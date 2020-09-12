from migen import *
from misoc.interconnect.stream import Endpoint
from misoc.cores.fir import MACFIR, HBFMACUpsampler
from misoc.cores.cic import SuperCIC
from misoc.cores.duc import complex


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
        self.body = Signal(n_mux*n_channel*2*b_sample)
        self.body_stb = Signal()
        self.sample = [Record(complex(b_sample)) for _ in range(n_channel)]
        self.sample_stb = Signal()
        samples = [Signal(n_channel*2*b_sample, reset_less=True)
                   for _ in range(n_mux)]
        assert len(Cat(samples)) == len(self.body)
        # maybe TODO: shift registers need fewer muxes
        i_sample = Signal(max=n_mux, reset_less=True)  # body pointer
        i_interp = Signal(max=n_interp, reset_less=True)  # interpolation
        self.comb += [
            Cat([(_.i[-b_sample:], _.q[-b_sample:]) for _ in self.sample]).eq(
                Array(samples)[i_sample]),
        ]
        self.sync += [
            i_interp.eq(i_interp - 1),
            self.sample_stb.eq(0),
            If(i_interp == 0,
                i_interp.eq(n_interp - 1),
                i_sample.eq(i_sample - 1),
                self.sample_stb.eq(1),
            ),
            If(self.body_stb,
                Cat(samples).eq(self.body),
                i_sample.eq(n_mux - 1),  # early sample is most significant
                i_interp.eq(n_interp - 1),
            )
        ]


class InterpolateChannel(Module):
    def __init__(self):
        # ciccomp: cic droop and gain, rate 1/10, gain 2**9/5**4 ~ 0.9, 9 taps
        # maybe TODO: use symmetry for power
        self.submodules.ciccomp = MACFIR(9, scale=16)
        for i, ci in enumerate(
                [24, -85, 281, -1314, 55856, -1314, 281, -85, 24]):
            self.ciccomp.coeff.sr[i].reset = ci
        # hbf1: rate 1/10 -> 1/5, gain=1, 39 taps
        self.submodules.hbf0 = HBFMACUpsampler(
            [-167, 0, 428, 0, -931, 0, 1776, 0, -3115, 0, 5185, 0, -8442, 0,
                14028, 0, -26142, 0, 82873, 131072, 82873, 0, -26142, 0, 14028,
                0, -8442, 0, 5185, 0, -3115, 0, 1776, 0, -931, 0, 428, 0,
                -167])
        # hbf1: rate 1/5 -> 2/5, gain=1, 19 taps
        self.submodules.hbf1 = HBFMACUpsampler(
            [294, 0, -1865, 0, 6869, 0, -20436, 0, 80679, 131072, 80679, 0,
                -20436, 0, 6869, 0, -1865, 0, 294])
        # cic: rate 2/5 -> 2/1, gain=5**4
        # the CIC doesn't cope with FIR overshoot and baseband data must be
        # band limited and/or backed off. Maybe TODO: clipping
        self.submodules.cic = SuperCIC(n=5, r=5, width=16)
        self.input = Endpoint([("data", (14, True))])
        self.output = Endpoint([("data0", (16, True)), ("data1", (16, True))])
        # align MACs to MSB to save power, keep one bit headroom for FIR
        # overshoot.
        scale_in = len(self.ciccomp.sample.load.data) - len(self.input.data) - 1
        scale_out = len(self.hbf1.output.data) - len(self.cic.input.data) - 1
        bias_out = (1 << scale_out - 1) - 1  # round half down bias
        # cic gain is r**(n-1) = 5**4, compensate with 2**-9,
        # the rest (2**9/5**4) is applied by ciccomp
        scale_cic = 9
        bias_cic = (1 << scale_cic - 1) - 1  # round half down bias
        self.comb += [
            self.input.connect(self.ciccomp.sample.load, omit=["data"]),
            self.ciccomp.sample.load.data.eq(self.input.data << scale_in),
            self.ciccomp.out.connect(self.hbf0.input),
            self.hbf0.output.connect(self.hbf1.input),
            self.hbf1.output.connect(self.cic.input, omit=["data"]),
            self.cic.input.data.eq((self.hbf1.output.data + bias_out) >>
                scale_out),
            self.cic.output.connect(self.output, omit=["data0", "data1"]),
            self.output.data0.eq((self.cic.output.data0 + bias_cic) >>
                scale_cic),
            self.output.data1.eq((self.cic.output.data1 + bias_cic) >>
                scale_cic),
        ]
