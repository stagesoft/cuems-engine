
from time import sleep
import sys
import inspect

from cuemsengine.osc.OssiaServer import OssiaServer
from cuemsengine.osc.RemoteOssia import RemoteOssia
from pyossia import ValueType
TEST_STR = 'goo'

"""Logging testing functions"""
def print_node(node):
    print(node)
    params = node.get_parameters()
    # print(str(params)) # Parameter objects addresses
    for param in params:
        print(f"Parameter info: [node: {param.node}, value: {param.value}, value_type: {param.value_type}]")

def iterate_on_devices(node):
    print_node(node)
    for child in node.children():
        print_node(child)
        if child.children():
            iterate_on_devices(child)
        else:
            print("No children")

def print_callback(node, value):
    print(
        f"Parameter changed at {node} to {value} [node value: {node.parameter.value}]"
    )

def print_test(x: str = TEST_STR):
    frame = sys._getframe(0)
    print(frame)
    print(frame.f_back)
    print(inspect.getmodule(frame))
    print(inspect.getmodule(frame.f_back))
    print(frame.f_code.co_name)
    print(f'name: {__name__}')
    print(f'func name: {print_test.__name__}')
    print(f'module: {print_test.__module__}')
    print(f'constant: {x}')

if __name__ == '__main__':

    test_endpoints = {
        # "/test1": [ValueType.Int, print_callback, 10],
        # "/test2": [ValueType.Int, print_callback, 20],
        "/test3": [ValueType.Int, print_callback, 30],
        "/test4": [ValueType.Int, print_callback, 40],
        # "/test/subcmd": [ValueType.Int, None, 330]
    }
    os = OssiaServer(log = True, endpoints = test_endpoints)
            
    iterate_on_devices(os.device.root_node)

    test_endpoints = {
        "/test1": [ValueType.Int, print_callback],
        "/test2": [ValueType.Int, print_callback, 10],
        "/test3": [ValueType.Int, print_callback, 20],
        "/test4": [ValueType.Int, print_callback, 30]
    }

    ro = RemoteOssia(
        endpoints = test_endpoints,
        # remote_type = RemoteDevices.OSCQUERY
    )

    iterate_on_devices(ro.device.root_node)

    print("Inner values")
    frame = sys._getframe(0)
    print(frame)
    print(frame.f_back)
    print(inspect.getmodule(frame))
    print(frame.f_code.co_name)

    print("Outer values")
    print_test()

    s = inspect.stack()
    print("Called values")
    print(f'name: {iterate_on_devices.__name__}')
    print(f'qualname: {iterate_on_devices.__qualname__}')
    print(f'module: {iterate_on_devices.__module__}')
    print(f'class: {iterate_on_devices.__class__}')
    print(f'global name: {__name__}')
    print(f'global file: {__file__}')
    print(f'global annotations: {__annotations__}')
    print(inspect.getmodule(iterate_on_devices))

    try:
        while True:
            # pass
            in_str = input('[?] Usage: <path>:<value>\n')
            if in_str:
                path, value = in_str.split(":")
                try:
                    print(f"[+] Path: {path}, Value: {int(value)}")
                    ro.set_value(path, int(value))
                except Exception as e:
                    print(f'[!] {e}')
                in_str = None
            else:
                sleep(0.01)
    except KeyboardInterrupt as e:
        print(": KeyboardInterrupt recieved")
        print("Server Ending...")
