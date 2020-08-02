from migen import *
from migen.genlib.cdc import MultiReg, AsyncResetSynchronizer, BlindTransfer
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine


class CRG(Module):
    def __init__(self, platform):
        clk125 = platform.request("clk125_gtp")
        platform.add_period_constraint(clk125, 8.)
        self.clk125_buf = Signal()
        self.clk125_div2 = Signal()
        self.specials += Instance("IBUFDS_GTE2",
            i_CEB=0,
            i_I=clk125.p, i_IB=clk125.n,
            o_O=self.clk125_buf,
            o_ODIV2=self.clk125_div2)
        cd_sys = ClockDomain("sys")
        self.clock_domains += cd_sys
        self.comb += [
            cd_sys.rst.eq(0),
            cd_sys.clk.eq(self.clk125_buf),
        ]


class Blink(Module):
    def __init__(self, platform):
        self.submodules.crg = CRG(platform)
        led = platform.request("user_led")
        self.sync += led.eq(~led)


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform()
    top = Blink(platform)
    platform.build(top, build_name=top.__class__.__name__.lower())
