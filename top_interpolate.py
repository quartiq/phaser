from migen import *
from crg import CRG
from link import Link
from duc import PhasedDUC
from dac_data import DacData


class Test(Module):
    def __init__(self, platform):
        self.submodules.crg = CRG(platform)
        eem = platform.request("eem", 0)
        # platform.add_period_constraint(eem.data0_p, 4.*8)
        self.submodules.link = Link(eem)
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
        self.sync += Cat(ins).eq(Cat(platform.request("test_point"), Cat(ins)))
        self.sync += platform.request("user_led").eq(Cat(self.link.data) == 0)


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform(load=False)
    test = Test(platform)
    platform.build(test)
