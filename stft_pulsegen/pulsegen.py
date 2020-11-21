# SingularitySurfer 2020


import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint

from block_fft import Fft
from super_interpolator import SuperInterpolator
from operator import and_


class Pulsegen(Module):
    """ Pulsegen main module

    Parameters
    ----------
    width_d:
    """

    def __init__(self, decoder, width_d=16, size_fft=64):
        self.submodules.fft = fft = Fft(n=size_fft, ifft=True, width_int=16, width_wram=16)
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
               p.eq(p+1)),




            # fft load logic

            If(decoder.get("fft_load", "read") == 1,



            ),
        ]


#     def sim(self):
#         for i in range(1500):
#             yield
#             # x = yield self.out0
#             # if x > 700: print(x)
#
#
# if __name__ == "__main__":
#     test = Pulsegen()
#     run_simulation(test, test.sim(), vcd_name="pulsegen.vcd")
