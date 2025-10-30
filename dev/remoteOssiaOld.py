from enum import Enum
from pyossia.ossia_python import OSCDevice, OSCQueryDevice, ValueType
from time import sleep
from typing import Union

from OssiaNodes import OssiaNodes

OSC_CLIENT_PORT = 9989
OSC_REQ_PORT = 9091
OSCQUERY_REQ_PORT = 40250
OSCQUERY_WS_PORT = 40255

def new_osc_device(cls) -> OSCDevice:
    x = OSCDevice(
        "cuems",
        # f"ws://{cls.host}:{OSCQUERY_WS_PORT}",
        "127.0.0.1",
        OSC_REQ_PORT,
        OSC_CLIENT_PORT
    )
    return x

def new_oscquery_device(cls) -> OSCQueryDevice:
    x = OSCQueryDevice(
        "cuems", cls.url, OSCQUERY_REQ_PORT
    )
    x.update()
    return x

class RemoteDevices(Enum):
    OSC = new_osc_device
    OSCQUERY = new_oscquery_device
    DISPATCHER = None

class RemoteOssia(OssiaNodes):
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
    
    from dev.ossiaServerOld import iterate_on_devices, print_callback

    test_endpoints = {
        "/test1": [ValueType.Int, print_callback],
        "/test2": [ValueType.Int, print_callback]
    }
    
    ro = RemoteOssia(
        endpoints = test_endpoints
    )
    
    iterate_on_devices(ro.device.root_node)

    try:
        while True:
            pass
    except KeyboardInterrupt as e:
        print(": KeyboardInterrupt recieved")
        print("Remote Ending...")
