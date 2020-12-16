# SingularitySurfer 2020


import numpy as np
from migen import *
from misoc.interconnect.stream import Endpoint
from misoc.cores.duc import *

from block_fft import Fft
from super_interpolator import SuperInterpolator
from operator import and_, add


class Fft_Loader(Module):
    """ fft coefficient loading logic

    In the first frame the fft_load reg is asserted, leading to the next frame writhing data into fft memory.
    The last fft coeff frame has to de-assert fft_load.

    """

    def __init__(self, decoder, fft, coef_per_frame):
        data = [Signal(fft[0].width_i * 2, reset_less=True)
                for _ in range(coef_per_frame)]
        b_adr = Signal(len(fft[0].x_in_adr))  # frame base adr, fft mem adr will incr. during frame data write
        dummy = Signal(fft[0].width_i * 2)  # empty dummy signal for shift reg

        datapos = Signal(int(np.ceil(np.log2(coef_per_frame + 1))))
        fft_id = Signal(4)

        for ff in fft:
            self.comb += [
                ff.x_in.eq(data[0]),
                ff.x_in_adr.eq(b_adr),
            ]
        self.comb += [
            fft_id.eq(decoder.zoh.body[16:20]),
        ]

        self.sync += [
            If(decoder.fft_stb,  # buffer addr and data if new frame in fft load mode
               [ff.x_in_we.eq(0) for ff in fft],
               Array([ff.x_in_we for ff in fft])[fft_id].eq(1),
               b_adr.eq(decoder.zoh.body[:16]),
               Cat(data).eq(decoder.zoh.body[fft[0].width_i * 2:fft[0].width_i * 2 * (1 + coef_per_frame)]),
               datapos.eq(0),
               ).Elif(datapos != (coef_per_frame - 1),
                      datapos.eq(datapos + 1),
                      Cat(data).eq(Cat(data[1:], dummy)),  # shift out data
                      b_adr.eq(b_adr + 1),
                      If(reduce(and_, b_adr), [ff.x_in_we.eq(0) for ff in fft])
                      # check if adr overflowed and de-assert write enable
                      ).Else(
                [ff.x_in_we.eq(0) for ff in fft],
            ),
        ]


class STFT_Branch(Module):
    """
    One stft branch with fft, I/Q interpolator and digital upconverter.
    """

    def __init__(self, nr, decoder, duc, width_d=16, size_fft=1024):

        self.submodules.fft = fft = Fft(n=size_fft, ifft=True, width_i=width_d, width_o=width_d, width_int=18,
                                        width_wram=18)

        self.submodules.inter_i = inter_i = SuperInterpolator(r_max=1024)
        self.submodules.inter_q = inter_q = SuperInterpolator(r_max=1024)

        cfg = decoder.get("stft_duc{}_cfg".format(nr), "write")
        self.sync += [
            # keep accu cleared
            duc.clr.eq(cfg[0]),
            If(decoder.registers["duc_stb"][0].bus.we,
               # clear accu once
               If(cfg[1],
                  duc.clr.eq(1),
                  ),
               duc.f.eq(decoder.get("stft_duc{}_f".format(nr), "write")),
               # msb align to 19 bit duc.p
               duc.p[3:].eq(
                   decoder.get("stft_duc{}_p".format(nr), "write")),
               ),
        ]

        pos = Signal(int(np.log2(size_fft)))  # position in fft mem
        p = Signal(16, reset=0)  # number repeats
        pdone = Signal(reset=1)  # pulse done signal

        self.comb += [
            inter_i.input.data.eq(fft.x_out[:width_d]),
            inter_q.input.data.eq(fft.x_out[width_d:]),
            fft.x_out_adr.eq(pos),
            fft.en.eq(1),
            duc.i[0].i.eq(self.inter_i.output.data0),
            duc.i[0].q.eq(self.inter_q.output.data0),
            duc.i[1].i.eq(self.inter_i.output.data1),
            duc.i[1].q.eq(self.inter_q.output.data1),
        ]

        self.sync += [
            # pulsegen settings
            inter_i.r.eq(decoder.get("interpolation_rate{}".format(nr), "read")),
            inter_q.r.eq(decoder.get("interpolation_rate{}".format(nr), "read")),
            fft.scaling.eq(decoder.get("fft{}_shiftmask".format(nr), "read")),
            If((decoder.get("pulse_settings", "read") & 0x01) == 0,  # continous fft outpout
               If(inter_i.input.ack,
                  pos.eq(pos + 1),
                  ),
               ),
               #.Elif(((decoder.get("pulse_settings", "read") & 0x01) == 1) & ~fft.busy,
               #        # standard pulse mode with p repeats
               #        If((decoder.get("pulse_trigger", "read") == 1) & (pdone == 1),
               #           p.eq(decoder.get("repeater", "read")),
               #           decoder.get("pulsegen_busy", "write").eq(1),
               #           decoder.get("pulse_trigger", "write").eq(0),  # de-assert trigger
               #           pdone.eq(0),
               #           pos.eq(0),
               #           ).Elif(pdone == 0,
               #                  If(inter_i.input.ack,
               #                     pos.eq(pos + 1),
               #                     ),
               #                  If(reduce(and_, pos),
               #                     p.eq(p - 1)),
               #                  If(p == 0,
               #                     pdone.eq(1),
               #                     pos.eq(0),
               #                     decoder.get("pulsegen_busy", "write").eq(0),
               #                     ),
               #                  ).Else(
               #            pdone.eq(1),
               #            pos.eq(0),
               #            decoder.get("pulsegen_busy", "write").eq(0),
               #        ),
               #        ),
            If(fft.start == 1, fft.start.eq(0), decoder.get("fft{}_start".format(nr), "write").eq(0)),
            If(decoder.get("fft{}_start".format(nr), "read") & (~fft.start), fft.start.eq(1)),
            decoder.get("fft_busy", "write").eq(fft.busy),
        ]


