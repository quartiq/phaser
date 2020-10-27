import unittest
import numpy as np
from migen import *
from block_fft import Fft
from fft_model import FftModel


def prep_mem(x, width):
    """combine real and imag part for simulation input"""
    y = np.zeros(len(x), dtype="complex")
    for i, k in enumerate(x):
        y[i] = (int(k.real) & int("0x0000ffff", 0)) | (int(k.imag) << width)
    return y.real.astype('int').tolist()


def bit_rev(x):
    """bit reverse"""
    y = np.zeros(len(x), dtype="complex")
    for i, k in enumerate(x):  # bit reverse
        binary = bin(i)
        reverse = binary[-1:1:-1]
        pos = int(reverse + (int(np.log2(len(x))) - len(reverse)) * '0', 2)
        y[i] = x[pos]
    return y


class TestFft(unittest.TestCase):
    """All tests compare the simulation output against a bit-accurate numeric model with
    maximum amplitude input coefficients and randomized phase"""

    def setUp(self):
        seed = np.random.randint(2 ** 32)
        np.random.seed(seed)
        print(f'random seed: {seed}')
        self.ampl = 2048
        self.n = 128
        self.x = np.ones(self.n, dtype="complex")
        phase = np.random.rand(self.n) * 2 * np.pi
        self.x = self.x * self.ampl * np.exp(1j * phase)

    def run_fft_sim(self, y, scaling):
        x_o_sim = np.zeros(self.fft.n, dtype="complex")  # simulation output

        def fft_sim():
            """input output testbench for 128 point fft"""
            p = 0
            for i in range(1024):
                yield
                yield self.fft.start.eq(0)
                if i < self.fft.n:  # load in values
                    yield self.fft.x_in_we.eq(1)
                    yield self.fft.x_in_adr.eq(i)
                    yield self.fft.x_in.eq(y[i])
                if i == self.fft.n + 1:  # start fft
                    yield self.fft.x_in_we.eq(0)
                    yield self.fft.start.eq(1)
                    yield self.fft.en.eq(1)
                    yield self.fft.scaling.eq(scaling)
                if (yield self.fft.done):  # retrieve ifft output
                    yield self.fft.x_out_adr.eq(p)
                    p += 1
                    xr2cpl = yield self.fft.x_out[:self.fft.width_o]  # x real in twos complement
                    xi2cpl = yield self.fft.x_out[self.fft.width_o:]  # x imag in twos complement
                    if xr2cpl & (1 << self.fft.width_o - 1):
                        xr = xr2cpl - 2 ** self.fft.width_o
                    else:
                        xr = xr2cpl
                    if xi2cpl & (1 << self.fft.width_o - 1):
                        xi = xi2cpl - 2 ** self.fft.width_o
                    else:
                        xi = xi2cpl
                    if p >= 3:
                        x_o_sim[p - 3] = xr + 1j * xi
                if p >= (self.fft.n + 2):
                    break

        run_simulation(self.fft, fft_sim())
        return x_o_sim

    def test_bitreversed(self):
        """ bitreversed input test for 128 point fft with randomized phases."""
        self.fft = Fft(n=128, ifft=True, input_bitreversed=True, width_int=16, width_wram=16)
        fft_model = FftModel(self.x, w_p=14)
        x_o_model = fft_model.full_fft(scaling='one', ifft=True)
        y = bit_rev(self.x)
        y = prep_mem(y, self.fft.width_int)
        x_o_sim = self.run_fft_sim(y, 0)
        self.assertEqual(x_o_model.tolist(), x_o_sim.tolist())

    def test_natural(self):
        """ natural order input test for 128 point fft"""
        self.fft = Fft(n=128, ifft=True, width_int=16, width_wram=16)
        fft_model = FftModel(self.x, w_p=14)
        x_o_model = fft_model.full_fft(scaling='one', ifft=True)
        y = prep_mem(self.x, self.fft.width_int)
        x_o_sim = self.run_fft_sim(y, 0)
        self.assertEqual(x_o_model.tolist(), x_o_sim.tolist())

    def test_scaling(self):
        """ 2**5 scaling test of fft calculation"""
        self.fft = Fft(n=128, ifft=True, width_int=16, width_wram=16)
        fft_model = FftModel(self.x, w_p=14)
        x_o_model = fft_model.full_fft(scaling=int('0011101', 2), ifft=True)
        y = prep_mem(self.x, self.fft.width_int)
        x_o_sim = self.run_fft_sim(y, int('0011101', 2))
        self.assertEqual(x_o_model.tolist(), x_o_sim.tolist())
