from migen import *
from migen.build.generic_platform import *
from migen.genlib.io import DifferentialOutput, DifferentialInput
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine
from crg import AsyncResetSynchronizerBUFG, CRG


class LinkCRG(Module):
    def __init__(self, d0_p, d0_n):
        self.clock_domains.cd_link = ClockDomain()
        self.clock_domains.cd_link2 = ClockDomain(reset_less=True)

        platform.add_period_constraint(d0_p, 4.*8)
        self.link_buf = Signal()
        self.specials += Instance("IBUFGDS",
            i_I=d0_p, i_IB=d0_n,
            o_O=self.link_buf)

        locked = Signal()
        fb = Signal()
        link = Signal()
        link2 = Signal()
        clk200 = Signal()
        clk200_buf = Signal()
        delay_rdy = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=4.*8, p_DIVCLK_DIVIDE=1, i_CLKIN1=self.link_buf,
                p_CLKFBOUT_MULT_F=32, i_CLKFBIN=fb, o_CLKFBOUT=fb,
                o_LOCKED=locked,
                #p_CLKOUT0_DIVIDE_F=4, p_CLKOUT0_PHASE=0, o_CLKOUT0=sys,
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0, o_CLKOUT1=link2,
                #p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90, o_CLKOUT2=link2q,
                p_CLKOUT3_DIVIDE=4, p_CLKOUT3_PHASE=0, o_CLKOUT3=link,
                p_CLKOUT4_DIVIDE=5, p_CLKOUT4_PHASE=0, o_CLKOUT4=clk200,
            ),
            Instance("BUFG", i_I=link, o_O=self.cd_link.clk),
            Instance("BUFG", i_I=link2, o_O=self.cd_link2.clk),
            # Instance("BUFG", i_I=sys2q, o_O=self.cd_sys2q.clk),
            Instance("BUFH", i_I=clk200, o_O=clk200_buf),
            Instance("IDELAYCTRL",
                i_REFCLK=clk200_buf, i_RST=~locked, o_RDY=delay_rdy),
        ]
        self.submodules += AsyncResetSynchronizerBUFG(self.cd_link,
            ~(locked & delay_rdy))



class Test(Module):
    def __init__(self, platform):
        #self.submodules.crg = LinkCRG(eem.data0_p, eem.data0_n)
        self.submodules.crg = CRG(platform)

        eem = platform.request("eem")
        mid = int(4e-9/4/78e-12/2)

        ld = Signal()  # load delay
        ce = Signal()  # inc delay
        cnt = Signal(5)
        cnt_out = Signal(5)
        bitslip_req = Signal()
        bitslip_done = Signal(reset_less=True)
        bitslip_pend = Signal(2, reset_less=True)
        self.sync += [
            Cat(bitslip_pend, bitslip_done).eq(
                Cat(bitslip_req, bitslip_pend)),
        ]
        self.comb += [
            If(cnt_out >= mid,
                cnt.eq(cnt_out - mid),
            ).Else(
                cnt.eq(cnt_out + mid),
            )
        ]

        platform.add_period_constraint(eem.data0_p, 4.*8)
        tt = Signal(7)
        for i in range(7):
            buf = Signal()
            dly = Signal()
            data = Signal(4)
            self.specials += [
                DifferentialInput(
                    getattr(eem, "data{}_p".format(i)),
                    getattr(eem, "data{}_n".format(i)),
                    buf),
                Instance("IDELAYE2",
                    p_IDELAY_TYPE="VAR_LOAD", p_IDELAY_VALUE=15,
                    p_SIGNAL_PATTERN="DATA" if i else "CLOCK",
                    i_C=ClockSignal(),
                    i_LD=1 if i else ld,
                    i_CE=0 if i else ce,
                    i_INC=1,
                    i_CNTVALUEIN=cnt_out if i else 15,
                    o_CNTVALUEOUT=Signal() if i else cnt_out,
                    i_IDATAIN=buf, o_DATAOUT=dly),
                Instance("ISERDESE2",
                    p_DATA_RATE="DDR", p_DATA_WIDTH=4,
                    p_INTERFACE_TYPE="NETWORKING", p_NUM_CE=1,
                    p_IOBDELAY="IFD",
                    i_DDLY=dly,
                    i_BITSLIP=bitslip_req,
                    i_CLK=ClockSignal("sys2"), i_CLKB=~ClockSignal("sys2"),
                    i_CLKDIV=ClockSignal(), i_RST=ResetSignal(), i_CE1=1,
                    o_Q1=data[3], o_Q2=data[2], o_Q3=data[1], o_Q4=data[0])
            ]
            self.sync += tt[i].eq(data == 0)
        self.sync += platform.request("user_led").eq(tt == 0)
        self.specials += [
            DifferentialOutput(Signal(), eem.data7_p, eem.data7_n)
        ]


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform(load=False)
    test = Test(platform)
    platform.build(test)
