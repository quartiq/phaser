from migen import *
from cossin import CosSinGen
from dac_data import DacData


def complex(width):
    return Record(
        [("i", (width, True)), ("q", (width, True))],
        reset_less=True)


class ComplexMultiplier(Module):
    def __init__(self, awidth=16, bwidth=None, pwidth=None):
        """
        pipelined, 3 DSP, round half up
        """
        if bwidth is None:
            bwidth = awidth
        if pwidth is None:
            pwidth = awidth + bwidth + 1
        self.a = complex(awidth)  # 5
        self.b = complex(bwidth)  # 5
        self.p = complex(pwidth)

        bias_bits = max(0, awidth + bwidth - pwidth)
        bias = 1 << bias_bits - 2 if bias_bits >= 2 else 0

        ai = [Signal((awidth, True), reset_less=True) for _ in range(3)]
        aq = [Signal((awidth, True), reset_less=True) for _ in range(3)]
        bi = [Signal((bwidth, True), reset_less=True) for _ in range(2)]
        bq = [Signal((bwidth, True), reset_less=True) for _ in range(2)]
        ad = Signal((awidth + 1, True), reset_less=True)
        bs = Signal((bwidth + 1, True), reset_less=True)
        bd = Signal((bwidth + 1, True), reset_less=True)
        m = [Signal((awidth + bwidth + 1, True), reset_less=True) for _ in range(6)]
        self.sync += [
            Cat(ai).eq(Cat(self.a.i, ai)),  # 1-3
            Cat(aq).eq(Cat(self.a.q, aq)),  # 1-3
            Cat(bi).eq(Cat(self.b.i, bi)),  # 1-2
            Cat(bq).eq(Cat(self.b.q, bq)),  # 1-2
            ad.eq(self.a.i - self.a.q),  # 1
            m[0].eq(ad*bi[0]),  # 2
            m[1].eq(m[0] + bias),  # 3
            bd.eq(bi[1] - bq[1]),  # 3
            bs.eq(bi[1] + bq[1]),  # 3
            m[2].eq(bd*ai[2]),  # 4
            m[3].eq(bs*aq[2]),  # 4
            m[4].eq(m[1]),  # 4
            m[5].eq(m[1]),  # 4
            self.p.i.eq((m[2] + m[4]) >> bias_bits),  # 5
            self.p.q.eq((m[3] + m[5]) >> bias_bits),  # 5
        ]
        self.latency = 5


class Accu(Module):
    def __init__(self, fwidth, pwidth):
        self.f = Signal(fwidth)  # 2
        self.p = Signal(pwidth)  # 1
        self.clr = Signal(reset=1)  # 2
        self.z = Signal(pwidth, reset_less=True)

        q = Signal(fwidth, reset_less=True)
        self.sync += [
            q.eq(q + self.f),
            If(self.clr,
                q.eq(0),
            ),
            self.z.eq(self.p + q[-pwidth:]),
        ]


class MCM(Module):
    def __init__(self, width, constants, sync=False):
        n = len(constants)
        self.i = i = Signal(width)  # int(sync)
        self.o = o = [Signal.like(self.i) for i in range(n)]

        ###

        # TODO: improve MCM
        assert range(n) == constants
        assert n <= 9

        if sync:
            ctx = self.sync
        else:
            ctx = self.comb
        if n > 0:
            ctx += o[0].eq(0)
        if n > 1:
            ctx += o[1].eq(i)
        if n > 2:
            ctx += o[2].eq(i << 1)
        if n > 3:
            ctx += o[3].eq(i + (i << 1))
        if n > 4:
            ctx += o[4].eq(i << 2)
        if n > 5:
            ctx += o[5].eq(i + (i << 2))
        if n > 6:
            ctx += o[6].eq(o[3] << 1)
        if n > 7:
            ctx += o[7].eq((i << 3) - i)
        if n > 8:
            ctx += o[8].eq(i << 3)


class PhasedAccu(Accu):
    def __init__(self, n=2, fwidth=32, pwidth=18):
        self.f = Signal(fwidth)  # 3
        self.p = Signal(pwidth)  # 2
        self.clr = Signal(reset=1)  # 3
        self.z = [Signal(pwidth, reset_less=True)
                  for _ in range(n)]

        self.submodules.mcm = MCM(fwidth, range(n), sync=True)
        q = [Signal(fwidth, reset_less=True) for _ in range(2)]
        self.sync += [
            q[0].eq(q[0] + (self.f << log2_int(n))),
            If(self.clr,
                q[0].eq(0),
            ),
            q[1].eq(q[0] + (self.p << fwidth - pwidth)),
            self.mcm.i.eq(self.f),
            [z.eq((q[1] + self.mcm.o[i])[-pwidth:])
                for i, z in enumerate(self.z)]
        ]


class PhaseModulator(Module):
    def __init__(self, **kwargs):
        self.submodules.cs = CosSinGen(**kwargs)
        self.submodules.mul = ComplexMultiplier(
            awidth=len(self.cs.x), pwidth=len(self.cs.x))
        self.z = self.cs.z
        self.i = self.mul.b
        self.o = self.mul.p
        self.sync += [
            self.mul.a.i.eq(self.cs.x),
            self.mul.a.q.eq(self.cs.y),
        ]


class PhasedDUC(Module):
    def __init__(self, **kwargs):
        self.submodules.accu = PhasedAccu(**kwargs)
        self.modulators = []
        for i in range(len(self.accu.z)):
            mod = PhaseModulator()
            self.modulators.append(mod)
            self.comb += mod.z.eq(self.accu.z[i][-len(mod.z):])
        self.submodules += self.modulators


class Test(Module):
    def __init__(self, platform):
        crg = CRG(platform)
        data = DacData(platform.request("dac_data"))
        self.submodules += crg, data
        ins = []
        for i in range(2):
            duc = PhasedDUC()
            self.submodules += duc
            ins.extend([duc.accu.f, duc.accu.p, duc.accu.clr])
            for j, mod in enumerate(duc.modulators):
                ins.extend([mod.i.i, mod.i.q])
                self.comb += [
                    data.data[2*i][j].eq(mod.o.i),
                    data.data[2*i + 1][j].eq(mod.o.q),
                ]
        self.sync += Cat(ins).eq(Cat(platform.request("test_point"), Cat(ins)))


if __name__ == "__main__":
    from phaser import Platform
    from crg import CRG
    platform = Platform(load=True)
    test = Test(platform)
    platform.build(test)
