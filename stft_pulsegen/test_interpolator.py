import unittest
import numpy as np
from migen import *

from super_interpolator import SuperInterpolator




class TestInterpolator(unittest.TestCase):

    def hbf_response(self, r):
        assert r in (4, 2), "unsupported rate"
        #  HBF0 impulse response:
        h_0 = [9, 0, -32, 0, 83, 0, -183, 0,
               360, 0, -650, 0, 1103, 0, -1780, 0,
               2765, 0, -4184, 0, 6252, 0, -9411, 0,
               14803, 0, -26644, 0, 83046, 131072, 83046, 0,
               -26644, 0, 14803, 0, -9411, 0, 6252, 0,
               -4184, 0, 2765, 0, -1780, 0, 1103, 0,
               -650, 0, 360, 0, -183, 0, 83, 0,
               -32, 0, 9]
        #  HBF1 impulse response:
        h_1 = [69, 0, -418, 0, 1512, 0, -4175, 0,
               9925, 0, -23146, 0, 81772, 131072, 81772, 0,
               -23146, 0, 9925, 0, -4175, 0, 1512, 0,
               -418, 0, 69]
        if r == 2:
            return h_0
        if r == 4:
            return h_1

    def setup_cic_model(self, r):
        self.n = 6
        self.width_lut = 18
        tweaks = np.arange(r // 4)
        tweaks[0] = 1
        self.shifts = np.ceil(np.log2(tweaks ** (self.n - 1))).astype('int').tolist()
        self.bitshift_lut_width = int(np.ceil(np.log2(max(self.shifts))))
        tweaks = (np.ceil(np.log2(tweaks ** (self.n - 1))) - np.log2(tweaks ** (self.n - 1)))
        tweaks = (2 ** tweaks)
        tweaks = tweaks * 2 ** (self.width_lut - self.bitshift_lut_width - 1)
        self.tweaks = tweaks.astype('int').tolist()

    def cic_model(self, x, r):
        '''computes the cic response as implemented in SuperCicUs'''
        h_cic = 1
        for i in range(self.n):
            h_cic = np.convolve(np.ones(r), h_cic)
        h_cic = h_cic.astype('int')
        print(h_cic.sum())
        for i, e in enumerate(x):
            x[i] = (e * self.tweaks[r]) >> (self.width_lut - self.bitshift_lut_width - 1)
        y_full = np.convolve(x, h_cic)
        for i, e in enumerate(y_full):
            y_full[i] = e >> self.shifts[r]
        return y_full.astype('int').tolist()

    def calc_delay(self, r):
        assert (r % 4 == 0) | (r == 2), "unsupported rate"
        if r == 2:
            return 18 + 20
        if r == 4:
            return 18 + 20 + 50 + 2
        if r > 4:
            if (r//4) % 2:
                return 18 + 20 + 50 + 2 + 28 + (((r // 4) - 1) * 94)
            else:
                return 18 + 20 + 50 + 2 + 28 + (((r // 4) - 1) * 94) + 1

    def interpolator_model(self, x, r):
        bias = (1 << 18 - 1) - 1
        # HBF0
        h = self.hbf_response(2)
        x_stuffed = []
        for xx in x:
            x_stuffed.append(xx)
            x_stuffed.append(0)
        x = (np.convolve(x_stuffed, h)).astype('int').tolist()
        x = [(xx+bias) >> 17 for xx in x]
        if r <= 2:
            return x

        # HBF1
        h = self.hbf_response(4)
        x_stuffed = []
        for xx in x:
            x_stuffed.append(xx)
            x_stuffed.append(0)
        x = (np.convolve(x_stuffed, h)).astype('int').tolist()
        x = [(xx+bias) >> 17 for xx in x]
        if r <= 4:
            return x

        # CIC
        r = r//4
        x_stuffed = []
        for xx in x:
            x_stuffed.append(xx)
            [x_stuffed.append(0) for _ in range(r - 1)]
        return self.cic_model(x_stuffed, r)

    def run_sim(self, x, r):
        y = []

        def sim():
            yield
            yield self.inter.r.eq(r)
            yield
            j = 0
            for i in range((r * 100) + 20):
                if j < len(x):
                    if (yield self.inter.input.ack):
                        yield self.inter.input.data.eq(x[j])
                        j += 1
                else:
                    yield self.inter.input.data.eq(0)
                yield self.inter.input.stb.eq(1)
                if (yield self.inter.output.stb):  # check for valid output data
                    v0 = yield self.inter.output.data0
                    # if v0 < 0:
                    #     v0 += 1
                    v1 = yield self.inter.output.data1
                    # if v1 < 0:
                    #     v1 += 1
                    y.append(v0)
                    y.append(v1)

                yield
        run_simulation(self.inter, sim())
        return y

    def setUp(self):
        n = 20  # nr input samples
        a_max = (2 ** 14) - 1  # max ampl
        r_max = 4096  # maximum ratechange

        seed = np.random.randint(2 ** 32)
        np.random.seed(seed)
        print(f'random seed: {seed}')
        self.x = (np.round(np.random.rand(n) * a_max)).astype('int').tolist()
        self.x.append(0)  # last value gets skiped during simulation but hard to change now...
        self.setup_cic_model(r_max)
        self.inter = SuperInterpolator(width_d=16, r_max=r_max//4)

    def test_hbf0(self):
        '''test for r=2, only hbf0 engaged'''
        r = 2

        y_model = self.interpolator_model(self.x, r)
        y_sim = self.run_sim(self.x, r)
        delay = self.calc_delay(r)
        y_sim = y_sim[delay: delay + len(y_model)]
        self.assertEqual(y_model, y_sim)

    def test_hbf01(self):
        '''test for r=4, hbf0 and hbf1 used'''
        r = 4

        y_model = self.interpolator_model(self.x, r)
        y_sim = self.run_sim(self.x, r)
        delay = self.calc_delay(r)
        y_sim = y_sim[delay: delay + len(y_model)]
        self.assertEqual(y_model, y_sim)

    def test_full(self):
        '''test for r>4, hbf0 + hbf1 + cic'''

        r = 36
        y_model = self.interpolator_model(self.x, r)
        y_sim = self.run_sim(self.x, r)
        delay = self.calc_delay(r)
        y_sim = y_sim[delay: delay + len(y_model)]
        self.assertEqual(y_model, y_sim)
