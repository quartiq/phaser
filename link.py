from migen import *
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine


class Phy(Module):
    def __init__(self, eem):
        mid = int(4e-9/4/78e-12/2)

        self.clk = Signal()  # link clock
        self.ld = Signal()  # load delay
        self.ce = Signal()  # inc delay
        self.bitslip = Signal()
        self.cnt_out = Signal(5)
        self.data = [Signal(4) for i in range(7)]
        self.miso = Signal(4)

        cnt = Signal(5)
        self.comb += [
            If(self.cnt_out >= mid,
                cnt.eq(self.cnt_out - mid),
            ).Else(
                cnt.eq(self.cnt_out + mid),
            )
        ]

        for i, data in enumerate(self.data):
            buf = Signal()
            dly = Signal()
            thru = Signal()
            attr = {("DIFF_TERM", "TRUE")}
            if i == 0:
                attr.add(("IBUF_LOW_PWR", "FALSE"))
            self.specials += [
                Instance("IBUFGDS" if i == 0 else "IBUFDS", attr=attr,
                    i_I=getattr(eem, "data{}_p".format(i)),
                    i_IB=getattr(eem, "data{}_n".format(i)),
                    o_O=buf),
                Instance("IDELAYE2",
                    p_IDELAY_TYPE="VAR_LOAD", p_IDELAY_VALUE=0,
                    p_SIGNAL_PATTERN="DATA" if i else "CLOCK",
                    i_C=ClockSignal(),
                    i_LD=1 if i else self.ld,
                    i_CE=0 if i else self.ce,
                    i_INC=1,
                    i_CNTVALUEIN=self.cnt_out if i else cnt,
                    o_CNTVALUEOUT=Signal() if i else self.cnt_out,
                    i_IDATAIN=buf, o_DATAOUT=dly),
                Instance("ISERDESE2",
                    p_DATA_RATE="DDR", p_DATA_WIDTH=4,
                    p_INTERFACE_TYPE="NETWORKING", p_NUM_CE=1,
                    p_IOBDELAY="IFD",
                    i_D=buf, i_DDLY=dly,
                    i_BITSLIP=self.bitslip,
                    i_CLK=ClockSignal("sys2"), i_CLKB=~ClockSignal("sys2"),
                    i_CLKDIV=ClockSignal(), i_RST=ResetSignal(), i_CE1=1,
                    # MSB first, Q1 is closest to D
                    o_Q1=data[0], o_Q2=data[1], o_Q3=data[2], o_Q4=data[3],
                    o_O=thru)
            ]
            if i == 0:
                self.comb += self.clk.eq(thru)
        pin = Signal()
        data = self.miso
        self.specials += [
            Instance("OSERDESE2",
                p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                p_DATA_WIDTH=4, p_TRISTATE_WIDTH=1,
                i_RST=ResetSignal(),
                i_CLK=ClockSignal("sys2"),
                i_CLKDIV=ClockSignal(),
                # LSB first, D1 is closest to Q
                i_D1=data[0], i_D2=data[1], i_D3=data[2], i_D4=data[3],
                i_TCE=1, i_OCE=1, i_T1=0,
                o_OQ=pin),
            Instance("OBUFDS", i_I=pin, o_O=eem.data7_p, o_OB=eem.data7_n)
        ]


class Slipper(Module):
    """Bitslip controller.

    Verifies `width` equal bits per cycle.
    If not, asserts bitslip and enforces latency blocking.
    Use bit index `width//2` as data.
    """
    def __init__(self, width):
        self.data = Signal(width)
        self.valid = Signal()
        self.bitslip = Signal()

        good = Signal()
        pending = Signal(3, reset_less=True)
        self.comb += [
            # serdes sample match
            good.eq(self.data == Replicate(self.data[0], width)),
            self.bitslip.eq(pending[0]),
            # match and slip done
            self.valid.eq(good & (pending == 0)),
        ]
        self.sync += [
            pending.eq(Cat(~good & (pending == 0), pending)),
        ]


