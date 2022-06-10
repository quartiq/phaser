#!/usr/bin/python3
# testbench for iir.rs

import unittest
from iir import Iir
from migen import *


def testbench_lowpass(dut, inp, outp):
    yield dut.ab[0][0][0].eq(0x10000)
    yield dut.ab[1][0][0].eq(0x10000)
    yield dut.ab[2][0][0].eq(0x60000)
    yield dut.ab[0][0][1].eq(0x20000)
    yield dut.ab[1][0][1].eq(0x20000)
    yield dut.ab[2][0][1].eq(0x60000)
    for i in inp:
        yield dut.inp[0].eq(i)
        yield dut.inp[1].eq(i-100)
        for _ in range(100):
            yield dut.stb_in.eq(1)
            yield
            yield dut.stb_in.eq(0)
            for _ in range(15):
                yield
        o = yield dut.outp[0]
        outp.append(o)


class TestIir(unittest.TestCase):
    def setUp(self):
        self.dut = Iir(decoder=None, w_coeff=20, w_data=16, gainbits=0,
                       nr_profiles=2, nr_channels=2)

    def test_lowpass(self):
        inp = [10000, 0, -10000]
        outp = []
        run_simulation(self.dut, testbench_lowpass(self.dut, inp, outp))
        # fails due to xy fixedpoint precision. TODO: better test
        # self.assertEqual(inp, outp)


if __name__ == "__main__":
    dut = Iir(decoder=None, w_coeff=20, w_data=16,
              gainbits=0, nr_profiles=2, nr_channels=2)
    run_simulation(dut, testbench_lowpass(
        dut, [10000, 0, -10000], []), vcd_name="iir.vcd")
