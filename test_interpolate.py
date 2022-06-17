import numpy as np
import unittest

from migen import *

import interpolate


def feed(endpoint, x, rate):
    n, d = rate
    t = 0
    for i, xi in enumerate(x):
        while t * n < i * d:
            yield
            t += 1
        yield endpoint.data.eq(int(xi))
        yield endpoint.stb.eq(1)
        yield
        t += 1
        while not (yield endpoint.ack):
            yield
        yield endpoint.stb.eq(0)


@passive
def retrieve(endpoint, o):
    yield
    while True:
        yield endpoint.ack.eq(1)
        yield
        while not (yield endpoint.stb):
            yield
        o.append(((yield endpoint.data0), (yield endpoint.data1)))
        yield endpoint.ack.eq(0)


class TestInter(unittest.TestCase):
    def setUp(self):
        self.dut = interpolate.InterpolateChannel()

    def test_init(self):
        self.assertEqual(len(self.dut.input.data), 14)
        self.assertEqual(len(self.dut.output.data0), 16)

    def test_seq(self):
        # impulse response plus latency
        x = [(1 << 13) - 1] + [0] * (30 + 10)
        y = []
        run_simulation(
            self.dut,
            [feed(self.dut.input, x, rate=(1, 10)), retrieve(self.dut.output, y)],
            vcd_name="int.vcd",
        )
        y = np.ravel(y)
        print(repr(y))
        # y0 =
        # np.testing.assert_equal(y, y0)
