from migen import *

from crg import CRG
from cossin import CosSinGen


class Top(Module):
    def __init__(self, platform):
        self.submodules += CRG(platform)

        i, o = [], []
        for _ in range(1 << 8):
            cs = CosSinGen()
            self.submodules += cs
            i.append(cs.z)
            o.extend([cs.x, cs.y])
        self.sync += [
            Cat(i).eq(Cat(platform.request("test_point"), Cat(i)))
        ]
        z = Signal(max(len(_) for _ in o), reset_less=True)
        for oi in o:
            z, z0 = Signal.like(z), z
            self.sync += [
                z.eq(z0 ^ oi)
            ]
        self.sync += platform.request("user_led").eq(z == 0)


if __name__ == "__main__":
    from platform import Platform
    platform = Platform(load=True)
    test = Top(platform)
    platform.build(test)
