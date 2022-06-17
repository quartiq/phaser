# SingularitySurfer 2020

import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint


class MAC_HBF_Upsampler(Module):
    """Multiply-accumulate half-band FIR interpolator.

    Always interpolates by a factor of 2. Uses a single, pipelined DSP block to do the FIR computation.
    Exploits even symmetry and trivial samples due to hbf architecture.
    Computation of a new output sample takes len(coeff + 1) / 4 cycles.
    The filter only checks that the output stream isn't stalled so no sample is lost downstream.
    The input strobe is ignored and the filter always uses the currently available data.
    Rounding is round half down.

    :param coeff: Filter coeffiecient list (full impulse response including center and zeros)
    :param width_d: Input/output data width
    :param width_coef: Coefficient width (fixed point position)
    :param dsp_arch: DSP block architecture (Xilinx/Lattice)
    """

    def __init__(self, coeff, width_d, width_coef, dsp_arch="xilinx"):

        assert dsp_arch in ("xilinx", "lattice"), "unsupported dsp architecture"
        self.dsp_arch = dsp_arch
        n = (len(coeff) + 1) // 4
        if len(coeff) != n * 4 - 1:
            raise ValueError("HBF length must be 4*n-1", coeff)
        elif n < 2:
            raise ValueError("Need order n >= 2")
        for i, c in enumerate(coeff):
            if i == n * 2 - 1:
                if not c:
                    raise ValueError("HBF center tap must not be zero")
            elif i & 1:
                if c:
                    raise ValueError("HBF even taps must be zero", (i, c))
            elif not c:
                raise ValueError("HBF needs odd taps", (i, c))
            elif c != coeff[-1 - i]:
                raise ValueError("HBF must be symmetric", (i, c))

        dsp_pipelen = 4
        bias = (1 << width_coef - 1) - 1
        coef = []
        for i, c in enumerate(coeff[: (len(coeff) + 1) // 2 : 2]):
            coef.append(Signal((width_coef + 1, True), reset_less=True, reset=c))

        self.input = Endpoint([("data", (width_d, True))])
        self.output = Endpoint([("data", (width_d, True))])

        x = [
            Signal((width_d, True), reset_less=True) for _ in range((len(coef) * 2))
        ]  # input hbf

        self.stop = Signal()  # filter output stall signal
        pos = Signal(int(np.ceil(np.log2(len(coef)))))
        pos_neg = Signal(len(pos) + 1)

        self.comb += [
            self.stop.eq(
                self.output.stb & ~self.output.ack
            )  # filter is sensitive to output and ignores input stb
        ]

        a, b, c, d, mux_p, p = self._dsp()

        self.comb += [
            pos_neg.eq(
                (len(coef) * 2) - 1 - pos
            ),  # position from end of input shift reg
            c.eq(bias),
            a.eq(Array(x)[pos]),
            d.eq(Array(x)[pos_neg]),
            b.eq(Array(coef)[pos]),
        ]

        self.sync += [
            If(
                ~self.stop,
                self.input.ack.eq(0),  # default no in ack
                self.output.stb.eq(0),  # default no out strobe
                mux_p.eq(0),  # default accumulate
                pos.eq(pos + 1),
                If(
                    pos == len(coef) - 1,  # new input sample
                    pos.eq(0),
                    Cat(x).eq(Cat(self.input.data, x)),  # shift in new sample
                    self.input.ack.eq(1),
                ),
                If(
                    pos == dsp_pipelen - 2,
                    mux_p.eq(1),
                ),
                If(
                    pos
                    == dsp_pipelen - 1,  # new output sample at the end of the dsp pipe
                    self.output.data.eq(p >> width_coef),
                    self.output.stb.eq(1),
                ),
                If(
                    pos
                    == (len(coef) // 2)
                    + dsp_pipelen
                    - 1,  # emit trivial sample at halfway computation + pipelen
                    self.output.data.eq(x[len(coef)]),
                    self.output.stb.eq(1),
                ),
            )
        ]

        if dsp_pipelen > (len(coef) // 2):  # if dsp pipe too long
            self.sync += [
                If(
                    pos == ((len(coef) // 2) + dsp_pipelen - 1) % (len(coef) // 2),
                    # emit trivial sample at halfway computation + pipelen
                    self.output.data.eq(x[len(coef) + 1]),
                    self.output.stb.eq(1),
                )
            ]

    def _dsp(self):
        """Fully pipelined DSP block mockup."""

        if self.dsp_arch == "lattice":
            a = Signal((18, True), reset_less=True)
            b = Signal((18, True), reset_less=True)
            c = Signal((36, True), reset_less=True)
            d = Signal((18, True), reset_less=True)
            ad = Signal((18, True), reset_less=True)
            m = Signal((36, True), reset_less=True)
            p = Signal((36, True), reset_less=True)
        else:  # xilinx dsp arch
            a = Signal((30, True), reset_less=True)
            b = Signal((18, True), reset_less=True)
            c = Signal((48, True), reset_less=True)
            d = Signal((25, True), reset_less=True)
            ad = Signal((25, True), reset_less=True)
            m = Signal((48, True), reset_less=True)
            p = Signal((48, True), reset_less=True)

        mux_p = Signal()  # accumulator mux
        a_reg = Signal.like(a)
        d_reg = Signal.like(d)
        b_reg = [Signal.like(b) for _ in range(2)]

        self.sync += [
            If(
                ~self.stop,
                a_reg.eq(a),
                Cat(b_reg).eq(Cat(b, b_reg)),
                d_reg.eq(d),
                ad.eq(a_reg + d_reg),
                m.eq(ad * b_reg[-1]),  # b is double piped to be in line with a+d
                If(~mux_p, p.eq(p + m)).Else(p.eq(m + c)),
            )
        ]
        return a, b, c, d, mux_p, p
