from migen import *

from crg import CRG
from cossin import CosSinGen


class DacData(Module):
    def __init__(self, pins, swap=[(0, 3), (1, 8)]):
        self.data_sync = Signal()
        self.data = [
            [Signal(16, reset_less=True) for i in range(2)]  # 2 samples
                for i in range(4)]  # 4 DAC channels

        self._oserdes([1, 0, 1, 0], pins.data_clk_p, pins.data_clk_n, "sys2q")
        self._oserdes([self.data_sync]*4, pins.sync_p, pins.sync_n)
        self._oserdes([self.data_sync, 0, 0, 0],
                      pins.istr_parityab_p, pins.istr_parityab_n)
        self._oserdes([0, 0, 0, 0], pins.paritycd_p, pins.paritycd_n)

        for i, (data, port) in enumerate([
                (self.data[:2], (pins.data_a_p, pins.data_a_n)),
                (self.data[2:], (pins.data_b_p, pins.data_b_n))]):
            for j, pin in enumerate(zip(*port)):
                bits = [data[0][0][j], data[1][0][j],
                        data[0][1][j], data[1][1][j]]
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
                i_TCE=1, i_OCE=1, i_T1=0),
            Instance("OBUFDS", i_I=pin, o_O=pin_p, o_OB=pin_n),
        ]



class Test(Module):
    def __init__(self, platform):
        self.submodules.crg = CRG(platform)
        self.submodules.data = DacData(platform.request("dac_data"))
        self.sync += Cat(self.data.data).eq(
            Cat(platform.request("test_point"), Cat(self.data.data)))


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform(load=True)
    test = Test(platform)
    platform.build(test)
