# SingularitySurfer 2020


import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint

from block_fft import Fft
from super_interpolator import SuperInterpolator


class Pulsegen(Module):
    """ Pulsegen main module

    Parameters
    ----------
    width_d:
    """

    def __init__(self, width_d=16, size_fft=256):

        self.submodules.fft = fft = Fft(n=size_fft)
        self.submodules.inter_i = inter_i = SuperInterpolator()
        self.submodules.inter_q = inter_q = SuperInterpolator()

        cnt = Signal(10)
        pos = Signal(int(np.log2(size_fft)))

        self.comb += [
            inter_i.input.data.eq(fft.x_out[:width_d]),
            inter_q.input.data.eq(fft.x_out[width_d:]),
            fft.en.eq(1),
            fft.scaling.eq(0xff),
            fft.x_out_adr.eq(pos),
            inter.r.eq(200),
        ]

        self.sync += [
            cnt.eq(cnt+1),
            If(cnt[-1], fft.start.eq(1)),
            If(inter.input.ack & fft.done,
               pos.eq(pos + 1))
        ]
