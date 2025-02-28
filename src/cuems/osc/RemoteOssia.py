from enum import Enum
from pyossia.ossia_python import OSCDevice, OSCQueryDevice, ValueType
from time import sleep
from typing import Union

from OssiaServer import OSC_CLIENT_PORT, OSC_REQ_PORT, OSCQUERY_REQ_PORT, OSCQUERY_WS_PORT
from OSCNodes import OSCNodes

def new_osc_device(cls) -> OSCDevice:
    x = OSCDevice(
        "cuems",
        cls.host,
        OSC_REQ_PORT,
        OSC_CLIENT_PORT
    )
    return x

def new_oscquery_device(cls) -> OSCQueryDevice:
    x = OSCQueryDevice(
        "cuems",
        f"ws://{cls.host}:{OSCQUERY_WS_PORT}",
        OSCQUERY_REQ_PORT
    )
    x.update()
    return x

class RemoteDevices(Enum):
    OSC = new_osc_device
    OSCQUERY = new_oscquery_device
    DISPATCHER = None

class RemoteOssia(OSCNodes):
    def __init__(
        self,
        host: str = "127.0.0.1",
        remote_type: RemoteDevices = RemoteDevices.OSC,
        endpoints: Union[dict, list] = None
    ):
        super().__init__()
        self.host = host
        print(f"Using remote device: {remote_type.__annotations__}")
        self.bind_device(remote_type)
        if endpoints:
            self.create_endpoints(endpoints)

    def bind_device(self, remote_type: RemoteDevices):
        self.device = remote_type(self)

if __name__ == "__main__":
    
    from OssiaServer import iterate_on_devices, print_callback

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

    import inspect
    from OssiaServer import print_test
    import sys
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
        print("Remote Ending...")
