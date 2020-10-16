import unittest

from phaser import Phaser
from migen.build.platforms.sinara.phaser import Platform


class TestVerilog(unittest.TestCase):
    def test_verilog(self):
        platform = Platform()
        dut = Phaser(platform)
        platform.get_verilog(dut, name="phaser")
