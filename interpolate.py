from migen import *
from misoc.cores.fir import SymMACFIR, HBFMACUpsampler
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
        # FIXME: center tap, gain 125/128
        self.submodules.ciccomp = SymMACFIR(3)
        for i, ci in enumerate([263, -5, 1]):
            self.ciccomp.coeff.sr[i].reset = ci
        self.submodules.hbf0 = HBFMACUpsampler(
            [-10, 0, 27, 0, -58, 0, 111, 0, -195, 0, 324, 0, -528, 0, 877, 0,
             -1634, 0, 5180, 8192, 5180, 0, -1634,
             0, 877, 0, -528, 0, 324, 0, -195, 0, 111, 0, -58, 0, 27, 0, -10])
        self.submodules.hbf1 = HBFMACUpsampler(
            [-4, 0, 21, 0, -74, 0, 313, 512, 313, 0, -74, 0, 21, 0, -4])
        self.submodules.cic = SuperCIC(n=4, r=5, width=16)
        self.input = self.ciccomp.sample.load
        self.output = self.cic.output
        self.comb += [
            self.ciccomp.out.connect(self.hbf0.sample.load),
            self.hbf0.out.connect(self.hbf1.sample.load),
            self.hbf1.out.connect(self.cic.input),
        ]
