
from typing import Union

from .OssiaNodes import OssiaNodes
from .helpers import ClientDevices

OSCCLIENT_LOCAL_PORT = 9009
OSCCLIENT_REMOTE_PORT = 9001

class OssiaClient(OssiaNodes):
    def __init__(
        self,
        host: str = "127.0.0.1",
        local_port: int = OSCCLIENT_LOCAL_PORT,
        remote_port: int = OSCCLIENT_REMOTE_PORT,
        remote_type: ClientDevices = ClientDevices.OSC,
        endpoints: Union[dict, list] = None
    ):
        super().__init__()
        self.host = host
        self.remote_port = remote_port
        self.local_port = local_port
        self.bind_device(remote_type)
        if endpoints:
            self.create_endpoints(endpoints)

    def bind_device(self, remote_type: ClientDevices):
        print(f"Using remote device: {remote_type.__annotations__}")
        self.device = remote_type(self)
