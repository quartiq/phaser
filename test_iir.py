#!/usr/bin/python3
# testbench for iir.py

import unittest
from iir import Iir
from migen import *


def rounding(dut, inp, coeff, outp):
    yield dut.inp[0].eq(inp)
    yield dut.coeff[0][0][0].eq(coeff)
    yield dut.coeff[1][0][0].eq(coeff)
    yield dut.coeff[2][0][0].eq(0)
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    o = yield dut.outp[0]
    outp.append(o)
    yield dut.coeff[0][0][0].eq(coeff)
    yield dut.coeff[1][0][0].eq(coeff + 1)  # add one LSB, should round up now
    yield dut.coeff[2][0][0].eq(0)
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    o = yield dut.outp[0]
    outp.append(o)


def profile_switch(dut, inp, coeff, offset, outp):
    yield dut.inp[0].eq(inp)
    yield dut.coeff[0][0][0].eq(coeff[0])
    yield dut.coeff[1][0][0].eq(coeff[0])
    yield dut.offset[0][0].eq(offset[0])
    yield dut.coeff[0][1][0].eq(coeff[1])
    yield dut.coeff[1][1][0].eq(coeff[1])
    yield dut.offset[1][0].eq(offset[1])
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    o = yield dut.outp[0]
    outp.append(o)
    yield
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for i in range(15):
        if i == 5:
            yield dut.ch_profile[0].eq(1)

        yield
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    yield dut.stb_in.eq(1)
    yield
    yield dut.stb_in.eq(0)
    for _ in range(15):
        yield
    o = yield dut.outp[0]
    outp.append(o)


class TestIir(unittest.TestCase):
    def setUp(self):
        self.dut = Iir(w_coeff=24, w_data=16, log2_a0=15, n_profiles=2, n_channels=2)

    def test_profile_switch(self):
        inp = 1000
        coeff = [0x200000, 0x300000]
        offset = [10, 30]
        outp = []
        run_simulation(self.dut, profile_switch(self.dut, inp, coeff, offset, outp))
        self.assertEqual(inp // 2 + offset[0], outp[0])
        self.assertEqual(inp * 3 // 4 + offset[1], outp[1])

    def test_rounding(self):
        inp = 2345
        coeff = 0x200000  # 0.25 for both b0, b1
        outp = []
        run_simulation(self.dut, rounding(self.dut, inp, coeff, outp))
        self.assertEqual(inp // 2, outp[0])
        self.assertEqual((inp // 2) + 1, outp[1])
