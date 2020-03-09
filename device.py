
import pyossia as ossia

local_device = ossia.LocalDevice("super software")
local_device.create_oscquery_server(3456, 5678, False)
foo_bar = local_device.add_node("/foo/bar/")


float_node = foo_bar
float_parameter = float_node.create_parameter(ossia.ValueType.Float)

float_parameter.value = 2.5

def iterate_on_children(node):

  for child in node.children():
    print(str(child))
    iterate_on_children(child)

# iterate on local device from the root
iterate_on_children(local_device.root_node)

while (True):
    wait
end
