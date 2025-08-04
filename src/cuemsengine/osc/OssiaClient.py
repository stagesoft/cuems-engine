from time import sleep
from typing import Union

from .OssiaNodes import OssiaNodes, STARTUP_DELAY
from .helpers import ClientDevices, ClientSetupFunction

OSCCLIENT_LOCAL_PORT = 9009
OSCCLIENT_REMOTE_PORT = 9001

class OssiaClient(OssiaNodes):
    def __init__(
        self,
        host: str = "127.0.0.1",
        local_port: int = OSCCLIENT_LOCAL_PORT,
        remote_port: int = OSCCLIENT_REMOTE_PORT,
        remote_type: ClientSetupFunction = ClientDevices.OSC,
        endpoints: Union[dict, list] | None = None
    ):
        super().__init__()
        self.host = host
        self.remote_port = remote_port
        self.local_port = local_port
        self.bind_device(remote_type)
        if endpoints:
            self.create_endpoints(endpoints)

    def bind_device(self, remote_type: ClientSetupFunction):
        print(f"Using remote device: {remote_type.__annotations__['return']}")
        self.device = remote_type(self)
        sleep(STARTUP_DELAY)
        print("Device bound")
        print(self.device)

class NodeClient(OssiaClient):
    def __init__(self, host: str, local_port: int, endpoints: dict):
        super().__init__(
            host = host,
            local_port = local_port,
            remote_type = ClientDevices.OSCQUERY,
            endpoints = endpoints
        )

class PlayerClient(OssiaClient):
    def __init__(self, player_port: int, endpoints: dict):
        super().__init__(
            local_port = player_port,
            remote_type = ClientDevices.OSC,
            endpoints = endpoints
        )
