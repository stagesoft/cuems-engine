
from typing import Union

from .OssiaNodes import OssiaNodes
from .helpers import ClientDevices

OSC_CLIENT_PORT = 9090
OSC_REQ_PORT = 9091

class OssiaClient(OssiaNodes):
    def __init__(
        self,
        host: str = "127.0.0.1",
        client_port: int = OSC_CLIENT_PORT,
        server_port: int = OSC_REQ_PORT,
        remote_type: ClientDevices = ClientDevices.OSC,
        endpoints: Union[dict, list] = None
    ):
        super().__init__()
        self.host = host
        self.client_port = client_port
        self.server_port = server_port
        self.bind_device(remote_type)
        if endpoints:
            self.create_endpoints(endpoints)

    def bind_device(self, remote_type: ClientDevices):
        print(f"Using remote device: {remote_type.__annotations__}")
        self.device = remote_type(self)
