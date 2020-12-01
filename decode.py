from collections import OrderedDict

from migen import *
from misoc.cores.duc import complex

from interpolate import SampleMux, InterpolateChannel


header_layout = [
    ("we", 1),
    ("addr", 7),
    ("data", 8),
    ("type", 4)
]

# straming gearbox
#
# 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
# ____----____----____----____----____----____----____----____----____----____----
# 66666666666666666666666666666665666666656666666566666665666666656666666566666660
#   4 2 0  4 2 0  4 2 0  4 2 0  4

class SampleGearbox(Module):
    """Variable width input uneven ratio gearbox (e.g. 5/6 to 7)

    `data_width <= sample_width`
    """
    def __init__(self, data_width, sample_width):
        self.data = Signal(data_width, reset_less=True)
        self.data_short = Signal()  # disregard data lsb
        self.data_stb = Signal()  # input data strobe
        self.clr = Signal()  # clear buffer level and disregard input data
        self.sample = Signal(sample_width, reset_less=True)
        self.sample_stb = Signal()  # output data strobe

        buf = Signal(data_width + sample_width - 1, reset_less=True)
        level = Signal(max=len(buf) + 1)
        incoming = Signal(max=data_width + 1)
        outgoing = Signal(max=sample_width + 1)
        full = Signal()
        self.comb += [
            If(self.data_stb,
                If(self.data_short,
                    incoming.eq(data_width - 1),
                ).Else(
                    incoming.eq(data_width),
                ),
            ).Else(
                incoming.eq(0),
            ),
            full.eq(level >= sample_width),
            If(full,
                outgoing.eq(sample_width),
            ).Else(
                outgoing.eq(0),
            ),
        ]
        self.sync += [
            If(self.data_stb,
                buf.eq(Mux(self.data_short,
                           Cat(self.data[1:], buf),
                           Cat(self.data, buf),
                )),
            ),
            self.sample_stb.eq(full),
            If(full,
                self.sample.eq(Case(level, {
                    sample_width + i: buf[i:] for i in range(data_width - 1)
                })),
            ),
            level.eq(level + incoming - outgoing),
            If(self.clr,
                level.eq(0),
            ),
        ]


bus_layout = [
    ("adr", 7),
    ("re", 1),
    ("dat_r", 8),
    ("we", 1),
    ("dat_w", 8),
]


class Register(Module):
    """Configuration/status register"""
    def __init__(self, width=None, read=True, write=True, readback=True):
        self.bus = Record(bus_layout)
        if width is None:
            width = len(self.bus.dat_w)
        assert width <= len(self.bus.dat_w)
        if write:
            self.write = Signal(width)
            self.sync += If(self.bus.we, self.write.eq(self.bus.dat_w))
        if read:
            self.read = Signal(width)
            self.comb += self.bus.dat_r.eq(self.read)
        if read and write and readback:
            self.comb += self.read.eq(self.write)


def intersection(a, b):
    (aa, am), (ba, bm) = a, b
    # TODO
    return False


class Bus(Module):
    def __init__(self):
        self.bus = Record(bus_layout)
        self._slaves = []

    def _check_intersection(self, adr, mask):
        for _, b_adr, b_mask in self._slaves:
            if intersection((b_adr, b_mask), (adr, mask)):
                raise ValueError("{} intersects {}".format(
                    (adr, mask), (b_adr, b_mask)))

    def connect(self, bus, adr, mask):
        adr &= mask
        self._check_intersection(adr, mask)
        self._slaves.append((bus, adr, mask))
        stb = Signal()
        self.comb += [
            stb.eq(self.bus.adr & mask == adr & mask),
            bus.adr.eq(self.bus.adr),
            bus.dat_w.eq(self.bus.dat_w),
            bus.we.eq(self.bus.we & stb),
            bus.re.eq(self.bus.re & stb),
            If(stb,
                self.bus.dat_r.eq(bus.dat_r)
            )
        ]


class Decode(Module):
    """Decode a frame into samples and metadata and drive
    a bus of registers from the metadata.
    """
    def __init__(self, b_sample, n_channel, n_mux, t_frame):
        n_samples = n_mux*n_channel*2
        header = Record(header_layout)
        body = Signal(n_samples*b_sample)
        self.frame = Signal(len(body) + len(header))
        self.stb = Signal()
        self.fft_stb = Signal()
        self.response = Signal(8)
        self.comb += [
            Cat(header.raw_bits(), body).eq(self.frame),
        ]

        self.submodules.zoh = SampleMux(
            b_sample=b_sample, n_channel=n_channel, n_mux=n_mux,
            t_frame=t_frame)
        self.comb += [
            self.zoh.body.eq(body),
            self.zoh.body_stb.eq(self.stb & (header.type == 1)),
            self.fft_stb.eq(self.stb & (header.type == 2)),
        ]

        self.interpolate = []
        self.data = [[Record(complex(16)) for _ in range(n_channel)]
                         for _ in range(2)]
        for ch in range(n_channel):
            for iq in "iq":
                inter = InterpolateChannel()
                self.submodules += inter
                self.interpolate.append(inter)
                self.comb += [
                    inter.input.data.eq(getattr(self.zoh.sample[ch], iq)),
                    inter.input.stb.eq(self.zoh.sample_stb),
                    getattr(self.data[0][ch], iq).eq(inter.output.data0),
                    getattr(self.data[1][ch], iq).eq(inter.output.data1),
                    inter.output.ack.eq(1),
                ]

        self.submodules.bus = Bus()
        self.comb += [
            self.bus.bus.dat_w.eq(header.data),
            self.bus.bus.adr.eq(header.addr),
            self.bus.bus.we.eq(self.stb & header.we),
            self.bus.bus.re.eq(self.stb & ~header.we),
            self.response.eq(self.bus.bus.dat_r),
        ]

    def map_registers(self, registers):
        self.mem_map = {}
        self.registers = {}
        addr = 0
        for name, *regs in registers:
            if isinstance(name, int):
                addr = name
                continue
            assert name not in self.registers
            self.registers[name] = regs
            for i, reg in enumerate(regs):
                self.bus.connect(reg.bus, addr, mask=0x7f)
                assert addr not in self.mem_map
                self.mem_map[addr] = (name, i)
                self.submodules += reg
                addr += 1

    def get(self, name, attr):
        regs = [getattr(reg, attr) for reg in self.registers[name]]
        if len(regs) == 1:
            return regs[0]
        else:
            return Cat(reversed(regs))  # big endian
