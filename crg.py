from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer


class AsyncResetSynchronizerBUFG(Module):
    def __init__(self, cd, async_reset):
        if not hasattr(async_reset, "attr"):
            i, async_reset = async_reset, Signal()
            self.comb += async_reset.eq(i)
        rst_meta = Signal()
        rst_unbuf = Signal()
        self.specials += [
            Instance("FDPE", p_INIT=1, i_D=0, i_PRE=async_reset,
                i_CE=1, i_C=cd.clk, o_Q=rst_meta,
                attr={"async_reg", "ars_ff1"}),
            Instance("FDPE", p_INIT=1, i_D=rst_meta, i_PRE=async_reset,
                i_CE=1, i_C=cd.clk, o_Q=rst_unbuf,
                attr={"async_reg", "ars_ff2"}),
            Instance("BUFG", i_I=rst_unbuf, o_O=cd.rst)
        ]


class CRG(Module):
    def __init__(self, platform, link=None):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sys2 = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys2q = ClockDomain(reset_less=True)

        clk125 = platform.request("clk125_gtp")
        platform.add_period_constraint(clk125, 8.)
        self.clk125 = Signal()
        self.clk125_div2 = Signal()
        self.clk125_buf = Signal()
        self.specials += [
            Instance("IBUFDS_GTE2",
                i_CEB=0,
                i_I=clk125.p, i_IB=clk125.n,
                o_O=self.clk125,
                o_ODIV2=self.clk125_div2),
            Instance("BUFG",
                i_I=self.clk125, o_O=self.clk125_buf),
        ]

        locked = Signal()
        fb = Signal()
        fb_buf = Signal()
        sys = Signal()
        sys2 = Signal()
        sys2q = Signal()
        clk200 = Signal()
        clk200_buf = Signal()
        delay_rdy = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                # p_BANDWIDTH="LOW",
                p_CLKIN1_PERIOD=8. if link is None else 4.*8,
                p_CLKFBOUT_MULT_F=8 if link is None else 4*8,
                p_DIVCLK_DIVIDE=1,
                i_CLKIN1=self.clk125_buf if link is None else link,
                i_CLKFBIN=fb_buf, o_CLKFBOUT=fb,
                o_LOCKED=locked,
                # p_CLKOUT0_DIVIDE_F=4, p_CLKOUT0_PHASE=0, o_CLKOUT0=sys,
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0, o_CLKOUT1=sys2,
                p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90, o_CLKOUT2=sys2q,
                p_CLKOUT3_DIVIDE=4, p_CLKOUT3_PHASE=0, o_CLKOUT3=sys,
                p_CLKOUT4_DIVIDE=5, p_CLKOUT4_PHASE=0, o_CLKOUT4=clk200,
            ),
            Instance("BUFG", i_I=fb, o_O=fb_buf),
            Instance("BUFG", i_I=sys, o_O=self.cd_sys.clk),
            Instance("BUFG", i_I=sys2, o_O=self.cd_sys2.clk),
            Instance("BUFG", i_I=sys2q, o_O=self.cd_sys2q.clk),
            Instance("BUFG", i_I=clk200, o_O=clk200_buf),
            Instance("IDELAYCTRL",
                i_REFCLK=clk200_buf, i_RST=~locked, o_RDY=delay_rdy),
        ]
        self.submodules += AsyncResetSynchronizerBUFG(
            self.cd_sys, ~(locked & delay_rdy))