class Unframer(Module):
    """Unframes the clk, marker, and data bit streams into a framed multibit
    stream

    * `n_data`: number of clk+data lanes
    * `t_clk` is the clock pattern length
    * `n_frame` clock cycles per frame
    """
    def __init__(self, n_data, t_clk, n_frame):
        n_marker = n_frame//2 + 1

        # clock and data inputs
        self.data_in = Signal(n_data)
        self.data_in_stb = Signal()
        # paybload data output
        self.data_out = Signal(n_data - 1, reset_less=True)
        self.data_out_stb = Signal()
        self.end_of_frame = Signal(reset_less=True)

        # 0b0000111 reset (plus the data[0] LSB)
        clk_sr = Signal(t_clk - 1, reset_less=True,
                        reset=((1 << t_clk//2) - 1) << (t_clk//2 - 1))
        clk_stb = Signal()
        self.clk_stb = clk_stb  # debug
        marker_sr = Signal(n_marker, reset_less=True,
                           reset=((1 << n_marker - 1) - 1) << 1)
        marker_stb = Signal()
        self.marker_stb = marker_stb  # debug

        self.comb += [
            # clock pattern match (00001111)
            clk_stb.eq(Cat(self.data_in[0], clk_sr) == (1 << t_clk//2) - 1),
            # marker pattern match (000001x)
            marker_stb.eq(marker_sr == 1),
        ]
        self.sync += [
            clk_sr.eq(Cat(self.data_in[0], clk_sr)),
            If(clk_stb,
                marker_sr.eq(Cat(self.data_in[1], marker_sr)),
            ),
            #If(~self.data_in_stb,
            #    clk_sr.eq(clk_sr.reset),
            #    marker_sr.eq(marker_sr.reset),
            #),
            self.data_out_stb.eq(self.data_in_stb),
            self.data_out.eq(self.data_in[1:]),
            self.end_of_frame.eq(clk_stb & marker_stb),
        ]


class Checker(Module):
    """Check CRC and assemble a frame"""
    def __init__(self, n_data, t_clk, n_frame):
        n_word = n_data*t_clk
        n_marker = n_frame//2 + 1
        n_crc = n_data

        self.data = Signal(n_data)
        self.data_stb = Signal()
        self.end_of_frame = Signal()
        self.frame = Signal(n_word*n_frame - n_marker - n_crc)
        self.frame_stb = Signal()
        self.crc_err = Signal(8)
        # response bitstream
        self.miso = Signal(reset_less=True)
        # response data, latched on end_of_frame
        self.response = Signal(n_frame*t_clk, reset_less=True)

        poly = {
            # 6: 0x27,  # CRC-6-CDMA2000-A
            6: 0x2f,  # CRC-6-GSM
        }[n_data]
        self.submodules.crc = LiteEthMACCRCEngine(
            data_width=n_data, width=n_data, polynom=poly)
        self.crc.last.reset_less = True
        crc_good = Signal()
        crc = Signal.like(self.crc.last, reset_less=True)
        self.comb += [
            crc_good.eq(self.crc.next == 0),
            # crc_good.eq(1),  # TODO
            # LiteEthMACCRCEngine takes LSB first
            self.crc.data.eq(self.data[::-1]),
        ]
        self.sync += [
            self.crc.last.eq(self.crc.next),
            If(self.end_of_frame | ~self.data_stb,
                self.crc.last.eq(0),
                If(~crc_good,
                    self.crc_err.eq(self.crc_err + 1),
                ),
            ),
        ]

        frame_buf = Signal(n_word*n_frame, reset_less=True)
        self.sync += [
            frame_buf.eq(Cat(self.data, frame_buf)),
            self.frame_stb.eq(self.end_of_frame & crc_good & self.data_stb),
        ]

        frame_parts = []
        for i in range(n_frame):
            if i == 0:
                offset = n_crc
            elif i < n_marker + 1:
                offset = 1
            else:
                offset = 0
            frame_parts.append(frame_buf[i*n_word + offset: (i + 1)*n_word])
        assert len(Cat(frame_parts)) == len(self.frame)
        self.comb += self.frame.eq(Cat(frame_parts))

        response_sr = Signal.like(self.response)
        self.comb += self.miso.eq(response_sr[-1])
        self.sync += [
            response_sr[1:].eq(response_sr),
            If(self.frame_stb,
                response_sr.eq(self.response),
            )
        ]


class Link(Module):
    """Kasli-Phaser link implementation

    * Like the Fastino link but with 8 bits per clock cycle
    * 1 clock lane, 6 phaser input data lanes, 1 phaser output data lane
    """
    def __init__(self, eem):
        self.submodules.phy = Phy(eem)
        n_serde = len(self.phy.data[0])
        self.submodules.slip = Slipper(n_serde - 1)
        self.comb += [
            self.slip.data.eq(self.phy.data[0]),  # clk
            self.phy.bitslip.eq(self.slip.bitslip),
        ]
        self.submodules.unframe = Unframer(
            n_data=7, n_frame=10, t_clk=8)
        self.comb += [
            self.unframe.data_in_stb.eq(self.slip.valid),
            self.unframe.data_in.eq(Cat([
                d[n_serde//2 - 1] for d in self.phy.data])),
        ]
        self.submodules.checker = Checker(n_data=6, n_frame=10, t_clk=8)
        self.comb += [
            self.checker.data.eq(self.unframe.data_out),
            self.checker.data_stb.eq(self.unframe.data_out_stb),
            self.checker.end_of_frame.eq(self.unframe.end_of_frame),
            self.phy.miso.eq(Replicate(self.checker.miso, n_serde)),
        ]


class Test(Module):
    def __init__(self, platform):
        eem = platform.request("eem", 0)
        platform.add_period_constraint(eem.data0_p, 4.*8)
        self.submodules.link = Link(eem)
        self.submodules.crg = CRG(platform, link=self.link.phy.clk)

        if True:
            platform.add_false_path_constraint(
                eem.data0_p, self.crg.cd_sys2.clk)
        else:
            for i in range(1, 7):
                pin = getattr(eem, "data{}_p".format(i))
                platform.add_platform_command(
                    "set_input_delay -0.25 -min -clock "
                    "[get_generated_clocks sys2] [get_ports {pin}]", pin=pin)
                platform.add_platform_command(
                    "set_input_delay 0.25 -max -clock "
                    "[get_generated_clocks sys2] [get_ports {pin}]", pin=pin)
                platform.add_platform_command(
                    "set_input_delay -0.25 -min -add_delay -clock_fall -clock "
                    "[get_generated_clocks sys2] [get_ports {pin}]", pin=pin)
                platform.add_platform_command(
                    "set_input_delay 0.25 -max -add_delay -clock_fall -clock "
                    "[get_generated_clocks sys2] [get_ports {pin}]", pin=pin)

        platform.toolchain.additional_commands.extend([
            "report_timing -nworst 20 -setup -hold -from [get_ports] "
            "-file {build_name}_timing_in.rpt",
        ])

        self.sync += platform.request("user_led").eq(Cat(
            self.link.checker.frame, self.link.checker.frame_stb) == 0)


if __name__ == "__main__":
    from phaser_platform import Platform
    from crg import CRG
    platform = Platform(load=False)
    test = Test(platform)
    platform.build(test)
