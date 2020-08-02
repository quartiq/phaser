from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer


class CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_clk200 = ClockDomain()

        clk125 = platform.request("clk125_gtp")
        platform.add_period_constraint(clk125, 8.)
        self.clk125_buf = Signal()
        self.clk125_div2 = Signal()
        self.specials += Instance("IBUFDS_GTE2",
            i_CEB=0,
            i_I=clk125.p, i_IB=clk125.n,
            o_O=self.clk125_buf,
            o_ODIV2=self.clk125_div2)

        mmcm_locked = Signal()
        mmcm_fb = Signal()
        mmcm_sys = Signal()
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=16.0,
                i_CLKIN1=self.clk125_div2,

                i_CLKFBIN=mmcm_fb,
                o_CLKFBOUT=mmcm_fb,
                o_LOCKED=mmcm_locked,

                # VCO @ 1GHz with MULT=16
                p_CLKFBOUT_MULT_F=16, p_DIVCLK_DIVIDE=1,
                p_CLKOUT0_DIVIDE_F=4, p_CLKOUT0_PHASE=0.0, o_CLKOUT0=mmcm_sys,
            ),
            Instance("BUFG", i_I=mmcm_sys, o_O=self.cd_sys.clk),
            AsyncResetSynchronizer(self.cd_sys, ~mmcm_locked),
        ]
