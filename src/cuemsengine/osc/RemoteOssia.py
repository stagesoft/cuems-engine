from enum import Enum
from pyossia.ossia_python import OSCDevice, OSCQueryDevice
from typing import Union

from .OssiaServer import OSC_CLIENT_PORT, OSC_REQ_PORT, OSCQUERY_REQ_PORT, OSCQUERY_WS_PORT
from .OssiaNodes import OssiaNodes

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
