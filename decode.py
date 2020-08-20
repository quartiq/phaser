from collections import OrderedDict

from migen import *

from duc import complex


header_layout = [
    ("we", 1),
    ("addr", 7),
    ("data", 8),
    ("type", 4)
]


class SampleMux(Module):
    """Zero order hold interpolator.

    * `b_sample`: bits per sample (i or q)
    * `n_mux`: iq samples per channel in body
    * `n_channel`: iq dac channels
    * `n_mux`: sample repetitions (interpolation)
    * `t_frame`: clock cycles per frame
    """
    def __init__(self, b_sample, n_channel, n_mux, t_frame):
        self.body = Signal(b_sample*2*n_channel*n_mux)
        self.body_stb = Signal()
        self.sample = [Record(complex(b_sample)) for _ in range(n_channel)]
        self.sample_stb = Signal()
        self.sample_mark = Signal()
        samples = [Signal(n_channel*2*b_sample, reset_less=True) for _ in range(n_mux)]
        assert len(Cat(samples)) == len(self.body)
        i = Signal(max=n_mux, reset_less=True)
        assert t_frame % n_mux == 0
        j = Signal(max=t_frame//n_mux, reset_less=True)
        self.comb += [
            Cat([_.raw_bits() for _ in self.sample]).eq(Array(samples)[i]),
        ]
        self.sync += [
            self.sample_mark.eq(self.body_stb),
            j.eq(j + 1),
            self.sample_stb.eq(0),
            If(j == t_frame//n_mux - 1,
                j.eq(0),
                i.eq(i + 1),
                self.sample_stb.eq(1),
            ),
            If(self.body_stb,
                Cat(samples).eq(self.body),
                i.eq(0),
                j.eq(0),
                self.sample_stb.eq(1),
            )
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
            stb.eq(self.bus.adr & mask == adr),
            bus.adr.eq(self.bus.adr),
            bus.dat_w.eq(self.bus.dat_w),
            bus.we.eq(self.bus.we & stb),
            bus.re.eq(self.bus.re & stb),
            If(stb,
                self.bus.dat_r.eq(bus.dat_r)
            )
        ]


ext_layout = [
    ("cs", 1),
    ("sck", 1),
    ("sdo", 1),
    ("sdi", 1),
]


class Decode(Module):
    def __init__(self, b_sample, n_channel, n_mux, t_frame):
        n_samples = n_mux*n_channel*2
        header = Record(header_layout)
        body = Signal(n_samples*b_sample)
        self.frame = Signal(len(body) + len(header))
        self.stb = Signal()
        self.response = Signal(8, reset_less=True)
        self.comb += [
            Cat(header.raw_bits(), body).eq(self.frame),
        ]

        self.submodules.zoh = SampleMux(
            b_sample=b_sample, n_channel=n_channel, n_mux=n_mux,
            t_frame=t_frame)
        self.comb += [
            self.zoh.body.eq(body),
            self.zoh.body_stb.eq(self.stb),
        ]

        self.submodules.bus = Bus()
        self.comb += [
            self.bus.bus.dat_w.eq(header.data),
            self.bus.bus.adr.eq(header.addr),
            self.bus.bus.we.eq(header.we & self.stb),
            self.bus.bus.re.eq(~header.we & self.stb),
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
        regs = self.registers[name]
        if len(regs) == 1:
            return getattr(regs[0], attr)
        return Cat([getattr(reg, attr) for reg in regs])
