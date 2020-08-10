from migen import *
from migen.genlib.io import DifferentialOutput, DifferentialInput
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine


class Link(Module):
    def __init__(self, eem):
        mid = int(4e-9/4/78e-12/2)

        self.ld = Signal()  # load delay
        self.ce = Signal()  # inc delay
        self.cnt_out = Signal(5)
        self.bitslip_req = Signal()
        self.bitslip_done = Signal(reset_less=True)
        self.data = [Signal(4) for i in range(7)]
        self.out = Signal(4)

        cnt = Signal(5)
        bitslip_pend = Signal(2, reset_less=True)
        self.sync += [
            Cat(bitslip_pend, self.bitslip_done).eq(
                Cat(self.bitslip_req, bitslip_pend)),
        ]
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
                DifferentialInput(
                    getattr(eem, "data{}_p".format(i)),
                    getattr(eem, "data{}_n".format(i)),
                    buf),
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
                    i_DDLY=dly,
                    i_BITSLIP=self.bitslip_req,
                    i_CLK=ClockSignal("sys2"), i_CLKB=~ClockSignal("sys2"),
                    i_CLKDIV=ClockSignal(), i_RST=ResetSignal(), i_CE1=1,
                    # LSB is past, Q1 is closest to D
                    o_Q1=data[3], o_Q2=data[2], o_Q3=data[1], o_Q4=data[0])
            ]
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
            DifferentialOutput(pin, eem.data7_p, eem.data7_n)
        ]


class Test(Module):
    def __init__(self, platform):
        #self.submodules.crg = LinkCRG(eem.data0_p, eem.data0_n)
        self.submodules.crg = CRG(platform)
        eem = platform.request("eem", 0)
        # platform.add_period_constraint(eem.data0_p, 4.*8)
        self.submodules.link = Link(eem)
        self.sync += platform.request("user_led").eq(Cat(self.link.data) == 0)


if __name__ == "__main__":
    from phaser import Platform
    from crg import CRG
    platform = Platform(load=False)
    test = Test(platform)
    platform.build(test)
