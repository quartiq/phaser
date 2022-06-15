#!/usr/bin/python3
# First order IIR filter for multiple channels and profiles with one DSP and no blockram.
# DSP block with MSB aligned inputs and "round half down" rounding.
# Can be used with Phasers decoder by passing this module. Without decoder pass `None`.
# 
#
# Note: Migen translates the "out of range" pc mux selector to the last vaid mux input.

# Todo: clipping
from migen import *
from migen.fhdl.verilog import convert as convert2verilog


NR_COEFF = 3  # [b0, b1, a0] number of coefficients for a first order iir


class Dsp(Module):
    def __init__(self):
        # xilinx dsp architecture (subset)
        self.a = a = Signal((25, True), reset_less=True)
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
    def __init__(self, decoder, w_coeff, w_data, gainbits, nr_profiles, nr_channels):
        # input strobe signal (start processing all channels)
        self.stb_in = stb_in = Signal()
        self.stb_out = stb_out = Signal()  # output strobe signal (all channels done)
        self.inp = inp = Array(Signal((w_data, True))
                               for _ in range(nr_channels))
        self.outp = outp = Array(Signal((w_data, True))
                                 for _ in range(nr_channels))
        # ab registers for all channels and profiles
        self.ab = ab = Array(Array(Array(Signal((w_coeff, True)) for _ in range(nr_channels))
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
        self.ch_profile_last = ch_profile_last = Signal(max=nr_profiles + 1)
        self.submodules.dsp = dsp = Dsp()
        assert w_data <= len(dsp.b)
        assert w_coeff <= len(dsp.a)
        shift_c = len(dsp.a) + len(dsp.b) - w_data - gainbits - 1
        shift_a = len(dsp.a) - w_coeff
        shift_b = len(dsp.b) - w_data
        c_rounding_offset = (1 << shift_c - 1) - 1

        if decoder != None:
            self.comb += [ab[k][j][i].eq(decoder.get(f"ch{i}_profile{j}_coeff{k}", "write")) for i in range(
                nr_channels) for j in range(nr_profiles) for k in range(NR_COEFF)]
            self.comb += [offset[j][i].eq(decoder.get(f"ch{i}_profile{j}_offset", "write")) for i in range(
                nr_channels) for j in range(nr_profiles)]
            self.sync += [
                If(stb_out,
                   ch_profile[0].eq(decoder.get(f"servo0_cfg", "write")>>1), # bit 0 is the ch enable bit
                   ch_profile[1].eq(decoder.get(f"servo1_cfg", "write")>>1))
            ]

        self.sync += [
            # default to 0 and set to 1 further down if computation done in this cycle
            stb_out.eq(0),
            If(stb_in, busy.eq(1), pp.eq(ch_profile[pc]), [[
               x0.eq(inp) for x0, inp in zip(xy[0][ch_profile[ch]], inp)] for ch in range(nr_channels)]),
            If(busy,
                step.eq(step+1),
                If(step == 1, dsp.mux_p.eq(0)),
                If(step == 2,
                    dsp.mux_p.eq(1),
                    step.eq(0),
                    pc.eq(pc + 1),
                    pp.eq(ch_profile[pc+1]),
                    If((pc != 0) & (pc != nr_channels+1),
                        xy[2][ch_profile_last][pc-1].eq(dsp.p >> shift_c))),
               ),
            # if done with all channels and last data through dsp
            If((pc == nr_channels) & (step == 2),
               pc.eq(0),
               pp.eq(ch_profile[0]),
               busy.eq(0),
               stb_out.eq(1),
               [[x1.eq(x0) for x1, x0 in zip(xy[1][ch_profile[ch]], xy[0][ch_profile[ch]])] for ch in range(nr_channels)]),
            dsp.a.eq(ab[step][pp][pc] << shift_a),
            dsp.b.eq(xy[step][pp][pc] << shift_b),
            dsp.c.eq(Cat(c_rounding_offset, 0, offset[pp][pc])),
        ]
        self.comb += [
            ch_profile_last.eq(ch_profile[pc-1]),
            outp[0].eq(xy[2][ch_profile[0]][0]),
            outp[1].eq(xy[2][ch_profile[1]][1]),
        ]
