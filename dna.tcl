# Execute this as:
#  vivado -mode batch -source dna.tcl
open_hw_manager
connect_hw_server
open_hw_target
current_hw_device [lindex [get_hw_devices] 0]
set DNA [get_property REGISTER.EFUSE.FUSE_DNA [current_hw_device]]
puts "### DNA ###: $DNA"
close_hw_target
close_hw_manager
quit
