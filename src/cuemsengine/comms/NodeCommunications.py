from pyossia import GlobalMessageQueue
from threading import Thread
from time import sleep
from typing import Optional

from cuemsutils.log import Logger

from ..tools.PortHandler import PORT_HANDLER
from ..players.PlayerHandler import PLAYER_HANDLER
from ..osc.helpers import ClientDevices
from ..osc.OssiaClient import OssiaClient

from .AsyncCommsThread import AsyncCommsThread
from .NodesHub import NodesHub, ActionType


class NodeCommunications(AsyncCommsThread):
    def __init__(self, osc_hub_address: str, commands_dict: dict, node_id: str):
        """
        Initialize AsyncCommsThread for NodeEngine.
        
        - Runs `OscNodesHub` in `DIALER` mode
        - Sends players to `ControllerEngine`
        - Listens to Controller OSCQueryServer using a GlobalMessageQueue
        - Filters and redirects OSCQuery signals to local endpoints
        
        Parameters:
        - osc_hub_address: TCP/IPC address for OSC hub (e.g., "tcp://127.0.0.1:5555")
        - commands_dict: Dictionary of engine commands to run on the node
        """
        super().__init__()
        self.osc_hub = NodesHub(
            osc_hub_address, mode=NodesHub.Mode.DIALER
        )
        self.ocsquery_queue_loop = Thread(
            target=self.oscquery_loop, name='OSCQueryQueueLoop'
        )
        self.commands_dict = commands_dict
        self.node_id = node_id

    def start(self):
        self.start_oscquery()
        self.ocsquery_queue_loop.start()
        super().start()

    def stop(self):
        self.ocsquery_queue_loop.join()
        super().stop()

    #########################
    # OSCQuery logic
    #########################
    def start_oscquery(self, host: str = None, port: int = None):
        """
        Add OSCQuery client to listen to Controller OSCQueryServer through GlobalMessageQueue
        """
        self.oscquery_client = OssiaClient(
            host = host,
            local_port = PORT_HANDLER.new_random_port(),
            remote_port = port,
            remote_type = ClientDevices.OSCQUERY
        )

        self.oscquery_queue = GlobalMessageQueue(self.oscquery_client.device)
    
    def oscquery_loop(self):
        while not self.stop_requested:
            message = self.oscquery_queue.pop()
            if message is not None:
                parameter, value = message
                self.route_message(parameter, value)
            else:
                sleep(0.001)

    def route_message(self, parameter, value):
        path_elements = str(parameter.node).split('/')[1:]
        if path_elements[0] == 'command':
            self.run_command(path_elements[1], value)
        if path_elements[0] == 'players':
            if path_elements[1] != self.node_id:
                return
            if path_elements[2] == 'video':
                PLAYER_HANDLER.route_video_message('/'.join(path_elements[3:]), value)
            if path_elements[2] == 'audio':
                PLAYER_HANDLER.route_audio_message('/'.join(path_elements[3:]), value)
            if path_elements[2] == 'dmx':
                PLAYER_HANDLER.route_dmx_message('/'.join(path_elements[3:]), value)
        else:
            Logger.debug(f'Recieved unused OSCQuery path: {str(parameter.node)}')
            return

    def run_command(self, command, value):
        if command in self.commands_dict.keys():
            self.commands_dict[command](value)
            return True
        else:
            Logger.error(f'Command {command} not found')
            return False

    #########################
    # Nng comms to Controller
    #########################
    def add_player(self, player_id: str, root_node, timeout: Optional[float] = None) -> dict:
        """
        Add a player to the OSC hub (thread-safe).
        
        Parameters:
        - player_id: Unique identifier for the player
        - root_node: pyossia Node object (the player's device root)
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        message = {
            "player_id": player_id,
            "root_node": root_node,
            "action": ActionType.ADD
        }
        return self.run_coroutine(self.osc_hub.add_player, message, timeout)
    
    def remove_player(self, player_id: str, timeout: Optional[float] = None) -> dict:
        """
        Remove a player from the OSC hub (thread-safe).
        
        Parameters:
        - player_id: Unique identifier of the player to remove
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        message = {
            "player_id": player_id,
            "action": ActionType.REMOVE
        }
        return self.run_coroutine(self.osc_hub.remove_player, message, timeout)
