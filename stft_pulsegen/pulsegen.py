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

        self.submodules.fft = fft = Fft(n=size_fft, ifft=True, width_int=16, width_wram=16)
        #self.submodules.inter_i = inter_i = SuperInterpolator()
        self.submodules.inter_q = inter_q = SuperInterpolator()

        cnt = Signal(10)
        pos = Signal(int(np.log2(size_fft)))

        self.comb += [
            #inter_i.input.data.eq(0),#fft.x_out[width_d:]),
            inter_q.input.data.eq(fft.x_out[:width_d]),
            fft.en.eq(1),
            fft.scaling.eq(0xff),
            fft.x_out_adr.eq(pos),
            #inter_i.r.eq(2),
            #inter_q.r.eq(2),
        ]

        self.sync += [
            cnt.eq(cnt+1),
            #If(cnt[2], fft.start.eq(1)),
            If(inter_q.input.ack,
            pos.eq(pos + 1))
        ]

    def sim(self):
        for i in range(1500):
            yield
            #x = yield self.out0
            #if x > 700: print(x)

if __name__ == "__main__":
    test = Pulsegen()
    run_simulation(test, test.sim(), vcd_name="pulsegen.vcd")