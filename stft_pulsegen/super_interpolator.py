# SingularitySurfer 2020


import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint

from super_cic import SuperCicUS


class SuperInterpolator(Module):
    """Supersampled Interpolator.

    Variable rate, >89.5dB image rejection, supersampled (two outputs per cycle) interpolator.

    The core always computes two new output samples per clockcycle and ingests an input sample every r/2 cycles.
    Input and output use the misoc stream format, however the input STB signal is ignored and the core uses whatever
    data is presented at the input at the time it needs it. The input ACK is set when a sample is ingested in that cycle.

    The ratechange can be dynamically set to r=2 or multiples of 4 via the r input Signal. Other r inputs default to
    the next lower possible ratechange (eg. r=10 will lead to a ratechange of 8).

    To achieve the >89.5dB image rejection over all interpolation rates, 3 interpolation filters are used in series.
    Two halfband (HBF) FIR filters, each with a ratechange of 2 and one CIC FIR filter with a variable ratechange.
    For r=2 only the first HBF is used, for r=4 both HBFs are used in series and for r>4 both HBFs and the CIC with
    r_cic=r/4 are engaged.

    The HBFs use 18 bit filter coefficients that fit both lattice and xilinx dsp architectures. Rounding is
    implemented using "half a bit" bias at the filter input (which internally has a higher precision) and cutting
    off the lower bits at the end.

    Due to the HBF filter dynamics it is possible for the data to overflow if the input is a sharp step change. This
    will produce an unwanted out-of-band output signal but never lead to undefined behaviour. After changing the rate
    input, the interpolator will exhibit a transient phase for a short time. This may produce an unwanted out-of-band
    output signal if the input is nonzero but never lead to undefined behaviour.

    The interpolator transition band starts at 80% the input nyquist rate. Input frequencies higher than that will lead
    to aliases in the transition band. For r>4 the droop at the edge of the passband due to the CIC filter is at most
    -1dB. For r=2 and r=4 there is no droop in the passband. Passband ripple is negligible in all cases (<0.0004dB).

    freq. responses: https://github.com/quartiq/Phaser_STFT_Pulsegen/blob/master/Interpolation_Filters.ipynb


    Parameters
    ----------
    width_d: width of the data in- and output
    r_max: maximum rate change
    dsp_arch: lattice or xilinx dsp architecture
    """

    def __init__(self, width_d=16, r_max=4096, dsp_arch="xilinx"):
        l2r = int(np.ceil(np.log2(r_max)))
        assert dsp_arch in ("xilinx", "lattice"), "unsupported dsp architecture"
        assert r_max % 4 == 0,  "unsupported ratechange"

        ###
        self.input = Endpoint([("data", (width_d, True))])      # Data in
        self.output = Endpoint([("data0", (width_d, True)),     # Data out 0
                                ("data1", (width_d, True))])    # Data out 1
        self.r = Signal(l2r)                                    # Interpolation rate
        ###

        self.dsp_arch=dsp_arch

        self.hbfstop = Signal()  # hbf stop signal
        self.inp_stall = Signal()  # global input stall (stop) signal
        self.mode2 = Signal()  # dual hbf mode
        self.mode3 = Signal()
        hbf0_step1 = Signal()  # hbf0 step1 signal if in mode 2
        hbf1_step1 = Signal()
        muxsel0 = Signal()  # necessary bc big expressions in Mux condition dont work

        nr_dsps = 15
        width_coef = 18
        midpoint = (nr_dsps - 1) // 2
        bias = (1 << width_coef - 1) - 1

        #  HBF0 impulse response:
        h_0 = [9, 0, -32, 0, 83, 0, -183, 0,
               360, 0, -650, 0, 1103, 0, -1780, 0,
               2765, 0, -4184, 0, 6252, 0, -9411, 0,
               14803, 0, -26644, 0, 83046, 131072, 83046, 0,
               -26644, 0, 14803, 0, -9411, 0, 6252, 0,
               -4184, 0, 2765, 0, -1780, 0, 1103, 0,
               -650, 0, 360, 0, -183, 0, 83, 0,
               -32, 0, 9]
        #  HBF1 impulse response:
        h_1 = [69, 0, -418, 0, 1512, 0, -4175, 0,
               9925, 0, -23146, 0, 81772, 131072, 81772, 0,
               -23146, 0, 9925, 0, -4175, 0, 1512, 0,
               -418, 0, 69]
        coef_a = []
        for i, coef in enumerate(h_0[: (len(h_0) + 1) // 2: 2]):
            coef_a.append(Signal((width_coef, True), reset=coef))
        coef_b = []
        for i, coef in enumerate(h_1[: (len(h_1) + 1) // 2: 2]):
            coef_b.append(Signal((width_coef, True), reset=coef))

        x = [Signal((width_d, True)) for _ in range(((len(coef_a) * 2) + 2))]  # input hbf0
        x_end_l = Signal((width_d, True))
        x1_ = [Signal((width_d, True)) for _ in range(((len(coef_b) * 2) + 2))]  # input hbf1
        x1__ = Signal((width_d, True))  # intermediate signal

        if dsp_arch == "lattice":
            y = [Signal((36, True)) for _ in range(nr_dsps)]
            y_reg = [Signal((36, True)) for _ in range(((nr_dsps - 1) // 2) + 1)]
        else:  # xilinx dsp arch
            y = [Signal((48, True)) for _ in range(nr_dsps)]
            y_reg = [Signal((48, True)) for _ in range(((nr_dsps - 1) // 2) + 1)]

        # last stage: supersampled CIC interpolator
        self.submodules.cic = SuperCicUS(width_d=width_d, n=6, r_max=r_max//4, gaincompensated=True, width_lut=18)

        # input/output handling
        self.comb += [
            self.output.stb.eq(1),
            If(~self.mode3,
               self.input.ack.eq(Mux(self.mode2, hbf0_step1, 1)),
               self.output.data0.eq(y[-1][width_coef - 1:width_coef - 1 + width_d]),
               self.output.data1.eq(Mux(self.mode2, x1_[-1], x[-1])),
               ).Else(  # If CIC engaged
                   self.input.ack.eq(hbf0_step1 & ~self.hbfstop),
                   self.output.data0.eq(self.cic.output.data0),
                   self.output.data1.eq(self.cic.output.data1),
               )
        ]

        # Interpolator mode and dataflow handling
        self.comb += [
            self.mode2.eq(Mux(self.r >= 4, 1, 0)),
            self.mode3.eq(Mux(self.r >= 8, 1, 0)),
            muxsel0.eq((~self.cic.input.ack) | (self.mode3 & hbf1_step1)),
            self.hbfstop.eq(Mux(muxsel0, 1, 0)),
            self.cic.r.eq(self.r[2:]),  # r_cic = r_inter//4
            self.cic.input.data.eq(Mux(hbf1_step1, y[-1][width_coef - 1:width_coef - 1 + width_d], x1_[-1])),
            self.cic.input.stb.eq(self.mode3),
            x1__.eq(y[midpoint][width_coef - 1:width_coef - 1 + width_d]),
        ]
        self.sync += [
            If(~self.hbfstop,
               If(~self.mode2 | (self.mode2 & hbf0_step1),
                  Cat(x).eq(Cat(self.input.data, x)),
                  ),
               hbf0_step1.eq(~hbf0_step1),
               x_end_l.eq(x[-4]),  # last sample in inputchain (plus dsp reg delay) needs to be delayed by one clk more.

               # input to second hbf
               Cat(x1_).eq(Cat(Mux(hbf0_step1, x1__, x[-2]), x1_)),
               ),
            If(self.cic.input.ack, hbf1_step1.eq(~hbf1_step1))
        ]

        # Hardwired dual HBF upsampler DSP chain
        for i in range(nr_dsps):
            a, b, c, d, mux_p, p = self._dsp()

            if i <= ((nr_dsps - 1) // 2) - 1:  # if first HBF in mode 2
                self.comb += [
                    y[i].eq(p),
                    If(~self.mode2,
                       mux_p.eq(1),
                       a.eq(x[i * 2]),
                       d.eq(x[-3]),  # third to last bc one extra samples for midpoint output
                       b.eq(coef_a[i]),
                       ).Else(  # if in mode 2
                        If(~hbf0_step1,
                           mux_p.eq(1),
                           a.eq(x[i * 4]),
                           d.eq(x_end_l),
                           b.eq(coef_a[i * 2]),
                           ).Else(
                            mux_p.eq(0),
                            a.eq(x[(i * 4) + 1]),
                            d.eq(x_end_l),
                            b.eq(coef_a[(i * 2) + 1]),
                        )
                    )
                ]
                self.sync += [
                    If(~hbf0_step1 & ~self.hbfstop,
                       y_reg[i].eq(p)
                       )
                ]
                if i >= 1:
                    self.comb += [
                        c.eq(Mux(self.mode2, y_reg[i - 1], y[i - 1])),
                        #c.eq(y[i-1])
                    ]
                else:
                    self.comb += c.eq(bias)

            elif i == midpoint:
                self.comb += [
                    y[i].eq(p),
                    c.eq(Mux(self.mode2, y_reg[i - 1], y[i - 1])),
                    If(~self.mode2,
                       mux_p.eq(1),
                       a.eq(x[i * 2]),
                       d.eq(x[-3]),  # third to last bc one extra samples for midpoint output
                       b.eq(coef_a[i]),
                       ).Else(  # if in mode 2
                        If(~hbf0_step1,
                           mux_p.eq(1),
                           a.eq(x[i * 4]),
                           d.eq(x_end_l),
                           b.eq(coef_a[i * 2]),
                           ).Else(
                            mux_p.eq(0),
                            a.eq(x[(i * 4) + 1]),
                            d.eq(x_end_l),
                            b.eq(0),
                        )
                    )
                ]

            elif i == midpoint + 1:  # second half of dsp chain
                self.comb += [
                    y[i].eq(p),
                    If(~self.mode2,
                       mux_p.eq(1),
                       a.eq(x[i * 2]),
                       d.eq(x[-3]),  # third to last bc one extra samples for midpoint output
                       b.eq(coef_a[i]),
                       y[i].eq(p),
                       c.eq(y[i - 1])
                       ).Else(
                        mux_p.eq(1),
                        a.eq(x1_[(i - midpoint - 1) * 2]),
                        d.eq(x1_[-3]),  # third to last bc one extra samples for midpoint output
                        b.eq(coef_b[i - midpoint - 1]),
                        y[i].eq(p),
                        c.eq(bias)
                    )
                ]

            else:  # second half of dsp chain
                self.comb += [
                    y[i].eq(p),
                    If(~self.mode2,
                       mux_p.eq(1),
                       a.eq(x[i * 2]),
                       d.eq(x[-3]),  # third to last bc one extra samples for midpoint output
                       b.eq(coef_a[i]),
                       y[i].eq(p),
                       c.eq(y[i - 1])
                       ).Else(
                        mux_p.eq(1),
                        a.eq(x1_[(i - midpoint - 1) * 2]),
                        d.eq(x1_[-3]),  # third to last bc one extra samples for midpoint output
                        b.eq(coef_b[i - midpoint - 1]),
                        y[i].eq(p),
                        c.eq(y[i - 1])
                    )
                ]

    def _dsp(self):
        """Fully pipelined DSP block mockup."""

        if self.dsp_arch == "lattice":
            a = Signal((18, True))
            b = Signal((18, True))
            b_reg = Signal((18, True))
            c = Signal((36, True))
            d = Signal((18, True))
            mux_p = Signal()  # accumulator mux
            ad = Signal((18, True))
            m = Signal((36, True))
            p = Signal((36, True))
        else:  # xilinx dsp arch
            a = Signal((30, True))
            b = Signal((18, True))
            b_reg = Signal((18, True))
            c = Signal((48, True))
            d = Signal((25, True))
            mux_p = Signal()  # accumulator mux
            ad = Signal((25, True))
            m = Signal((48, True))
            p = Signal((48, True))

        self.sync += [
            If(~self.hbfstop,
               b_reg.eq(b),
               ad.eq(a + d),
               m.eq(ad * b_reg),
               If(~mux_p, p.eq(p + m)
                  ).Else(p.eq(m + c))
               )
        ]
        return a, b, c, d, mux_p, p
