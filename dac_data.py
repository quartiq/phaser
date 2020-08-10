from migen import *
from migen.genlib.io import DifferentialOutput
import itertools, operator


def parity(*x):
    return reduce(operator.xor, itertools.chain(*x))


# using PLL, internal OSTR generated at PFD freq
# SYNC resets PLL n-divider
# if N-div=1, SYNC irrelevant
# then use dual-source-sync: internal OSTR resets read side
# ISTR (SDR) resets write side
# clock DSP, data_clk from good GTP clock = dac_clk = ref_clk
# ping-pong CDC from fram_clk to data_clk
# synchronize frame marker to frame processing and to data_sync

class DacData(Module):
    def __init__(self, pins, swap=((0, 3), (1, 8))):
        self.data_sync = Signal()  # every 8 samples (4 sys cycles)
        self.blank = Signal()
        # A0:C0, B0:D0, A1:C1, B1:D1
        self.data = [[
            Signal(16, reset_less=True) for _ in range(2)
            ] for _ in range(4)]

        words = [[Signal.like(i) for i in j] for j in self.data]
        self.sync += Cat(words).eq(Cat(self.data))

        par = Signal(len(self.data), reset_less=True)
        self.sync += par.eq(Cat([parity(*word) for word in self.data]))

        # 1/4 cycle delayed clock to have the rising edge on the A/C sample
        # without tweaking delays
        self._oserdes([1, 0, 1, 0], pins.data_clk_p, pins.data_clk_n, "sys2q")
        # SYNC for PLL N divider, to dac_clk, not needed if N=1
        # for write pointer reset, to data_clk not needed
        # self._oserdes([self.data_sync]*4, pins.sync_p, pins.sync_n)
        # ISTR for write pointer
        self._oserdes([self.data_sync, 0, 0, 0],
                      pins.istr_parityab_p, pins.istr_parityab_n)
        # 32 bit parity
        self._oserdes(par, pins.paritycd_p, pins.paritycd_n)
        # external read pointer reset, to dac_clk*interpolation, not needed
        # self._oserdes([0, 0, 0, 0], pins.ostr_p, pins.ostr_n)

        # A0:C0, B0:D0, A1:C1, B1:D1
        for i, port in enumerate([
                (pins.data_a_p, pins.data_a_n),
                (pins.data_b_p, pins.data_b_n)]):
            for j, pin in enumerate(zip(*port)):
                bits = [words[k][i][j] for k in range(4)]
                if (i, j) in swap:  # sinara-hw/Phaser#102
                    bits = [~_ for _ in bits]
                    pin = pin[::-1]
                self._oserdes(bits, pin[0], pin[1])

    def _oserdes(self, data, pin_p, pin_n, clk="sys2"):
        pin = Signal()
        self.specials += [
            Instance("OSERDESE2",
                p_DATA_RATE_OQ="DDR", p_DATA_RATE_TQ="BUF",
                p_DATA_WIDTH=4, p_TRISTATE_WIDTH=1,
                p_INIT_OQ=0b00000000,
                i_RST=ResetSignal(),
                i_CLK=ClockSignal(clk),
                i_CLKDIV=ClockSignal(),
                # MSB is future, D1 is closest to Q
                i_D1=data[0], i_D2=data[1], i_D3=data[2], i_D4=data[3],
                i_TCE=1, i_OCE=1, i_T1=0,
                o_OQ=pin),
            DifferentialOutput(pin, pin_p, pin_n),
        ]
