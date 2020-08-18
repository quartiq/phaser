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
                    i_BITSLIP=self.bitslip_req,
                    i_CLK=ClockSignal("sys2"), i_CLKB=~ClockSignal("sys2"),
                    i_CLKDIV=ClockSignal(), i_RST=ResetSignal(), i_CE1=1,
                    # LSB is past, Q1 is closest to D
                    o_Q1=data[3], o_Q2=data[2], o_Q3=data[1], o_Q4=data[0])
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
                # MSB is future, D1 is closest to Q
                i_D1=data[0], i_D2=data[1], i_D3=data[2], i_D4=data[3],
                i_TCE=1, i_OCE=1, i_T1=0,
                o_OQ=pin),
            Instance("OBUFDS", i_I=pin, o_O=eem.data7_p, o_OB=eem.data7_n)
        ]


class Slipper(Module):
    def __init__(self, width):
        self.data = Signal(width)
        self.valid = Signal()
        self.bitslip = Signal()

        good = Signal()
        pending = Signal(4, reset_less=True)
        self.comb += [
            good.eq(self.data == Replicate(self.data[0], width)),
            self.bitslip.eq(pending[0]),
        ]
        self.sync += [
            pending[0].eq((pending == 0) & ~good),
            pending[1:].eq(pending),
            self.valid.eq(good & (pending == 0)),
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

        self.sync += platform.request("user_led").eq(Cat(self.link.data) == 0)


if __name__ == "__main__":
    from phaser import Platform
    from crg import CRG
    platform = Platform(load=False)
    test = Test(platform)
    platform.build(test)
