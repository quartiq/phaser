# Copyright (C) 2020 by SingularitySurfer
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without l> imitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint


class SuperCicUS(Module):
    """Supersampled CIC filter upsampler. Interpolates the input by variable rate r.
    Processes two new output samples every clockcycle if input data isn't stalled.
    If stalled the core waits for new samples.

    Ingests on average r/2 samples every clockcycle. Eg. one sample every 3 clockcycles
    in case of r=6. For uneven r it alternates the waiting periods ie. 3-4-3-4-3-4 etc.
    clockcycles for r=7.

    Adapted from the Misoc DUC CIC.

    Parameters
    ----------
    width_d: width of the data input (and output if gaincompensated)
    n: cic order
    r_max: maximum interpolation rate
    gaincompensated: If True the output will have unity DC gain, else G=r**n
        Will use a ROM of size r_max and a DSP block.
    width_lut: Width oof the gain compensation ROM LUT if in use
    """

    def __init__(self, width_d=16, n=6, r_max=2048, gaincompensated=True, width_lut=18):
        if r_max < 2:
            raise ValueError()
        if n < 1:
            raise ValueError()
        b_max = np.ceil(np.log2(r_max))  # max bit growth

        ###
        self.input = Endpoint([("data", (width_d, True))])
        if gaincompensated:
            self.output = Endpoint([("data0", (width_d, True)),
                                    ("data1", (width_d, True))])
        else:
            self.output = Endpoint([("data0", (width_d + int(np.ceil(np.log2(r_max ** (n - 1)))), True)),
                                    ("data1", (width_d + int(np.ceil(np.log2(r_max ** (n - 1)))), True))])
        self.r = Signal(int(np.ceil(np.log2(r_max))))  # rate input (always at least two due to supersampling)
        ###

        self.width_d = width_d

        i = Signal.like(self.r)
        comb_ce = Signal()
        inp_stall = Signal()
        inp_stall_reg = Signal()
        r_reg = Signal.like(self.r)
        f_rst = Signal()

        self.sync += f_rst.eq(self.r != r_reg)  # handle ratechange

        # Filter "clocking" from the input. Halts if no new samples.
        self.comb += [
            comb_ce.eq(self.input.ack & self.input.stb),
            self.output.stb.eq(~inp_stall),
            inp_stall.eq(self.input.ack & ~self.input.stb)
        ]

        self.sync += [
            inp_stall_reg.eq(inp_stall)
        ]

        self.sync += [
            self.input.ack.eq((i == r_reg - 1) | inp_stall | (i == r_reg[1:] - 1)),
            r_reg.eq(self.r),
            If(~inp_stall_reg,
               i.eq(i + 1),
               ),
            If((i == r_reg - 1) | f_rst,
               i.eq(0),
               ),
        ]

        if gaincompensated:
            sig, shift = self._tweak_gain(r_reg, r_max, n, self.input.data, f_rst, width_lut=width_lut)
        else:
            sig = self.input.data

        width = len(sig)

        # comb stages, one pipeline stage each
        for _ in range(n):
            old = Signal((width, True), reset_less=True)
            width += 1
            diff = Signal((width, True), reset_less=True)
            self.sync += [
                If(comb_ce,
                   old.eq(sig),
                   diff.eq(sig - old),
                   ),
                If(f_rst,
                   old.eq(0),
                   diff.eq(0)
                   )
            ]

            sig = diff

        # zero stuffer, gearbox, and first integrator, one pipeline stage
        width -= 1
        sig_a = Signal((width, True), reset_less=True)
        sig_b = Signal((width, True), reset_less=True)
        sig_i = Signal((width, True), reset_less=True)
        self.comb += [
            sig_i.eq(sig_b + sig),
        ]
        self.sync += [
            sig_a.eq(sig_b),
            If(comb_ce,
               If((i == 0) & r_reg[0],
                  sig_a.eq(sig_i),
                  ),
               sig_b.eq(sig_i)
               ),
            If(f_rst,
               sig_a.eq(0),
               sig_b.eq(0),
               )
        ]

        # integrator stages, two pipeline stages each
        for _ in range(n - 1):
            sig_a0 = Signal((width, True), reset_less=True)
            sum_ab = Signal((width + 1, True), reset_less=True)
            width += int(b_max - 1)
            sum_a = Signal((width, True), reset_less=True)
            sum_b = Signal((width, True), reset_less=True)
            self.sync += [
                If(~inp_stall_reg,
                   sig_a0.eq(sig_a),
                   sum_ab.eq(sig_a + sig_b),
                   sum_a.eq(sum_b + sig_a0),
                   sum_b.eq(sum_b + sum_ab),
                   ),
                If(f_rst,
                   sig_a0.eq(0),
                   sum_ab.eq(0),
                   sum_a.eq(0),
                   sum_b.eq(0),
                   )
            ]
            sig_a, sig_b = sum_a, sum_b

        if gaincompensated:
            self.sync += [
                self.output.data0.eq(sig_a >> shift),
                self.output.data1.eq(sig_b >> shift),
            ]
        else:
            self.sync += [
                self.output.data0.eq(sig_a),
                self.output.data1.eq(sig_b),
            ]

    def _tweak_gain(self, r, r_max, n, x, f_rst, width_lut=18):
        """tweaks the DC gain of the cic to be unity for all ratechanges"""
        tweaks = np.arange(r_max)
        tweaks[0] = 1
        shifts = np.ceil(np.log2(tweaks ** (n - 1))).astype('int').tolist()
        bitshift_lut_width = int(np.ceil(np.log2(max(shifts))))
        # Nr. bits for the bitshifting LUT. The rest will be gaintweak LUT.
        tweaks = (np.ceil(np.log2(tweaks ** (n - 1))) - np.log2(tweaks ** (n - 1)))
        tweaks = (2 ** tweaks)
        tweaks = tweaks * 2 ** (width_lut - bitshift_lut_width - 1)
        tweaks = tweaks.astype('int').tolist()
        for i, e in enumerate(tweaks):
            tweaks[i] = tweaks[i] | (shifts[i] << (width_lut - bitshift_lut_width))
        lut = Memory(width_lut, r_max, init=tweaks, name="gaintweaks")
        port = lut.get_port(write_capable=False)
        self.specials += lut, port
        out = Signal((len(x) + n, True), reset_less=True)
        shift = Signal((bitshift_lut_width), reset_less=True)
        temp = Signal((width_lut - bitshift_lut_width + self.width_d, True), reset_less=True)
        tweak = Signal(width_lut - bitshift_lut_width)
        x_reg = Signal.like(x)
        self.sync += [
            x_reg.eq(x),
            port.adr.eq(r),
            tweak.eq(port.dat_r[:(width_lut - bitshift_lut_width)]),
            temp.eq(tweak * x_reg),
            out.eq(temp >> (width_lut - bitshift_lut_width - 1)),
            # out.eq((port.dat_r[:(width_lut - bitshift_lut_width)] * x) >> (width_lut - bitshift_lut_width - 1)),
            shift.eq(port.dat_r[(width_lut - bitshift_lut_width):]),
            If(f_rst,
               x_reg.eq(0),
               out.eq(0),
               temp.eq(0)
               )
        ]
        return out, shift
