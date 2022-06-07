#!/usr/bin/python3
# first order iir for multiple channels and profiles with one DSP and no blockram
#
# round half down
#
# Notes: I don't know how the "out or range" extra channel to wait for DSP pipe gets
# synthesized as the selector for data register array.
#
# Maybe Todo: replace [pc != 0] with [!OR(pc)]
from migen import *

NR_COEFF = 3  # [b0, b1, a0] number of coefficients for a first order iir


class Dsp(Module):
    def __init__(self):
        # xilinx dsp architecture (subset)
        self.a = a = Signal((30, True), reset_less=True)
        self.b = b = Signal((18, True), reset_less=True)
        self.c = c = Signal((48, True), reset_less=True)
        self.mux_p = mux_p = Signal()  # accumulator mux
        self.m = m = Signal((48, True), reset_less=True)
        self.p = p = Signal((48, True), reset_less=True)
        self.sync += [
            m.eq(a * b),
            p.eq(Mux(mux_p, m + p, m + c))
        ]


class Iir(Module):
    def __init__(self, w_coeff, w_data, gainbits, nr_profiles, nr_channels):
        # input strobe signal (start processing all channels)
        self.stb_in = stb_in = Signal()
        self.stb_out = stb_out = Signal()  # output strobe signal (all channels done)
        self.inp = inp = Array(Signal((w_data, True))
                               for _ in range(nr_channels))
        self.outp = outp = Array(Signal((w_data, True))
                                 for _ in range(nr_channels))
        # ab registers for all channels and profiles
        self.ab = ab = Array(Array(Array(Signal((w_coeff, True), reset=10000) for _ in range(nr_channels))
                                   for _ in range(nr_profiles)) for _ in range(NR_COEFF))
        self.offset = offset = Array(Array(Signal((w_data, True))
                                           for _ in range(nr_channels)) for _ in range(nr_profiles))
        # registers for selected profile for channel
        self.ch_profile = ch_profile = Array(Signal(max=nr_profiles + 1)
                                             for _ in range(nr_channels))
        ###
        self.xy = xy = Array(Array(Array(Signal((w_data, True)) for _ in range(nr_channels))
                                   for _ in range(nr_profiles)) for _ in range(NR_COEFF))
        self.pp = pp = Signal(max=nr_profiles+1)  # position in profiles
        self.pc = pc = Signal(max=nr_channels+1)  # position in channels
        self.busy = busy = Signal()
        self.step = step = Signal(2)  # computation step
        self.submodules.dsp = dsp = Dsp()
        assert w_data <= len(dsp.b)
        assert w_coeff <= len(dsp.a)
        shift_c = len(dsp.p) - w_data - gainbits - 1
        shift_a = len(dsp.a) - w_coeff
        shift_b = len(dsp.b) - w_data
        c_rounding_offset = (1 << shift_c - 1) - 1

        self.sync += [
            # default to 0 and set to 1 further down if computation done in this cycle
            stb_out.eq(0),
            If(stb_in, busy.eq(1), [
               x0.eq(inp) for x0, inp in zip(xy[0][pp], inp)]),
            If(busy,
                step.eq(step+1),
                If(step == 1, dsp.mux_p.eq(0)),
                If(step == 2,
                    dsp.mux_p.eq(1),
                    step.eq(0),
                    pc.eq(pc + 1),
                    If(pc != 0,
                        xy[2][pp][pc-1].eq(dsp.p >> shift_c))),
               ),
            # if done with all channels and last data through dsp
            If((pc == nr_channels) & (step == 2),
               pc.eq(0),
               busy.eq(0),
               stb_out.eq(1),
               [x1.eq(x0) for x1, x0 in zip(xy[1][pp], xy[0][pp])]),
            dsp.a.eq(ab[step][pp][pc] << shift_a),
            dsp.b.eq(xy[step][pp][pc] << shift_b),
            dsp.c.eq(Cat(c_rounding_offset, 0, offset[pp][pc])),
        ]
        self.comb += [
            pp.eq(ch_profile[pc]),
            [outp.eq(y0) for outp, y0 in zip(outp, xy[2][pp])]
        ]
