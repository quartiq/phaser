import unittest

from phaser import Phaser
from phaser_platform import Platform


class TestVerilog(unittest.TestCase):
    def test_verilog(self):
        platform = Platform(load=False)
        dut = Phaser(platform)
        platform.get_verilog(dut, name="phaser")
