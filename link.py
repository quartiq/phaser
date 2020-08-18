from migen import *
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine


class Link(Module):
    def __init__(self, eem):
        mid = int(4e-9/4/78e-12/2)

        self.clk = Signal()  # link clock
        self.ld = Signal()  # load delay
        self.ce = Signal()  # inc delay
        self.bitslip = Signal()
        self.cnt_out = Signal(5)
        self.data = [Signal(4) for i in range(7)]
        self.out = Signal(4)

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
            self.specials += [
                Instance("IBUFGDS" if i == 0 else "IBUFDS",
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
                    # p_IOBDELAY="IFD",
                    p_IOBDELAY="NONE",
                    i_DDLY=dly, i_D=buf,
                    i_BITSLIP=self.bitslip,
                    i_CLK=ClockSignal("sys2"), i_CLKB=~ClockSignal("sys2"),
                    i_CLKDIV=ClockSignal(), i_RST=ResetSignal(), i_CE1=1,
                    # MSB first, Q1 is closest to D
                    o_Q1=data[0], o_Q2=data[1], o_Q3=data[2], o_Q4=data[3])
            ]
            if i == 0:
                self.comb += self.clk.eq(buf)
        pin = Signal()
        data = self.out
        self.specials += [
            Instance("OSERDESE2",
                p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                p_DATA_WIDTH=4, p_TRISTATE_WIDTH=1,
                p_INIT_OQ=0b00000000,
                i_RST=ResetSignal(),
                i_CLK=ClockSignal("sys2"),
                i_CLKDIV=ClockSignal(),
                # MSB first, D1 is closest to Q
                i_D1=data[3], i_D2=data[2], i_D3=data[1], i_D4=data[0],
                i_TCE=1, i_OCE=1, i_T1=0,
                o_OQ=pin),
            Instance("OBUFDS", i_I=pin, o_O=eem.data7_p, o_OB=eem.data7_n)
        ]


class Slipper(Module):
    """Bitslip controller.

    Verifies `width - 1` equal bits per cycle.
    If not, asserts bitslip and enforces latency.
    Use bit index `(width - 1)//2` as data.
    """
    def __init__(self, width):
        self.data = Signal(width)
        self.valid = Signal()
        self.bitslip = Signal()

        good = Signal()
        pending = Signal(4, reset_less=True)
        self.comb += [
            # serdes sample match
            good.eq(self.data[:-1] ==
                    Replicate(self.data[0], width - 1)),
            self.bitslip.eq(pending[0]),
        ]
        self.sync += [
            pending.eq(Cat((pending == 0) & ~good, pending)),
            # match and slip done
            self.valid.eq(good & (pending == 0)),
        ]


