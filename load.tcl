open_hw_manager
connect_hw_server
open_hw_target
current_hw_device [lindex [get_hw_devices] 0]
set_property PROGRAM.FILE [lindex $argv 0] [current_hw_device]
program_hw_devices
close_hw_target
close_hw_manager
quit
