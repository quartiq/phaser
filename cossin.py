import migen as mg
import numpy as np
import logging


logger = logging.getLogger(__name__)


def minimax_linear_approximation(ab, f, f1i):
    """Minimax linear approximation

    returns 1st order polynomial coefficients m, n
    for linear minimax approximation mx + n of function f
    between consecutive points in ab. The inverse of the
    derivative of f is provided as f1i.
    """
    fab = f(ab)
    a, b = ab[:-1], ab[1:]
    fa, fb = fab[:-1], fab[1:]
    m = (fa - fb)/(a - b)
    c = f1i(m)
    fc = f(c)
    n = (fa + fc - m*(a + c))/2
    e = m*a + n - fa
    np.testing.assert_allclose(m*b + n - fb, e)
    np.testing.assert_allclose(m*c + n - fc, -e)
    #x = np.linspace(a, b, 100)
    #np.testing.assert_array_less(np.absolute(m*x + n - f(x)), np.ones_like(x)*1.00001*e)
    return m, n


class CosSinGen(mg.Module):
    """cos(z), sin(z) generator using a block ROM and linear interpolation

    For background information about an alternative way of computing
    trigonometric functions without multipliers and large ROM, see:

    P. K. Meher et al., "50 Years of CORDIC: Algorithms, Architectures, and Applications"
    in IEEE Transactions on Circuits and Systems I: Regular Papers, vol. 56, no. 9,
    pp. 1893-1907, Sept. 2009. doi: 10.1109/TCSI.2009.2025803
    https://eprints.soton.ac.uk/267873/1/tcas1_cordic_review.pdf

    For other implementations of trigonometric function generators, see

    https://www.xilinx.com/products/intellectual-property/dds_compiler.html#documentation
    https://www.intel.com/content/dam/altera-www/global/en_US/pdfs/literature/ug/ug_nco.pdf

    The implementation is as follows:

    1. Extract the 3 MSBs and save for later unmapping.
    2. Map the remaining LSBs into the first octant [0, pi/4[
       (conditional phase flip)
    3. Use the coarse `zl` MSBs of the first octant phase to look up
       cos(z), sin(z), cos'(z), sin'(z) in block ROM.
    4. Interpolate with the residual LSBs as cos(z + dz) = cos(z) + dz*cos'(z).
    5. Unmap the octant (cos sign flip, sin sign flip, cos/sin swap).

    The default values for the constructor parameters yield a 100 dBc
    SFDR cons/sin generator with 18 bit phase and 16 bit outputs using
    one 9x36 bit block ROM (one RAMB18xx in read-only SDP mode on several
    Xilinx architectures), and 4x6 and 3x6 bit fabric multipliers for the
    interpolation. It runs at > 250 MHz on an A7-2.

    Dithering the input phase improves the SFDR further.

    The output is combinatorial and it helps to add another pipeline
    stage.

    Multiplication by a amplitude scaling factor (`a*cos(z)`)
    and generation of the phase input (e.g. a phase accumulator)
    is to be implemented elsewhere.
    """
    def __init__(self, z=18, x=15, zl=9, xd=4):
        self.latency = 0  # computed later
        self.z = mg.Signal(z)  # input phase
        self.x = mg.Signal((x + 1, True), reset_less=True)  # output cos(z)
        self.y = mg.Signal((x + 1, True), reset_less=True)  # output sin(z)

        ###

        x_max = (1 << x) - 1

        # LUT depth
        if zl is None:
            zl = z - 3
        assert zl >= 0

        # generate the cos/sin LUT
        ab = np.pi/4/(1 << zl)*np.arange((1 << zl) + 1)
        if xd:
            cm, cn = minimax_linear_approximation(ab, np.cos, lambda x: np.arcsin(-x))
            sm, sn = minimax_linear_approximation(ab, np.sin, lambda x: np.arccos(x))
            csd = cm + 1j*sm
            cs = cn + 1j*sn + csd*(ab[:-1] + ab[1:])/2
            csd = np.round((1 << xd)*np.pi/4/1j*csd)
        else:
            cs = np.exp(1j*ab)
            cs = (cs[1:] + cs[:-1])/2
            csd = np.zeros_like(cs)
        cs = np.round(x_max*cs)

        lut_init = []
        for csi, csdi in zip(cs, csd):
            # save a bit by noticing that cos(z) > 1/2 for 0 < z < pi/4
            xy = csi - (1 << x - 1)
            xi, yi = int(xy.real), int(xy.imag)
            assert 0 <= xi < 1 << x - 1
            assert 0 <= yi < 1 << x
            lut_init.append(xi | (yi << x - 1))
            if xd:
                # derivative LUT
                # includes the 2pi/(1 << xd) = pi/4 scaling factor
                # save a bit by noticing that cos(z) > 1/2 for 0 < z < pi/4
                xyd = csdi - (1 << xd - 1)
                xid, yid = int(xyd.real), int(xyd.imag)
                assert 0 <= xid < 1 << xd - 1
                assert 0 <= yid < 1 << xd
                lut_init[-1] |= (xid << 2*x - 1) | (yid << 2*x + xd - 2)
        assert len(lut_init) == 1 << zl

        # LUT ROM
        mem_layout = [("x", x - 1), ("y", x)]
        if xd:
            mem_layout.extend([("xd", xd - 1), ("yd", xd)])
        lut_data = mg.Record(mem_layout, reset_less=True)
        assert all(0 <= _ < 1 << len(lut_data) for _ in lut_init)
        logger.info("CosSin LUT {} bit deep, {} bit wide".format(zl, len(lut_data)))
        self.lut = mg.Memory(len(lut_data), 1 << zl, init=lut_init)
        lut_port = self.lut.get_port()
        self.specials += self.lut, lut_port
        self.sync += [
            # use BRAM output data register
            lut_data.raw_bits().eq(lut_port.dat_r),
        ]
        self.latency += 1  # mem dat_r output register

        # compute LUT address
        # 3 MSBs: octant
        # LSBs: phase, maped into first octant
        za = mg.Signal(z - 3)
        self.comb += [
            za.eq(mg.Mux(
                self.z[-3], (1 << z - 3) - 1 - self.z[:-3], self.z[:-3])),
            lut_port.adr.eq(za[-zl:]),
        ]
        self.latency += 1  # mem address register

        xl = lut_data.x | (1 << x - 1)
        yl = lut_data.y
        if xd:  # apply linear interpolation
            zk = z - 3 - zl
            zd = mg.Signal((zk + 1, True), reset_less=True)
            self.comb += zd.eq(za[:zk] - (1 << zk - 1) + self.z[-3])
            zd = self.pipe(zd, self.latency)
            # add a rounding bias
            zq = z - 3 - x + xd
            assert zq > 0
            qb = (1 << zq - 1) - 1
            lxd = mg.Signal((xd + zk - zq, True), reset_less=True)
            lyd = mg.Signal((xd + zk - zq, True), reset_less=True)
            self.sync += [
                lxd.eq((zd*(lut_data.xd | (1 << xd - 1)) + qb) >> zq),
                lyd.eq((zd*lut_data.yd + qb) >> zq),
            ]
            xl = self.pipe(xl, 1) - lyd
            yl = self.pipe(yl, 1) + lxd
            self.latency += 1
        x1 = self.pipe(xl, 0)
        y1 = self.pipe(yl, 0)

        # unmap octant
        zq = self.pipe(mg.Cat(self.z[-3] ^ self.z[-2],
                              self.z[-2] ^ self.z[-1], self.z[-1]), self.latency)
        # intermediate unmapping signals
        x2 = mg.Signal((x + 1, True))
        y2 = mg.Signal((x + 1, True))
        self.comb += [
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
        z = np.arange(1 << len(self.z))
        x, y = np.array(xy).T
        xy = x + 1j*y
        pxy = np.fft.fft(xy)
        assert np.argmax(np.absolute(pxy)) == 1
        pxy[1] = 0.
        xye = np.fft.ifft(pxy)
        xye2 = np.absolute(xye)
        assert xye.mean() < 1e-3
        return (xye, np.fabs(np.r_[xye.real, xye.imag]).max(),
                (xye2**2).mean()**.5, xye2.max())

    def verify(self):
        """Verify that the numerical model and the gateware
        implementation are equivalent."""
        co = CosSin(z=len(self.z), x=len(self.x) - 1,
                    zl=mg.log2_int(self.lut.depth),
                    xd=self.lut.width//2 - len(self.x) + 2)
        z = np.arange(1 << len(self.z))
        xy0 = np.array(co.xy(z))
        xy = []
        mg.Simulator(self, [self.log(z, xy)]).run()
        xy = np.array(xy).T
        np.testing.assert_allclose(xy, xy0)
        return xy
