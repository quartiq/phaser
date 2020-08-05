from migen import *

from crg import CRG
from cossin import CosSinGen


class Test(Module):
    def __init__(self, platform):
        self.submodules += CRG(platform)

        i, o = [], []
        for _ in range(1 << 8):
            cs = CosSinGen()
            self.submodules += cs
            i.append(cs.z)
            o.extend([cs.x, cs.y])
        self.sync += [
            Cat(i).eq(Cat(platform.request("test_point"), Cat(i)))
        ]
        z = Signal(max(len(_) for _ in o), reset_less=True)
        for oi in o:
            z, z0 = Signal.like(z), z
            self.sync += [
                z.eq(z0 ^ oi)
            ]
        self.sync += platform.request("user_led").eq(z == 0)


if __name__ == "__main__":
    from phaser import Platform
    platform = Platform()
    if False:
        platform.toolchain.additional_commands.extend([
            "open_hw_manager",
            "create_hw_target -quiet -svf true migen_svf",
            "open_hw_target [get_hw_targets */migen_svf]",
            "create_hw_device -part xc7a100t",
            "current_hw_device [lindex [get_hw_devices] 0]",
            "set_property PROGRAM.FILE {{{build_name}.bit}} [current_hw_device]",
            "program_hw_devices [current_hw_device]",
            "write_hw_svf -force {build_name}.svf",
            "close_hw_target",
            "close_hw_manager"])
    else:
        platform.toolchain.additional_commands.extend([
            "open_hw_manager",
            "connect_hw_server",
            "open_hw_target",
            "current_hw_device [lindex [get_hw_devices] 0]",
            # "set_property PROGRAM.FILE {{{build_name}.bit}} [current_hw_device]",
            # "program_hw_devices",
            # "refresh_hw_device",
            "write_cfgmem -force -format MCS -size 8 -interface SPIx4 -loadbit \"up 0x0 {build_name}.bit\" {build_name}",
            "create_hw_cfgmem -hw_device [current_hw_device] [lindex [get_cfgmem_parts {{s25fl128sxxxxxx0-spi-x1_x2_x4}}] 0]",
            "set_property PROGRAM.BLANK_CHECK 0 [current_hw_cfgmem]",
            "set_property PROGRAM.ERASE 1 [current_hw_cfgmem]",
            "set_property PROGRAM.CFG_PROGRAM 1 [current_hw_cfgmem]",
            "set_property PROGRAM.VERIFY 1 [current_hw_cfgmem]",
            "set_property PROGRAM.CHECKSUM 0 [current_hw_cfgmem]",
            "set_property PROGRAM.ADDRESS_RANGE {{use_file}} [current_hw_cfgmem]",
            "set_property PROGRAM.FILES {{{build_name}.mcs}} [current_hw_cfgmem]",
            "set_property PROGRAM.UNUSED_PIN_TERMINATION {{pull-none}} [current_hw_cfgmem]",
            "create_hw_bitstream -hw_device [current_hw_device] [get_property PROGRAM.HW_CFGMEM_BITFILE [current_hw_device]]",
            "program_hw_devices",
            "program_hw_cfgmem",
            "boot_hw_device",
            "close_hw_target",
            "close_hw_manager"])
    test = Test(platform)
    platform.build(test)
