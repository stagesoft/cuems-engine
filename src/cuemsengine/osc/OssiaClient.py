# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from time import sleep
from typing import Union

from cuemsutils.log import Logger
from pyossia import ossia

from ..tools.PortHandler import PORT_HANDLER
from .helpers import ClientDevices, ClientSetupFunction
from .OssiaNodes import STARTUP_DELAY, OssiaNodes

OSCCLIENT_LOCAL_PORT = 9009
OSCCLIENT_REMOTE_PORT = 9001


class OssiaClient(OssiaNodes):
    def __init__(
        self,
        host: str = "127.0.0.1",
        local_port: int = OSCCLIENT_LOCAL_PORT,
        remote_port: int = OSCCLIENT_REMOTE_PORT,
        remote_type: ClientSetupFunction = ClientDevices.OSC,
        endpoints: Union[dict, list] | None = None,
        name: str = "cuems",
    ):
        super().__init__()
        self.host = host
        self.name = name
        self.remote_port = remote_port
        self.local_port = local_port
        self.bind_device(remote_type)
        # In OSCQuery clients do not create nodes, just read them
        if endpoints and remote_type == ClientDevices.OSC:
            self.create_endpoints(endpoints)

    def bind_device(self, remote_type: ClientSetupFunction):
        Logger.info(f"Using remote device: {remote_type.__annotations__['return']}")
        self.device = remote_type(self)
        sleep(STARTUP_DELAY)
        if not self.device:
            raise RuntimeError("OssiaClient device not bound")
        Logger.debug(f"OssiaClient device bound: {self.device}")

        # Skip nodes_from_device() for OSCQuery clients to preserve GMQ functionality
        if remote_type == ClientDevices.OSCQUERY:
            self.nodes = {}
        else:
            try:
                self.nodes = self.nodes_from_device()
            except Exception as e:
                Logger.warning(f"nodes_from_device() failed: {e}")
                self.nodes = {}

    def add_node_creation_callback(self, callback: callable):
        Logger.debug(f"Now adding callback to {self.device}")
        _ = ossia.DeviceCallback(self.device, callback, callback, callback)


class NodeClient(OssiaClient):
    def __init__(self, host: str, local_port: int, endpoints: dict):
        super().__init__(
            host=host,
            local_port=local_port,
            remote_type=ClientDevices.OSCQUERY,
            endpoints=endpoints,
        )


class PlayerClient(OssiaClient):
    def __init__(self, player_port: int, endpoints: dict, name: str = "player"):
        super().__init__(
            local_port=PORT_HANDLER.new_random_port(),
            remote_port=player_port,
            remote_type=ClientDevices.OSC,
            endpoints=endpoints,
            name=name,
        )
