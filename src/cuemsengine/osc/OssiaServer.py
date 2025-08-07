# from threading import Thread
from pyossia import LocalDevice
from typing import Union
from time import sleep

from .OssiaNodes import OssiaNodes, STARTUP_DELAY
from .helpers import ServerDevices, ServerSetupFunction

OSCSERVER_LOCAL_PORT = 9000
OSCSERVER_REMOTE_PORT = 9001

class OssiaServer(OssiaNodes):
    def __init__(
            self,
            name: str | None = None,
            log: bool = False,
            host: str = "127.0.0.1",
            remote_port: int = OSCSERVER_REMOTE_PORT,
            local_port: int = OSCSERVER_LOCAL_PORT,
            server: ServerSetupFunction = ServerDevices.OSC,
            endpoints: Union[dict, list] | None = None
        ):
        super().__init__()
        if not name:
            name = self.__class__.__name__
        self.host = host
        self.device = LocalDevice(name)
        self.logging = log
        self.remote_port = remote_port
        self.local_port = local_port
        self.setup_server(server)
        if endpoints:
            self.create_endpoints(endpoints)

    def setup_server(self, server: ServerSetupFunction) -> None:
        """Create a local OSC server
        
        Create a local device and set it up to handle oscquery or osc requests
        """
        done = server(self)
        sleep(STARTUP_DELAY)
        self.started = done
        if not done:
            self.remove_device()
            raise Exception("Server setup failed")
