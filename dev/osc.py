
from time import sleep
import sys
import inspect

TEST_STR = 'goo'

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

    ro = OssiaClient(
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
