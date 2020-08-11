import unittest

from migen import *

import duc


class TestAccu(unittest.TestCase):
    def setUp(self):
        self.dut = duc.Accu(fwidth=32, pwidth=16)

    def test_init(self):
        self.assertEqual(len(self.dut.f), 32)
        self.assertEqual(len(self.dut.p), 16)
        self.assertEqual(len(self.dut.z), 16)

    def test_seq(self):
        def gen():
            yield self.dut.clr.eq(0)
            yield self.dut.p.eq(0x01)
            yield
            yield
            self.assertEqual((yield self.dut.z), 0x1)
            yield self.dut.f.eq(0x80 << 16)
            yield
            yield
            yield
            self.assertEqual((yield self.dut.z), 0x81)
            yield
            self.assertEqual((yield self.dut.z), 0x101)
            yield self.dut.clr.eq(1)
            yield
            yield self.dut.clr.eq(0)
            yield
            yield
            self.assertEqual((yield self.dut.z), 0x1)
        run_simulation(self.dut, gen())


class TestPhasedAccu(unittest.TestCase):
    def setUp(self):
        self.dut = duc.PhasedAccu(n=2, fwidth=32, pwidth=16)

    def test_init(self):
        self.assertEqual(len(self.dut.f), 32)
        self.assertEqual(len(self.dut.p), 16)
        self.assertEqual(len(self.dut.z), 2)
        self.assertEqual(len(self.dut.z[0]), 16)

    def test_seq(self):
        def gen():
            yield self.dut.clr.eq(0)
            yield self.dut.p.eq(0x01)
            yield
            yield
            yield
            self.assertEqual((yield self.dut.z[0]), 0x01)
            self.assertEqual((yield self.dut.z[1]), 0x01)
            yield self.dut.f.eq(0x10 << 16)
            yield
            yield
            yield
            self.assertEqual((yield self.dut.z[0]), 0x01)
            self.assertEqual((yield self.dut.z[1]), 0x11)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x21)
            self.assertEqual((yield self.dut.z[1]), 0x31)
            yield self.dut.clr.eq(1)
            yield
            yield
            yield self.dut.clr.eq(0)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x81)
            self.assertEqual((yield self.dut.z[1]), 0x91)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x01)
            self.assertEqual((yield self.dut.z[1]), 0x01)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x01)
            self.assertEqual((yield self.dut.z[1]), 0x01)
            yield self.dut.f.eq(0x20 << 16)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x01)
            self.assertEqual((yield self.dut.z[1]), 0x11)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x21)
            self.assertEqual((yield self.dut.z[1]), 0x31)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x41)
            self.assertEqual((yield self.dut.z[1]), 0x61)
            yield
            self.assertEqual((yield self.dut.z[0]), 0x81)
            self.assertEqual((yield self.dut.z[1]), 0xa1)
        run_simulation(self.dut, gen())


