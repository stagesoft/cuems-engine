import pyossia as ossia
import time

local_device = ossia.LocalDevice(f'node_127.0.0.1_oscquery')
local_device.create_oscquery_server( 1234, 6666, True)
foo_bar_node = local_device.add_node("/foo/bar/")
float_parameter = foo_bar_node.create_parameter(ossia.ValueType.Float)
float_parameter.access_mode = ossia.AccessMode.Bi
float_parameter.value = 1
while True:
    time.sleep(2)
    float_parameter.value += 1
input("press any key to exit")