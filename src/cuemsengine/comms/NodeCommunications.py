import asyncio
from typing import Optional

from cuemsutils.log import Logger

from .AsyncCommsThread import AsyncCommsThread
from .NodesHub import NodesHub, ActionType


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
        """Create async tasks for node communications
        
        Note: NNG hub is not started since communication happens via OSCQuery
        """
        Logger.info('Starting all tasks in NodeCommunications (OSCQuery mode)')
        # Return empty list - communication happens via OSCQuery, not NNG
        return []
    
    async def hub_message_receiver(self):
        """Receive and process messages from the NNG hub"""
        Logger.info('Hub message receiver started')
        while not self.stop_requested:
            try:
                message = await self.nng_hub.get_message()
                if message and isinstance(message.data, dict):
                    msg_type = message.data.get('__type__')
                    if msg_type == 'command':
                        action = message.data.get('action')
                        value = message.data.get('value', '')
                        Logger.info(f'Received command from hub: {action}')
                        self.run_command(action, value)
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                Logger.debug('Hub message receiver cancelled')
                break
            except Exception as e:
                if self.stop_requested:
                    break
                Logger.error(f'Error in hub_message_receiver: {e}')
                await asyncio.sleep(1)
        Logger.info('Hub message receiver stopped')

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
        return self.run_coroutine(self.nng_hub.add_player, message, timeout)
    
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
        return self.run_coroutine(self.nng_hub.remove_player, message, timeout)
