from migen import *

from crg import CRG
from cossin import CosSinGen


class Test(Module):
    def __init__(self, platform):
        self.submodules += CRG(platform)

        for i in range(1):
            cs = CosSinGen()
            self.submodules += cs
            x = Signal.like(cs.x)
            y = Signal.like(cs.y)
            self.sync += [
                cs.z.eq(Cat(platform.request("test_point"), cs.z)),
                y.eq(cs.y),
                x.eq(cs.x),
                platform.request("user_led").eq(x | y == 0),
            ]


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform()
    test = Test(platform)
    platform.build(test)