class Unframer(Module):
    """Unframes the clk, marker, and data bit streams into frames consisting of
    multiple payload chunks and one metadata chunk.

    * `n_data`: number of clk+data lanes
    * `t_clk` is the clock pattern length
    * `n_frame` clock cycles per frame
    * `n_payload` bits per payload
    * `n_meta` metadata bits per frame
    """
    def __init__(self, n_data, t_clk, n_frame, n_payload, n_meta):
        n_marker = n_frame//2 + 1
        n_frame_total = n_frame*t_clk*(n_data - 1)
        n_words, n_rest = divmod(n_frame_total - n_marker - n_meta, n_payload)
        assert n_rest == 0
        n_offset, n_rest = divmod(n_marker + n_meta, n_words)
        assert n_rest == 0
        t_payload, n_rest = divmod(n_frame*t_clk, n_words)
        assert n_rest == 0
        n_meta_in_marker = n_frame - n_marker

        # clock and data inputs
        self.data = Signal(n_data)
        # paybload data output
        self.payload = Signal(n_payload, reset_less=True)
        self.payload_stb = Signal()
        # metadata output
        self.meta = Signal(n_meta, reset_less=True)
        self.meta_stb = Signal()
        # response bitstream
        self.out = Signal(reset_less=True)
        # response data
        self.response = Signal(n_frame)

        clk_sr = Signal(t_clk - 1, reset_less=True)
        clk_stb = Signal()
        marker_sr = Signal(n_frame - 1, reset_less=True)
        marker_stb = Signal()
        meta_sr = Signal(n_meta - n_meta_in_marker, reset_less=True)
        assert len(self.meta) == len(meta_sr) + len(marker_sr) - (n_marker - 1)
        i_payload = Signal(max=t_payload)
        i_payload_stb = Signal()
        response_sr = Signal(n_frame, reset_less=True)

        self.comb += [
            # clock pattern match (00001111)
            clk_stb.eq(Cat(self.data[0], clk_sr) == (1 << t_clk//2) - 1),
            # marker pattern match (000001)
            marker_stb.eq(clk_stb & (
                Cat(self.data[1], marker_sr[:n_marker - 1]) == 1)),
            self.meta.eq(Cat(marker_sr[n_marker - 1:], meta_sr)),
            i_payload_stb.eq(i_payload == t_payload - 1),
            self.out.eq(response_sr[-1]),
        ]
        self.sync += [
            clk_sr.eq(Cat(self.data[0], clk_sr)),
            If(clk_stb,
                marker_sr.eq(Cat(self.data[1], marker_sr)),
            ),
            i_payload.eq(i_payload + 1),
            If(i_payload_stb | marker_stb,
                i_payload.eq(0),
            ),
            response_sr[1:].eq(response_sr),
            If(self.meta_stb,
                response_sr.eq(self.response),
            ),
            self.payload.eq(Cat(self.data[1 + n_offset:], self.payload)),
            self.payload_stb.eq(i_payload_stb),
            meta_sr.eq(Cat(self.data[2:1 + n_offset], self.meta)),
            self.meta_stb.eq(marker_stb),
        ]


class Test(Module):
    def __init__(self, platform):
        eem = platform.request("eem", 0)
        self.submodules.link = Link(eem)
        self.submodules.crg = CRG(platform, link=self.link.clk)

        if True:
            platform.add_period_constraint(eem.data0_p, 4.*8)
            platform.add_false_path_constraint(eem.data0_p, self.crg.cd_sys2.clk)
        else:
            # this needs to be late
            platform.add_platform_command(
                    "create_clock -name {clk} -period 32.0 [get_ports {clk}]",
                    clk=eem.data0_p)
            for i in range(1, 7):
                pin = getattr(eem, "data{}_p".format(i))
                platform.add_platform_command(
                    "set_input_delay -0.25 -min -clock [get_clocks {clk}] "
                    "[get_ports {pin}]", clk=eem.data0_p, pin=pin)
                platform.add_platform_command(
                    "set_input_delay 0.25 -max -clock [get_clocks {clk}] "
                    "[get_ports {pin}]", clk=eem.data0_p, pin=pin)
        platform.toolchain.additional_commands.extend([
            "report_timing -nworst 20 -setup -hold -from [get_ports] "
            "-file {build_name}_timing_in.rpt",
        ])

        n_serde = len(self.link.data[0])
        self.submodules.slip = Slipper(n_serde)
        self.comb += [
            self.slip.data.eq(self.link.data[0]),  # clk
            self.link.bitslip.eq(self.slip.bitslip),
        ]
        self.submodules.unframe = Unframer(
            n_data=7, n_frame=10, t_clk=8, n_payload=2*14,
            n_meta=6 + 1 + 9 + 8 + 2)
        self.comb += [
            # self.unframe.slip_valid.eq(self.slip.valid)
            [i.eq(o[n_serde//2 - 1]) for i, o in zip(self.unframe.data, self.link.data)],
            self.link.out.eq(Replicate(self.unframe.out, n_serde)),
        ]

        self.sync += platform.request("user_led").eq(Cat(self.unframe.payload,
            self.unframe.meta) == 0)


if __name__ == "__main__":
    from phaser import Platform
    from crg import CRG
    platform = Platform(load=False)
    test = Test(platform)
    platform.build(test)
