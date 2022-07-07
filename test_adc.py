#!/usr/bin/python3

import unittest
from adc import Adc, AdcParams
from migen import *


def bench(dut, done):
    yield
    yield dut.start.eq(1)
    yield dut.sdo[0].eq(1)
    yield dut.sdo2n.eq(0)
    for _ in range(1000):
        yield dut.clkout.eq(dut.sck)
    d = yield dut.done
    done.append(d)


class TestInter(unittest.TestCase):
    def setUp(self):
        adc_p = AdcParams(width=16, channels=2, lanes=2, t_cnvh=8, t_conv=3, t_rtt=10)
        self.dut = Adc(None, adc_p)

    def test(self):
        done = []
        run_simulation(self.dut, bench(self.dut, done))
        self.assertEqual(done[0], True)
