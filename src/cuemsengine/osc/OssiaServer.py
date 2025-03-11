# from threading import Thread
from pyossia import LocalDevice
from typing import Union

from .OssiaNodes import OssiaNodes
from .helpers import ServerDevices

ENGINE_CLIENT_PORT = 9000
ENGINE_SERVER_PORT = 9001
OSCQUERY_REQ_PORT = 40250
OSCQUERY_WS_PORT = 40255

class OssiaServer(OssiaNodes):
    def __init__(
            self,
            name: str = None,
            log: bool = False,
            host: str = "127.0.0.1",
            client_port: int = ENGINE_CLIENT_PORT,
            server_port: int = ENGINE_SERVER_PORT,
            server: ServerDevices = ServerDevices.OSC,
            endpoints: Union[dict, list] = None
        ):
        super().__init__()
        if not name:
            name = self.__class__.__name__
        self.host = host
        self.device = LocalDevice(name)
        self.logging = log
        self.client_port = client_port
        self.server_port = server_port
        self.setup_server(server)
        if endpoints:
            self.create_endpoints(endpoints)

    def setup_server(self, server: ServerDevices) -> None:
        """Create a local OSC server
        
        Create a local device and set it up to handle oscquery or osc requests
        """
        done = server(self)
        self.started = done
        if not done:
            raise Exception("Server setup failed")
