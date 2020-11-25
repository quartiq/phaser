from migen import *


class Checker(Module):
    """Check CRC and assemble a frame"""
    def __init__(self, n_data, t_clk, n_frame):
        n_word = n_data * t_clk
        n_marker = n_frame // 2 + 1
        n_crc = n_data
        self.frame = Signal(n_word * n_frame - n_marker - n_crc)
        self.frame_stb = Signal()
        self.response = Signal(n_frame*t_clk, reset_less=True)


class Link(Module):
    """Kasli-Phaser link implementation

    * Like the Fastino link but with 8 bits per clock cycle
    * 1 clock lane, 6 phaser input data lanes, 1 phaser output data lane
    """
    def __init__(self):
        self.submodules.checker = Checker(n_data=6, n_frame=10, t_clk=8)

