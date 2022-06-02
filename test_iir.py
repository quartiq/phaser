#!/usr/bin/python3
# testbench for iir.rs

from iir import Iir
from migen import *


dut = Iir(w_coeff=16, w_data=16, gainbits=0, nr_profiles=2, nr_channels=2)


def testbench_lowpass():
    yield dut.ab[0][0][0].eq(0x1000)
    yield dut.ab[1][0][0].eq(0x1000)
    yield dut.ab[2][0][0].eq(0x6000)
    yield dut.inp[0].eq(1000)
    for _ in range(100):
        yield dut.stb_in.eq(1)
        yield
        yield dut.stb_in.eq(0)
        for _ in range(10):
            yield


run_simulation(dut, testbench_lowpass(), vcd_name="iir.vcd")
