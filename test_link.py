import numpy as np
import unittest

from migen import *

import link


class TestSlip(unittest.TestCase):
    def setUp(self):
        self.dut = link.Slipper(width=3)

    def test_init(self):
        self.assertEqual(len(self.dut.data), 3)

    def do(self, data):
        yield self.dut.data.eq(data)
        yield
        valid = yield self.dut.valid
        yield
        bitslip = yield self.dut.bitslip
        return valid, bitslip

    def test_seq(self):
        def gen():
            v, b = yield from self.do(0b000)
            self.assertEqual(v, 1)
            self.assertEqual(b, 0)
            v, b = yield from self.do(0b111)
            self.assertEqual(v, 1)
            self.assertEqual(b, 0)
            v, b = yield from self.do(0b001)
            self.assertEqual(v, 0)
            self.assertEqual(b, 1)
            for i in range(3):
                yield
                self.assertEqual((yield self.dut.bitslip), 0)
            yield
            self.assertEqual((yield self.dut.bitslip), 1)
        run_simulation(self.dut, gen())


def pack(data):
    n_frame = 10
    n_data = 7
    t_clk = 8
    n_marker = n_frame//2 + 1
    assert len(data) == n_frame*(n_data - 1)*t_clk - n_marker
    frame = []
    for i in range(n_frame):
        for j in range(t_clk):
            b = 0
            if j >= t_clk//2:
                b |= 1
            if j == t_clk - 1:
                if i == n_frame - 1:
                    b |= 2
                elif i < n_frame - n_marker:
                    b |= data.pop(0) << 1
            else:
                b |= data.pop(0) << 1
            for k in range(2, n_data):
                b |= data.pop(0) << k
            frame.append(b)
    assert len(data) == 0, data
    return frame


def bytes_to_bits(byt):
    bit = []
    for b in byt:
        for i in reversed(range(8)):
            bit.append((b >> i) & 1)
    return bit


class TestUnframe(unittest.TestCase):
    def setUp(self):
        self.dut = link.Unframer(n_data=7, t_clk=8, n_frame=10)

    def test_init(self):
        self.assertEqual(len(self.dut.data), 7)

    def feed_bits(self, bits):
        for b in bits:
            yield self.dut.data.eq(b)
            yield self.dut.valid.eq(1)
            yield

    def record_frame(self, bits, n_max=100):
        i = 0
        while True:
            if (yield self.dut.payload_stb):
                bits.append((yield self.dut.payload))
            if (yield self.dut.end_of_frame):
                break
            yield
            i += 1
            if n_max and i > n_max:
                break

    def test_mini(self):
        bits = []
        run_simulation(self.dut,
            [self.feed_bits([]), self.record_frame(bits)])
        self.assertEqual(bits, [])

    def test_frame(self):
        frame = pack([0] * (10*8*6 - 6))
        bits = []
        run_simulation(self.dut,
            [self.feed_bits(frame), self.record_frame(bits)])
        self.assertEqual(bits, [0] * (10*8 - 1) + [1])
