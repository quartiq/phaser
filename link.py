from migen import *
from migen.build.generic_platform import *
from migen.genlib.io import DifferentialOutput, DifferentialInput
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine
from crg import AsyncResetSynchronizerBUFG


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
        self.specials += [
            Instance("MMCME2_BASE",
                p_CLKIN1_PERIOD=4.*8, p_DIVCLK_DIVIDE=1, i_CLKIN1=self.link_buf,
                p_CLKFBOUT_MULT_F=32, i_CLKFBIN=fb, o_CLKFBOUT=fb,
                o_LOCKED=locked,
                #p_CLKOUT0_DIVIDE_F=4, p_CLKOUT0_PHASE=0, o_CLKOUT0=sys,
                p_CLKOUT1_DIVIDE=2, p_CLKOUT1_PHASE=0, o_CLKOUT1=link2,
                #p_CLKOUT2_DIVIDE=2, p_CLKOUT2_PHASE=90, o_CLKOUT2=link2q,
                p_CLKOUT3_DIVIDE=4, p_CLKOUT3_PHASE=0, o_CLKOUT3=link,
                #p_CLKOUT4_DIVIDE=5, p_CLKOUT4_PHASE=0, o_CLKOUT4=clk200,
            ),
            Instance("BUFG", i_I=link, o_O=self.cd_link.clk),
            Instance("BUFG", i_I=link2, o_O=self.cd_link2.clk),
            # Instance("BUFG", i_I=sys2q, o_O=self.cd_sys2q.clk),
            # Instance("BUFH", i_I=clk200, o_O=self.cd_clk200.clk),
            # AsyncResetSynchronizer(self.cd_clk200, ~locked),
        ]
        self.submodules += AsyncResetSynchronizerBUFG(self.cd_link, ~locked)



class Test(Module):
    def __init__(self, platform):
        eem = platform.request("eem")
        self.submodules.crg = LinkCRG(eem.data0_p, eem.data0_n)
        self.specials += [
            DifferentialInput(
                getattr(eem, "data{}_p".format(i)),
                getattr(eem, "data{}_n".format(i)),
                Signal()) for i in range(1, 7)] + [
            DifferentialOutput(Signal(), eem.data7_p, eem.data7_n)
        ]
        led = platform.request("user_led")
        self.sync.link += led.eq(~led)


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform(load=True)
    test = Test(platform)
    platform.build(test)
