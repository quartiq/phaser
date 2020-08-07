from migen import *
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
        self.data_sync = Signal()  # every second sys cycle
        # 2 samples (01), 4 channels (ABCD)
        self.data = [[
            Signal((16, True), reset_less=True) for _ in range(2)
            ] for _ in range(4)]

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
        self._oserdes([
            parity(self.data[0][0], self.data[2][0]),  # A0:C0
            parity(self.data[1][0], self.data[3][0]),  # B0:D0
            parity(self.data[0][1], self.data[2][1]),  # A1:C1
            parity(self.data[1][1], self.data[3][1]),  # B1:D1
            ], pins.paritycd_p, pins.paritycd_n)
        # external read pointer reset, to dac_clk*interpolation, not needed
        # self._oserdes([0, 0, 0, 0], pins.ostr_p, pins.ostr_n)

        # A0:C0, B0:D0, A1:C1, B1:D1
        for i, port in enumerate([
                (pins.data_a_p, pins.data_a_n),
                (pins.data_b_p, pins.data_b_n)]):
            for j, pin in enumerate(zip(*port)):
                # (A0j, B0j, A1j, B1j) or (C0j, D0j, C1j, D1j)
                bits = [self.data[2*i][0][j], self.data[2*i + 1][0][j],
                        self.data[2*i][1][j], self.data[2*i + 1][1][j]]
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
                o_OQ=pin,
                i_RST=ResetSignal(),
                i_CLK=ClockSignal(clk),
                i_CLKDIV=ClockSignal(),
                i_D1=data[0], i_D2=data[1], i_D3=data[2], i_D4=data[3],
                i_D5=0, i_D6=0, i_D7=0, i_D8=0,
                i_TCE=1, i_OCE=1,
                i_T1=0, i_T2=0, i_T3=0, i_T4=0,
                i_SHIFTIN1=0, i_SHIFTIN2=0, i_TBYTEIN=0),
            Instance("OBUFDS", i_I=pin, o_O=pin_p, o_OB=pin_n),
        ]
