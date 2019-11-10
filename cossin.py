import migen as mg
import numpy as np


class CosSinGen(mg.Module):
    """cos(z), sin(z) generator using a block ROM and linear interpolation

    For background information about an alternative way of computing
    trigonometric functions without multipliers and large ROM, see:

    P. K. Meher et al., "50 Years of CORDIC: Algorithms, Architectures, and
    Applications" in IEEE Transactions on Circuits and Systems I: Regular
    Papers, vol. 56, no. 9, pp. 1893-1907, Sept. 2009.
    doi: 10.1109/TCSI.2009.2025803
    https://eprints.soton.ac.uk/267873/1/tcas1_cordic_review.pdf

    For other implementations of trigonometric function generators, see

    https://www.xilinx.com/products/intellectual-property/dds_compiler.html#documentation
    https://www.intel.com/content/dam/altera-www/global/en_US/pdfs/literature/ug/ug_nco.pdf

    The implementation is as follows:

    1. Extract the 3 MSBs and save for later unmapping.
    2. Map the remaining LSBs into the first octant [0, pi/4]
       (conditional phase flip)
    3. Use the coarse `zl` MSBs of the first octant phase to look up
       cos(z), sin(z), cos'(z), sin'(z) in block ROM.
    4. Interpolate with the residual LSBs as cos(z + dz) = cos(z) + dz*cos'(z).
    5. Unmap the octant (cos sign flip, sin sign flip, cos/sin swap).

    The default values for the constructor parameters yield a 105 dBc
    SFDR generator (19 bit phase that uses one 9x36 bit block ROM (one
    RAMB18xx in read-only SDP mode on several Xilinx architectures),
    two 3x6 bit multipliers (fabric), and two 16 bit adders.

    The output is combinatorial and it helps to add another pipeline
    stage.

    Multiplication by a amplitude scaling factor (`a*cos(z)`)
    and generation of the phase input (e.g. a phase accumulator)
    is to be implemented elsewhere.
    """
    def __init__(self, z=18, x=15, zl=9, xd=3):
        self.latency = 2
        self.z = mg.Signal(z)  # input phase
        self.x = mg.Signal((x + 1, True), reset_less=True)  # output cos(z)
        self.y = mg.Signal((x + 1, True), reset_less=True)  # output sin(z)

        ###

        if zl is None:
            zl = z - 3
        assert zl >= 0
        # LUT phase values
        zls = (np.arange(1 << zl) + .5)/(1 << zl)*np.pi/4
        # LUT cos/sin
        init = [(int(_.real) | int(_.imag) << x)
                for _ in np.round(((1 << x) - 1)*np.exp(1j*zls))]
        mem_layout = [("x", x), ("y", x)]
        if xd:
            # derivative LUT, includes the 2pi/(1 << xd) scaling factor
            init = [i | (int(j.real) << 2*x) | (int(j.imag) << 2*x + xd)
                    for i, j in zip(
                        init, np.round(np.pi/4*(1 << xd)*np.exp(1j*zls)))]
            mem_layout.extend([("xd", xd), ("yd", xd)])
        lut = mg.Record(mem_layout, reset_less=True)
        assert len(init) == 1 << zl
        print("CosSin LUT {} bit deep, {} bit wide".format(zl, len(lut)))
        self.mem = mg.Memory(len(lut), 1 << zl, init=init)
        assert all(_ >= 0 for _ in self.mem.init)
        assert all(_ < (1 << len(lut)) for _ in self.mem.init)
        mem_port = self.mem.get_port()
        self.specials += self.mem, mem_port
        # 3 MSBs: octant
        # LSBs: phase, maped into first octant
        za = mg.Signal(z - 3)
        # LUT lookup
        xl, yl = lut.x, lut.y
        if xd:  # apply linear interpolation
            zk = z - 3 - zl
            zd = mg.Signal((zk, True), reset_less=True)
            self.comb += zd.eq(za[:zk] - (1 << zk - 1))
            zd = self.pipe(zd, 2)
            zq = z - 3 - x + xd
            assert zq > 0
            # add a rounding bias
            xl = xl - (((zd*lut.yd) + (1 << zq - 1)) >> zq)
            yl = yl + (((zd*lut.xd) + (1 << zq - 1)) >> zq)
        # unmap octant, pipe for BRAM adr and data registers
        zq = self.pipe(mg.Cat(self.z[-3] ^ self.z[-2],
                              self.z[-2] ^ self.z[-1], self.z[-1]), 2)
        # intermediate unmapping signals
        x1 = mg.Signal((x + 1, True))
        y1 = mg.Signal((x + 1, True))
        x2 = mg.Signal((x + 1, True))
        y2 = mg.Signal((x + 1, True))
        self.comb += [
            za.eq(mg.Mux(
                self.z[-3], (1 << z - 3) - 1 - self.z[:-3], self.z[:-3])),
            mem_port.adr.eq(za[-zl:]),
            # use BRAM output data register
            lut.raw_bits().eq(self.pipe(mem_port.dat_r, 1)),
            x1.eq(xl),
            y1.eq(yl),
            x2.eq(mg.Mux(zq[0], y1, x1)),
            y2.eq(mg.Mux(zq[0], x1, y1)),
            self.x.eq(mg.Mux(zq[1], -x2, x2)),
            self.y.eq(mg.Mux(zq[2], -y2, y2)),
        ]

    def pipe(self, x, n=0):
        """Create `n` pipeline register stages for signal x
        and return final stage"""
        k = mg.value_bits_sign(x)
        x, x0 = mg.Signal(k, reset_less=True), x
        self.comb += x.eq(x0)
        for i in range(n):
            x, x0 = mg.Signal(k, reset_less=True), x
            self.sync += x.eq(x0)
        return x

    def log(self, z, xy):
        """Run self for each value of `z` and record output values into `xy`"""
        if z is None:
            z = np.arange(1 << len(self.z))
        z = np.r_[z, (0,)*self.latency]
        for i, zi in enumerate(z):
            yield self.z.eq(int(zi))
            yield
            if i >= self.latency:
                x = yield self.x
                y = yield self.y
                xy.append((x, y))

    def xy_err(self, xy):
        """Given the `xy` output of all possible `z` values,
        calculate error, maximum quadrature error, rms magnitude error,
        and maximum magnitude error."""
        z = np.arange(1 << len(self.z)) + .5
        x, y = np.array(xy).T
        xy = x + 1j*y
        x_max = (1 << 9) - 1
        x_max = max(x)
        xye = xy - x_max*np.exp(2j*np.pi*z/len(z))
        xye2 = np.absolute(xye)
        assert xye.mean() < 1e-3
        return (xye, np.fabs(np.r_[xye.real, xye.imag]).max(),
                (xye2**2).mean()**.5, xye2.max())

    def verify(self):
        """Verify that the numerical model and the gateware
        implementation are equivalent."""
        co = CosSin(z=len(self.z), x=len(self.x) - 1,
                    zl=mg.log2_int(self.mem.depth),
                    xd=self.mem.width//2 - len(self.x) + 1)
        z = np.arange(1 << len(self.z))
        xy0 = np.array(co.xy(z))
        xy = []
        mg.Simulator(self, [self.log(z, xy)]).run()
        xy = np.array(xy).T
        np.testing.assert_allclose(xy, xy0)
        return xy
