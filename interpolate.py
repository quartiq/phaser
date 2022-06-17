from migen import *
from misoc.interconnect.stream import Endpoint
from misoc.cores.fir import MACFIR, HBFMACUpsampler
from misoc.cores.cic import SuperCIC
from misoc.cores.duc import complex

from mac_hbf_upsampler import MAC_HBF_Upsampler
from mac_sym_fir import MAC_SYM_FIR


class SampleMux(Module):
    """Zero order hold interpolator.

    * `b_sample`: bits per sample (i or q)
    * `n_channel`: iq dac channels
    * `n_mux`: samples in a frame
    * `t_frame`: clock cycles per frame
    """

    def __init__(self, b_sample, n_channel, n_mux, t_frame):
        n_interp, n_rest = divmod(t_frame, n_mux)
        assert n_rest == 0
        self.body = Signal(n_mux * n_channel * 2 * b_sample)
        self.body_stb = Signal()
        self.sample = [Record(complex(b_sample)) for _ in range(n_channel)]
        self.sample_stb = Signal()
        # frame body shift register
        samples = [
            Signal(n_channel * 2 * b_sample, reset_less=True) for _ in range(n_mux)
        ]
        assert len(Cat(samples)) == len(self.body)
        i_interp = Signal(max=n_interp, reset_less=True)  # interpolation
        self.comb += [
            # early sample is most significant
            Cat([(_.i[-b_sample:], _.q[-b_sample:]) for _ in self.sample]).eq(
                samples[-1]
            )
        ]
        self.sync += [
            i_interp.eq(i_interp - 1),
            self.sample_stb.eq(0),
            If(
                i_interp == 0,
                Cat(samples[1:]).eq(Cat(samples)),
                i_interp.eq(n_interp - 1),
                self.sample_stb.eq(1),
            ),
            If(
                self.body_stb,
                Cat(samples).eq(self.body),
                i_interp.eq(n_interp - 1),
                self.sample_stb.eq(1),
            ),
        ]


class MiniFIFO(Module):
    """Minimal FIFO buffer, unit capacity"""

    def __init__(self, width):
        self.input = Endpoint([("data", width)])
        self.output = Endpoint([("data", width)])
        self.input.data.reset_less = True
        self.output.data.reset_less = True
        self.comb += [
            self.input.ack.eq(~self.output.stb | self.output.ack),
        ]
        self.sync += [
            If(
                self.output.stb & self.output.ack,
                self.output.stb.eq(0),
            ),
            If(
                self.input.stb & self.input.ack,
                self.output.data.eq(self.input.data),
                self.output.stb.eq(1),
            ),
        ]


class InterpolateChannel(Module):
    def __init__(self):
        h_fir = [24, -85, 281, -1314, 55856, -1314, 281, -85, 24]
        # ciccomp: cic droop and gain, rate 1/10, gain 2**9/5**4 ~ 0.9, 9 taps
        self.submodules.ciccomp = MAC_SYM_FIR(h_fir, width_d=24, width_coef=16)
        h_hbf0 = [
            -167,
            0,
            428,
            0,
            -931,
            0,
            1776,
            0,
            -3115,
            0,
            5185,
            0,
            -8442,
            0,
            14028,
            0,
            -26142,
            0,
            82873,
            131072,
            82873,
            0,
            -26142,
            0,
            14028,
            0,
            -8442,
            0,
            5185,
            0,
            -3115,
            0,
            1776,
            0,
            -931,
            0,
            428,
            0,
            -167,
        ]
        # hbf1: rate 1/10 -> 1/5, gain=1, 39 taps
        self.submodules.hbf0 = MAC_HBF_Upsampler(h_hbf0, width_d=24, width_coef=17)
        h_hbf1 = [
            294,
            0,
            -1865,
            0,
            6869,
            0,
            -20436,
            0,
            80679,
            131072,
            80679,
            0,
            -20436,
            0,
            6869,
            0,
            -1865,
            0,
            294,
        ]
        # hbf1: rate 1/5 -> 2/5, gain=1, 19 taps
        self.submodules.hbf1 = MAC_HBF_Upsampler(h_hbf1, width_d=24, width_coef=17)
        # cic: rate 2/5 -> 2/1, gain=5**4
        # the CIC doesn't cope with FIR overshoot and baseband data must be
        # band limited and/or backed off. Maybe TODO: clipping
        self.submodules.cic = SuperCIC(n=5, r=5, width=16)
        # buffer the odd/even stutter of the HBFs
        self.submodules.buf0 = MiniFIFO((len(self.hbf1.input.data), True))
        self.submodules.buf1 = MiniFIFO((len(self.cic.input.data), True))

        self.input = Endpoint([("data", (14, True))])
        self.output = Endpoint([("data0", (16, True)), ("data1", (16, True))])
        # align MACs to MSB to save power, keep one bit headroom for FIR
        # overshoot.
        scale_in = len(self.ciccomp.input.data) - len(self.input.data) - 1
        scale_out = len(self.hbf1.output.data) - len(self.cic.input.data) - 1
        bias_out = (1 << scale_out - 1) - 1  # round half down bias
        # cic gain is r**(n-1) = 5**4, compensate with 2**-9,
        # the rest (2**9/5**4) is applied by ciccomp
        scale_cic = 9
        bias_cic = (1 << scale_cic - 1) - 1  # round half down bias
        self.comb += [
            self.input.connect(self.hbf0.input, omit=["data"]),
            self.ciccomp.input.data.eq(self.input.data << scale_in),
            self.ciccomp.output.connect(self.hbf0.input),
            self.hbf0.output.connect(self.buf0.input),
            self.buf0.output.connect(self.hbf1.input),
            self.hbf1.output.connect(self.buf1.input, omit=["data"]),
            self.buf1.input.data.eq((self.hbf1.output.data + bias_out) >> scale_out),
            self.buf1.output.connect(self.cic.input),
            self.cic.output.connect(self.output, omit=["data0", "data1"]),
            self.output.data0.eq((self.cic.output.data0 + bias_cic) >> scale_cic),
            self.output.data1.eq((self.cic.output.data1 + bias_cic) >> scale_cic),
        ]
