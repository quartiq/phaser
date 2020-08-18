from migen import *
from crg import CRG
from link import Link
from duc import PhasedDUC
from dac_data import DacData


class Test(Module):
    def __init__(self, platform):
        eem = platform.request("eem", 0)
        self.submodules.link = Link(eem)
        self.submodules.crg = CRG(platform, link=self.link.phy.clk)
        platform.add_period_constraint(eem.data0_p, 4.*8)
        platform.add_false_path_constraint(eem.data0_p, self.crg.cd_sys2.clk)

        self.submodules.data = DacData(platform.request("dac_data"))
        ins = []
        for i in range(2):
            duc = PhasedDUC(n=2, pwidth=18, fwidth=32)
            self.submodules += duc
            ins.extend([duc.f, duc.p, duc.clr])
            for j, (ji, jo) in enumerate(zip(duc.i, duc.o)):
                ins.extend([ji.i, ji.q])
                self.comb += [
                    self.data.data[2*j][i].eq(jo.i),
                    self.data.data[2*j + 1][i].eq(jo.q),
                ]
        self.sync += [
            If(self.link.checker.frame_stb,
                Cat(ins).eq(self.link.checker.frame)
            )
        ]


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform(load=False)
    test = Test(platform)
    platform.build(test)