class Shaper(Module):
    """
    Overall pulse shaper. Consists of one fft, one (real) interpolator and one real x complex multiplier.
    """

    def __init__(self, decoder, width_d=16, size_fft=1024):
        self.submodules.fft = fft = Fft(n=size_fft, ifft=True, width_i=width_d, width_o=width_d, width_int=18,
                                        width_wram=18)

        self.submodules.inter = inter = SuperInterpolator(r_max=2048)

        pos = Signal(int(np.log2(size_fft)))  # position in fft mem
        p = Signal(16, reset=0)  # number repeats
        pdone = Signal(reset=1)  # pulse done signal
        cfg = decoder.get("duc{}_cfg".format(0), "write")

        self.comb += [
            inter.input.data.eq(fft.x_out[:width_d]),
            fft.x_out_adr.eq(pos),
            fft.en.eq(1),
        ]

        self.sync += [
            # pulsegen settings
            inter.r.eq(decoder.get("interpolation_rate_shaper", "read")),  # decoder.get("interpolation_rate", "read")),
            fft.scaling.eq(decoder.get("fft_shaper_shiftmask", "read")),
            If((decoder.get("pulse_settings", "read") & 0x01) == 0,  # continous fft outpout
               If(inter.input.ack,
                  pos.eq(pos + 1),
                  ),
               ).Elif(((decoder.get("pulse_settings", "read") & 0x01) == 1) & ~fft.busy,
                      # standard pulse mode with p repeats
                      If((decoder.get("pulse_trigger", "read") == 1) & (pdone == 1),
                         p.eq(decoder.get("repeater", "read")),
                         decoder.get("pulsegen_busy", "write").eq(1),
                         decoder.get("pulse_trigger", "write").eq(0),  # de-assert trigger
                         pdone.eq(0),
                         pos.eq(0),
                         ).Elif(pdone == 0,
                                If(inter.input.ack,
                                   pos.eq(pos + 1),
                                   ),
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
            If(fft.start == 1, fft.start.eq(0), decoder.get("fft_shaper_start", "write").eq(0)),
            If(decoder.get("fft_shaper_start", "read") & (~fft.start), fft.start.eq(1)),
            decoder.get("fft_busy", "write").eq(fft.busy),
        ]


class Pulsegen(Module):
    """ Pulsegen main module

    Parameters
    ----------
    width_d: data width
    size_fft: fft size
    """

    def __init__(self, decoder, duc=[], width_d=16, size_fft=1024, nr_branches=3):
        coef_per_frame = 13

        while(len(duc) < nr_branches):
            duc.append(PhasedDUC(n=2, pwidth=19, fwidth=32, zl=10))

        self.submodules.duc = duc

        self.submodules.branch = branch = [STFT_Branch(i, decoder, duc[i], width_d, size_fft) for i in range(nr_branches)]

        self.submodules.shaper = shaper = Shaper(decoder, width_d, size_fft)

        self.submodules.loader = Fft_Loader(decoder, [b.fft for b in branch] + [shaper.fft], coef_per_frame)

        self.submodules.mult = mult = [RealComplexMultiplier(width_d, width_d, width_d) for _ in range(2)]

        #  sum (supersampled)
        self.sum = sum = [[Record(complex(width_d), reset_less=True, name="sum") \
                           for _ in range(2)] for _ in range(len(branch) + 1)]
        self.output = [Record(complex(width_d), reset_less=True, name="output") for _ in range(2)]

        self.test = test = [Signal((width_d, True)) for _ in range(2)]
        self.cnt =Signal(27)

        # signal flow

        # add up all upconverted STFT branches
        # [(s.i.eq(reduce(add, [_.o[n].i for _ in duc])), (s.q.eq(reduce(add, [_.o[n].q for _ in duc]))))\
        #                                              for n, s in enumerate(sum)],
        # if len(branch) > 1:
        #     self.sync += [
        #         [(s.i.eq(duc[0].o[n].i + duc[1].o[n].i), s.q.eq(duc[0].o[n].q + duc[1].o[n].q)) \
        #          for n, s in enumerate(sum[0])],
        #     ]
        # else:
        #     self.sync += [
        #         [(s.i.eq(duc[0].o[n].i), s.q.eq(duc[0].o[n].q)) for n, s in enumerate(sum[0])],
        #     ]

        # if len(branch) > 0:
        self.sync += [
            [[(s.i.eq(sum[m - 1][n].i + duc[m - 1].o[n].i), (s.q.eq(sum[m - 1][n].q + duc[m - 1].o[n].q))) \
              for n, s in enumerate(k)] for m, k in enumerate(sum) if m >= 1],
            self.test[0].eq(duc[0].o[0].i + 0),
            self.test[1].eq(duc[0].o[1].i + 0),
            self.cnt.eq(self.cnt+1),
        ]

        self.sync += [
            # multiply with shaper output
            mult[0].b.eq(sum[-1][0]),
            mult[0].a.eq(shaper.inter.output.data0),
            mult[1].b.eq(sum[-1][1]),
            mult[1].a.eq(shaper.inter.output.data1),
            If((decoder.get("pulse_settings", "read") & 0x04) == 0x04,  # if shaper enabled
               [o.eq(m.p) for o, m in zip(self.output, mult)]
               ).Else(
                [o.eq(s) for o,s in zip(self.output, sum[-1])]
            )

        ]
