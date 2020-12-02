# SingularitySurfer 2020


import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint

from block_fft import Fft
from super_interpolator import SuperInterpolator
from operator import and_


class Fft_load(Module):
    """ fft coefficient loading logic

    In the first frame the fft_load reg is asserted, leading to the next frame writhing data into fft memory.
    The last fft coeff frame has to de-assert fft_load.

    """

    def __init__(self, decoder, fft, coef_per_frame):
        data = [Signal(fft.width_i * 2, reset_less=True)
                for _ in range(coef_per_frame)]
        b_adr = Signal(len(fft.x_in_adr))  # frame base adr, fft mem adr will incr. during frame data write
        dummy = Signal(fft.width_i * 2)  # empty dummy signal for shift reg

        datapos = Signal(int(np.ceil(np.log2(coef_per_frame + 1))))

        self.test = Signal()
        self.cnt = Signal(28)

        self.comb += [
            fft.x_in.eq(data[0]),
            fft.x_in_adr.eq(b_adr),
        ]

        self.sync += [

            self.cnt.eq(self.cnt + 1),
            If(decoder.fft_stb,  # buffer addr and data if new frame in fft load mode
               self.test.eq(1),
               b_adr.eq(decoder.zoh.body[:fft.width_i * 2]),
               Cat(data).eq(decoder.zoh.body[fft.width_i * 2:fft.width_i * 2 * (1 + coef_per_frame)]),
               datapos.eq(0),
               fft.x_in_we.eq(1),
               ).Elif(datapos != (coef_per_frame - 1),
                      datapos.eq(datapos + 1),
                      Cat(data).eq(Cat(data[1:], dummy)),  # shift out data
                      b_adr.eq(b_adr + 1),
                      If(reduce(and_, b_adr), fft.x_in_we.eq(0))  # check if adr overflowed and de-assert write enable
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
        self.submodules.fft = fft = Fft(n=size_fft, ifft=True, width_i=width_d, width_o=width_d, width_int=width_d, width_wram=width_d)
        self.submodules.loader = loader = Fft_load(decoder, fft, 4)

        self.submodules.inter_i = inter_i = SuperInterpolator(r_max=1024)
        self.submodules.inter_q = inter_q = SuperInterpolator(r_max=1024)

        pos = Signal(int(np.log2(size_fft)))  # position in fft mem
        p = Signal(16, reset=0)  # number repeats
        pdone = Signal(reset=1)  # pulse done signal

        self.comb += [
            inter_i.input.data.eq(fft.x_out[width_d:]),
            inter_q.input.data.eq(fft.x_out[:width_d]),
            fft.x_out_adr.eq(pos),
            fft.en.eq(1),
        ]

        self.sync += [

            # pulsegen settings
            inter_i.r.eq(decoder.get("interpolation_rate", "read")),
            inter_q.r.eq(decoder.get("interpolation_rate", "read")),
            fft.scaling.eq(decoder.get("fft_shiftmask", "read")),
            If(decoder.get("pulse_settings", "read") == 0,  # continous fft outpout
               If(inter_i.input.ack,
                  pos.eq(pos + 1)),

               ).Elif((decoder.get("pulse_settings", "read") == 1) & ~fft.busy,  # standard pulse mode with p repeats
                      If((decoder.get("pulse_trigger", "read") == 1) & (pdone == 1),
                         # TODO: check for fft/pulse busy/reasserted pulse_trigger to restart pulse or not??
                         p.eq(decoder.get("repeater", "read")),
                         decoder.get("pulsegen_busy", "write").eq(1),
                         decoder.get("pulse_trigger", "write").eq(0),  # de-assert trigger
                         pdone.eq(0),
                         pos.eq(0),
                         ).Elif(pdone == 0,
                                If(inter_i.input.ack,
                                   pos.eq(pos + 1)),
                                If(reduce(and_, pos),
                                   p.eq(p - 1)),
                                If(p == 0,
                                   pdone.eq(1),
                                   pos.eq(0),
                                   decoder.get("pulsegen_busy", "write").eq(0),
                                   ),
                                ).Else(
                          pdone.eq(1),
                          pos.eq(0),
                          decoder.get("pulsegen_busy", "write").eq(0),
                      ),
                      ),
            If(decoder.get("fft_start", "read") == 1,
               fft.start.eq(1)).Else(
                fft.start.eq(0)
            ),
            decoder.get("fft_busy", "write").eq(fft.busy),

        ]
