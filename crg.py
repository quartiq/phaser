from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer


class CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys2 = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys2q = ClockDomain(reset_less=True)
        self.clock_domains.cd_clk200 = ClockDomain()

        self.comb += platform.request("clk_sel").eq(0)  # mmcx internal

        clk125 = platform.request("clk125_gtp")
        platform.add_period_constraint(clk125, 8.)
        self.clk125_buf = Signal()
        self.clk125_div2 = Signal()
        self.specials += Instance("IBUFDS_GTE2",
            i_CEB=0,
            i_I=clk125.p, i_IB=clk125.n,
            o_O=self.clk125_buf,
            o_ODIV2=self.clk125_div2)

        locked = Signal()
        fb = Signal()
        sys = Signal()
        sys2 = Signal()
        sys2q = Signal()
        clk200 = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=16.0, p_DIVCLK_DIVIDE=1, i_CLKIN1=self.clk125_div2,
                p_CLKFBOUT_MULT_F=16, i_CLKFBIN=fb, o_CLKFBOUT=fb,
                o_LOCKED=locked,
                #p_CLKOUT0_DIVIDE_F=4, p_CLKOUT0_PHASE=0, o_CLKOUT0=sys,
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0, o_CLKOUT1=sys2,
                p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90, o_CLKOUT2=sys2q,
                p_CLKOUT3_DIVIDE=4, p_CLKOUT3_PHASE=0, o_CLKOUT3=sys,
                p_CLKOUT4_DIVIDE=5, p_CLKOUT4_PHASE=0, o_CLKOUT4=clk200,
            ),
            Instance("BUFG", i_I=sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=sys2, o_O=self.cd_sys2.clk),
            Instance("BUFG", i_I=sys2q, o_O=self.cd_sys2q.clk),
            Instance("BUFH", i_I=clk200, o_O=self.cd_clk200.clk),
            AsyncResetSynchronizer(self.cd_sys, ~locked),
            AsyncResetSynchronizer(self.cd_clk200, ~locked),
        ]
