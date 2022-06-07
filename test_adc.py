#!/usr/bin/python3
# testbench for iir.rs

import unittest
from adc import Adc, AdcParams
from migen import *


def testbench(dut):
    yield
    yield dut.start.eq(1)
    yield dut.sdo[0].eq(1)
    yield dut.sdo2n.eq(0)
    for _ in range(1000):
        yield dut.clkout.eq(dut.sck)
        yield


class TestInter(unittest.TestCase):
    def setUp(self):
        pass


if __name__ == "__main__":
    adc_p = AdcParams(width=16, channels=2, lanes=2,
                      t_cnvh=8, t_conv=3, t_rtt=10)
    dut = Adc(None, adc_p)
    run_simulation(dut, testbench(
        dut), vcd_name="adc.vcd")
