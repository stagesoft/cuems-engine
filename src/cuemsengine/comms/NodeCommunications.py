import asyncio
from typing import Optional

from cuemsutils.log import Logger

from .AsyncCommsThread import AsyncCommsThread
from .NodesHub import NodesHub, ActionType, OperationType, NodeOperation


class NodeCommunications(AsyncCommsThread):
    def __init__(self, hub_address: str, node_id: str):
        """
        Initialize AsyncCommsThread for NodeEngine.
        
        - Runs `OscNodesHub` in `DIALER` mode
        - Sends players to `ControllerEngine`
        - Listens to Controller OSCQueryServer using a GlobalMessageQueue
        - Filters and redirects OSCQuery signals to local endpoints
        
        Parameters:
        - hub_address: TCP/IPC address for OSC hub (e.g., "tcp://127.0.0.1:5555")
        - commands_dict: Dictionary of engine commands to run on the node
        """
        super().__init__()
        self.nng_hub = NodesHub(
            hub_address, mode=NodesHub.Mode.DIALER
        )
        self.node_id = node_id

    def create_all_tasks(self):
        """Create async tasks for node communications."""
        Logger.info('Starting all tasks in NodeCommunications')
        return [
            asyncio.create_task(self.nng_hub.start())
        ]

    #########################
    # Nng comms to Controller
    #########################
    def send_operation(self, operation: NodeOperation, timeout: Optional[float] = None):
        """
        Send a NodeOperation to the controller (thread-safe).
        
        Parameters:
        - operation: NodeOperation to send
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        return self.run_coroutine(self.nng_hub.send_operation, operation, timeout)
    
    def add_player(self, player_id: str, data: dict, timeout: Optional[float] = None):
        """
        Add a player to the OSC hub (thread-safe).
        
        Parameters:
        - player_id: Unique identifier for the player
        - data: Player data to send
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        operation = NodeOperation(
            type=OperationType.PLAYER,
            action=ActionType.ADD,
            sender=self.node_id,
            target=player_id,
            data=data
        )
        return self.send_operation(operation, timeout)
    
    def remove_player(self, player_id: str, timeout: Optional[float] = None):
        """
        Remove a player from the OSC hub (thread-safe).
        
        Parameters:
        - player_id: Unique identifier of the player to remove
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        operation = NodeOperation(
            type=OperationType.PLAYER,
            action=ActionType.REMOVE,
            sender=self.node_id,
            target=player_id,
            data=None
        )
        return self.send_operation(operation, timeout)
