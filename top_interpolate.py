from migen import *
from crg import CRG
from link import Link
from decode import Decode
from duc import PhasedDUC
from dac_data import DacData


class Phaser(Module):
    def __init__(self, platform):
        eem = platform.request("eem", 0)
        self.submodules.link = Link(eem)
        self.submodules.crg = CRG(platform, link=self.link.phy.clk)
        platform.add_period_constraint(eem.data0_p, 4.*8)
        platform.add_false_path_constraint(eem.data0_p, self.crg.cd_sys2.clk)
        self.submodules.decoder = Decode(
            n_sample=14, n_channel=2, n_mux=8, n_frame=8*10)
        self.comb += [
            self.decoder.frame.eq(self.link.checker.frame),
            self.decoder.stb.eq(self.link.checker.frame_stb),
        ]
        self.sync += [
            self.decoder.registers["duc"][0].write[:4].eq(0),  # up, clr
        ]
        self.submodules.data = DacData(platform.request("dac_data"))
        self.comb += [
            self.data.data_sync.eq(self.decoder.zoh.sample_mark),
        ]
        for i in range(2):
            duc = PhasedDUC(n=2, pwidth=18, fwidth=32)
            self.submodules += duc
            self.comb += [
                duc.clr.eq(self.decoder.registers["duc"][0].write[2 + i]),
                duc.i[0].eq(self.decoder.zoh.sample[i]),
                duc.i[1].eq(self.decoder.zoh.sample[i]),
            ]
            self.sync += [
                If(self.decoder.registers["duc"][0].write[i],
                    duc.f.eq(self.decoder.get_write("duc{}_f".format(i))),
                    duc.p.eq(self.decoder.get_write("duc{}_p".format(i))),
                ),
            ]
            for j, (ji, jo) in enumerate(zip(duc.i, duc.o)):
                self.comb += [
                    self.data.data[2*j][i].eq(jo.i),
                    self.data.data[2*j + 1][i].eq(jo.q),
                ]


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform(load=False)
    test = Phaser(platform)
    platform.build(test, build_name="phaser")
