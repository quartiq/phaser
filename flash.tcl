set bit [lindex $argv 0]
set pfx [file rootname $bit]
open_hw_manager
connect_hw_server
open_hw_target
current_hw_device [lindex [get_hw_devices] 0]
write_cfgmem -force -format MCS -size 8 -interface SPIx4 -loadbit [format "up 0x0 %s" $bit] $pfx
create_hw_cfgmem -hw_device [current_hw_device] [lindex [get_cfgmem_parts {s25fl128sxxxxxx0-spi-x1_x2_x4}] 0]
set_property PROGRAM.BLANK_CHECK 0 [current_hw_cfgmem]
set_property PROGRAM.ERASE 1 [current_hw_cfgmem]
set_property PROGRAM.CFG_PROGRAM 1 [current_hw_cfgmem]
set_property PROGRAM.VERIFY 1 [current_hw_cfgmem]
set_property PROGRAM.CHECKSUM 0 [current_hw_cfgmem]
set_property PROGRAM.ADDRESS_RANGE {use_file} [current_hw_cfgmem]
set_property PROGRAM.FILES [format "%s.mcs" $pfx] [current_hw_cfgmem]
set_property PROGRAM.UNUSED_PIN_TERMINATION {pull-none} [current_hw_cfgmem]
create_hw_bitstream -hw_device [current_hw_device] [get_property PROGRAM.HW_CFGMEM_BITFILE [current_hw_device]]
program_hw_devices
program_hw_cfgmem
boot_hw_device -verbose [current_hw_device]
close_hw_target
close_hw_manager
quit