class TestMul(unittest.TestCase):
    def setUp(self):
        self.dut = duc.ComplexMultiplier(awidth=16)

    def test_init(self):
        for sig in self.dut.a.i, self.dut.a.q, self.dut.b.i, self.dut.b.q:
            self.assertEqual(len(sig), 16)
        for sig in self.dut.p.i, self.dut.p.q:
            self.assertEqual(len(sig), 33)

    def get(self, a, b):
        yield self.dut.a.i.eq(a[0])
        yield self.dut.a.q.eq(a[1])
        yield self.dut.b.i.eq(b[0])
        yield self.dut.b.q.eq(b[1])
        for _ in range(5 + 1):
            yield
        pi = (yield self.dut.p.i)
        pq = (yield self.dut.p.q)
        return pi, pq

    def check(self, abp):
        def gen():
            for a, b, p in abp:
                with self.subTest(a=a, b=b, p=p):
                    pi = yield from self.get(a, b)
                    self.assertEqual(pi, p)
        run_simulation(self.dut, gen())

    def test_gen(self):
        """Full width exact complex multiplication"""
        seq = 0, 1, -2, 0x7fff, -0x8000
        self.check([((ai, aq), (bi, bq), (ai*bi - aq*bq, ai*bq + aq*bi))
                    for ai in seq for aq in seq for bi in seq for bq in seq])

    def test_round(self):
        """Reounded 16x16 -> 16 bit multiplication"""
        self.dut = duc.ComplexMultiplier(awidth=16, pwidth=16)
        # max is |m + 1j*m| < 0x8000
        m = int((0x7fff << 16 - 1 - 1)**.5)
        bias_bits = 16 - 1
        bias = (1 << bias_bits - 1) - 1  # round half up
        def do(ai, aq, bi, bq):
            pi = (ai*bi - aq*bq + bias) >> bias_bits
            pq = (ai*bq + aq*bi + bias) >> bias_bits
            return pi, pq

        seq = 0, 0x4321, m, -m
        self.check([((ai, aq), (bi, bq), do(ai, aq, bi, bq))
                    for ai in seq for aq in seq for bi in seq for bq in seq])

        # corner cases one maximum component
        m = 0x7fff
        seq = [
            (m, 0, m, 0),
            (0, m, m, 0),
            (-m, 0, m, 0),
            (-m, 0, 0, -m),
            (-m - 1, 0, m, 0),
            (-m - 1, 0, -m, 0),
        ]
        self.dut = duc.ComplexMultiplier(awidth=16, pwidth=16)
        self.check([(ab[:2], ab[2:], do(*ab)) for ab in seq])


class TestPhasedDUC(unittest.TestCase):
    def setUp(self):
        self.dut = duc.PhasedDUC(n=2, fwidth=32, pwidth=16)

    def test_init(self):
        self.assertEqual(len(self.dut.f), 32)
        self.assertEqual(len(self.dut.p), 16)
        for i in self.dut.i + self.dut.o:
            self.assertEqual(len(i.i), 16)
            self.assertEqual(len(i.q), 16)

    def seq(self, samples, f, p, expect):
        n = len(self.dut.i)
        self.assertEqual(len(samples) % n, 0)
        output = []
        f_latency = 7
        mul_latency = 8

        def get():
            for _ in range(f_latency + mul_latency):
                yield
            for _ in range(len(samples)//n):
                for out in self.dut.o:
                    oi = yield out.i
                    oq = yield out.q
                    output.append(oi + 1j*oq)
                yield

        def set():
            yield self.dut.clr.eq(1)
            yield self.dut.p.eq(p)
            yield self.dut.f.eq(f)
            yield
            yield self.dut.clr.eq(0)
            for _ in range(f_latency):
                yield
            for i, ins in enumerate(samples):
                q, i = divmod(i, n)
                if not i:
                    yield
                yield self.dut.i[i].i.eq(round(ins.real))
                yield self.dut.i[i].q.eq(round(ins.imag))

        run_simulation(self.dut, [get(), set()])
        self.assertEqual(len(output), len(samples))
        expect = [round(_.real) + 1j*round(_.imag) for _ in expect]
        self.assertEqual(output, expect)
        return output

    def test_latency(self):
        i = [0, 10, 0, 40]
        o = self.seq(i, 0, 0, i)

    def test_neg(self):
        i = [0, 10, 50, 30j, -50j, 40-20j, -100+1j, 0]
        o = self.seq(i, 0, 0x8000, [-_ for _ in i])

    def test_quad(self):
        i = [0, 10, 50, 30j, -50j, 40-20j, -100+1j, 0]
        o = self.seq(i, 0, 0x4000, [1j*_ for _ in i])

    def test_freq(self):
        i = list(range(32))
        f = 0x800 << 16
        o = self.seq(i, f, 0,
                     [1j**(i/8.)*j for i, j in enumerate(i)])
