from migen import *


def stream(width):
    return Record([
        ("data", width, DIR_M_TO_S),
        ("stb", 1, DIR_M_TO_S),
        ("ack", 1, DIR_M_TO_S),
    ])


def source(stream, i):
    for ti, ii in i:
        assert ti > 0
        for _ in range(ti - 1):
            yield
        yield stream.data.eq(ii)
        yield stream.stb.eq(1)
        yield
        while not (yield stream.ack):
            #print(ti, "dly")
            yield
        yield stream.stb.eq(0)


#@passive
def sink(stream, o, max):
    yield stream.ack.eq(1)
    t = 0

    while True:
        while not (yield stream.stb):
            t += 1
            yield
        d = yield stream.data
        o.append((t, d))
        if len(o) == max:
            break
        t = 1
        yield
    yield stream.ack.eq(0)


class Upsampler(Module):
    def __init__(self, r, width):
        self.i = stream(width)
        self.o = stream(width)
        self.r = Signal(max=r, reset=r - 1)

        i = Signal(max=r)
        i_done = Signal()
        self.comb += [
            i_done.eq(i == 0),
            self.i.ack.eq(i_done & self.o.ack),
            If(i_done,
                self.o.data.eq(self.i.data),
            ),
            self.o.stb.eq(~i_done | self.i.stb),
        ]
        self.sync += [
            If(self.o.ack & self.o.stb & ~i_done,
                i.eq(i - 1)
            ),
            If(self.i.ack & self.i.stb,
                i.eq(self.r)
            ),
        ]


class Downsampler(Module):
    def __init__(self, r, width):
        self.i = stream(width)
        self.o = stream(width)
        self.r = Signal(max=r, reset=r - 1)

        i = Signal(max=r)
        i_done = Signal()
        self.comb += [
            i_done.eq(i == 0),
            self.i.ack.eq(~i_done | self.o.ack),
            self.o.data.eq(self.i.data),
            self.o.stb.eq(i_done & self.i.stb),
        ]
        self.sync += [
            If(self.i.ack & self.i.stb & ~i_done,
                i.eq(i - 1)
            ),
            If(self.o.ack & self.o.stb,
                i.eq(self.r)
            ),
        ]


class Register(Module):
    def __init__(self, width):
        self.i = stream(width)
        self.o = stream(width)
        self.o.data.reset_less = True

        self.comb += [
            self.i.ack.eq(~self.o.stb | self.o.ack),
        ]
        self.sync += [
            If(self.o.ack,
                self.o.stb.eq(0),
            ),
            If(self.i.ack & self.i.stb,
                self.o.data.eq(self.i.data),
                self.o.stb.eq(1)
            )
        ]


class CIC(Module):
    def __init__(self, r, m, n, width):
        if isinstance(width, tuple):
            width = width[0]
        self.gain = (r*m)**n/r
        self.rate = Signal(max=abs(r), reset=abs(r) - 1)

        g = -(1 << width - 1)
        w = lambda g: (bits_for(ceil(g)), True)
        self.i = stream(w(g))
        self.o = stream(w(g*self.gain))

        self.i_stall = Signal()
        self.o_drop = Signal()

        self.comb += [
            self.i_stall.eq(~self.i.ack & self.i.stb)
        ]

        x, en = self.i.data, self.i.stb
        if r > 0:
            i = Signal(max=r)
            self.comb += [
                self.i.ack.eq(i == 0),
            ]
            self.sync += [
                If(~self.i.ack,
                    i.eq(i - 1),
                ),
                If(self.i.stb,
                   i.eq(self.rate - 1),
                ),
            ]
            if False:
                for i in range(n):
                    g *= 2
                    x, en = self.make_comb(x, en, w(g), m)
            else:
                g *= 2**n
                x, en = self.make_itercomb(x, en, w(g), n, m)
            self.submodules.r = Upsampler(abs(r), w(g))
            g *= 1/r
            self.comb += [
                self.r.r.eq(self.rate),
                self.r.i.data.eq(x),
                self.r.i.stb.eq(en),
                self.r.o.ack.eq(1),
            ]
            x, en = self.r.o.data, self.r.o.stb
            for i in range(n):
                g *= r*m/2
                x, en = self.make_integrator(x, en, w(g))
        else:
            self.comb += self.i.ack.eq(1)
            g *= (r*m)**n
            for i in range(n):
                x, en = self.make_integrator(x, en, w(g))
            self.submodules.r = Downsampler(abs(r), w(g))
            self.comb += [
                self.r.r.eq(self.rate),
                self.r.i.data.eq(x),
                self.r.i.stb.eq(en),
                self.r.o.ack.eq(1),
            ]
            x, en = self.r.o.data, self.r.o.stb
            for i in range(n):
                x, en = self.make_comb(x, en, w(g), m)
        self.o.data.reset_less = True
        self.sync += [
            self.o.data.eq(x),
            self.o.stb.eq(en),
            self.o_drop.eq(self.o.stb & ~self.o.ack & en),
        ]

    def make_comb(self, i, en, width, m=1):
        i0 = i
        for _ in range(m):
            i1, i0 = i0, Signal.like(i0)
            self.sync += [
                If(en,
                    i0.eq(i1),
                )
            ]
        comb = Signal(width, reset_less=True)
        comb_en = Signal()
        self.sync += [
            comb.eq(i - i0),
            comb_en.eq(en),
        ]
        return comb, comb_en

    def make_itercomb(self, i, en, width, n, m=1):
        if m != 1:
            raise NotImplemented()
        mem = Memory(width=width[0], depth=bits_for(n))
        memp = mem.get_port(write_capable=True, mode=READ_FIRST)
        self.specials += mem, memp
        j = Signal(max=n)
        i0 = Signal(width, reset_less=True)
        comb0 = Signal(width)
        comb = Signal(width, reset_less=True)
        done = Signal()
        self.comb += done.eq(j == n - 1)
        self.sync += [
            If(~done,
               j.eq(j - 1)
            ),
            If(en,
               j.eq(n - 1)
            ),
            i0.eq(memp.dat_w)
        ]
        self.comb += [
            comb0.eq(i0 - memp.dat_r),
            memp.dat_w.eq(Mux(en, i, comb)),
        ]
        return comb, comb_en

    def make_integrator(self, i, en, width):
        integrator = Signal(width)
        integrator_en = Signal()
        self.sync += [
            If(en,
                integrator.eq(integrator + i),
            ),
            integrator_en.eq(en),
        ]
        return integrator, integrator_en
