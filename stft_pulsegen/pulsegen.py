# SingularitySurfer 2020


import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint

from block_fft import Fft
from super_interpolator import SuperInterpolator
from operator import and_


class Fft_load(Module):
    """ fft coefficient loading logic"""

    def __init__(self, decoder, fft, coef_per_frame):
        data = [Signal(fft.width_i * 2, reset_less=True)
                for _ in range(coef_per_frame)]
        b_adr = Signal.like(fft.x_in_adr)  # frame base adr, fft mem adr will incr. during frame data write
        dummy = Signal(fft.width_i * 2)  # empty dummy signal for shift reg

        datapos = Signal(int(np.ceil(np.log2(coef_per_frame + 1))))

        self.comb += [
            fft.x_in.eq(data[0]),
            fft.x_in_adr.eq(b_adr),
        ]

        self.sync += [
            If(decoder.stb & decoder.get("fft_load", "read") == 1,  # buffer addr and data if new frame in fft load mode
               b_adr.eq(decoder.zoh.body[:fft.width_i * 2]),
               Cat(data).eq(decoder.zoh.body[fft.width_i * 2:fft.width_i * 2 * (1 + coef_per_frame)]),
               datapos.eq(0),
               fft.x_in_we.eq(1),
               ).Elif(datapos != (coef_per_frame - 1),
                      b_adr.eq(b_adr + 1),
                      datapos.eq(datapos + 1),
                      Cat(data).eq(Cat(data[1:], dummy)),  # shift out data
                      ).Else(
                fft.x_in_we.eq(0),
            ),
        ]


class Pulsegen(Module):
    """ Pulsegen main module

    Parameters
    ----------
    width_d:
    """

    def __init__(self, decoder, width_d=16, size_fft=64):
        self.submodules.fft = fft = Fft(n=size_fft, ifft=True, width_int=16, width_wram=16)
        self.submodules.loader = loader = Fft_load(decoder, fft, 4)

        self.submodules.inter_i = inter_i = SuperInterpolator(r_max=1024)
        self.submodules.inter_q = inter_q = SuperInterpolator(r_max=1024)

        pos = Signal(int(np.log2(size_fft)))  # position in fft mem
        p = Signal(16, reset=0)  # number repeats

        self.comb += [
            inter_i.input.data.eq(fft.x_out[width_d:]),
            inter_q.input.data.eq(fft.x_out[:width_d]),
            fft.en.eq(1),
            fft.scaling.eq(0xff),
            fft.x_out_adr.eq(pos),
        ]

        self.sync += [

            # pulse start/stop logic

            If(inter_q.input.ack,
               pos.eq(pos + 1)),
            If(reduce(and_, pos),
               p.eq(p + 1)),

        ]
