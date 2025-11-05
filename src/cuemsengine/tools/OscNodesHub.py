from enum import Enum
from dataclasses import dataclass
from cuemsutils.tools.HubServices import Message, Nng_bus_hub
from cuemsutils.log import Logger
import asyncio
from typing import Optional, Dict, Callable

from ..osc.helpers import Node, serialize_node, deserialize_node

class ActionType(Enum):
    ADD = "add"
    REMOVE = "remove"
    UPDATE = "update"

@dataclass
class PlayerOperation:
    """Represents an operation to be performed on a player's OSC nodes."""
    action: ActionType
    player_id: str  # Unique player identifier
    node_data: Optional[dict]  # None for REMOVE operations
    sender: str  # Node that sent this player

class OscNodesHub(Nng_bus_hub):
    """
    Extension of Nng_bus_hub for transmitting pyossia player node structures.
    
    Nodes send player structures (player_id + root_node) to the controller.
    Players are transmitted one by one as they become available.
    This class handles transmission only - storage is left to the user.
    """
    
    def __init__(self, hub_address: str, mode=Nng_bus_hub.Mode.LISTENER):
        """
        Initialize OscNodesHub.
        
        Parameters:
        - hub_address: The address for the bus communication
        - mode: CONTROLLER or NODE mode
        """
        super().__init__(hub_address, mode)
        
        # Callback for when player operations are received (controller side)
        self._on_player_received: Optional[Callable] = None
        
        # Note: We use the base class queues (self.outgoing and self.incoming)
    
    def set_player_received_callback(self, callback: Callable[[str, str, Optional[dict], ActionType], None]):
        """
        Set a callback to be invoked when player operations are received (controller side).
        
        Parameters:
        - callback: Function that takes (sender, player_id, node_data, action) as arguments
                   node_data will be None for REMOVE operations
        """
        self._on_player_received = callback
    
    async def add_player(self, player_id: str, root_node: Node, action: ActionType = ActionType.ADD):
        """
        Add a player to the send queue (node side).
        
        This queues the player to be transmitted to the controller.
        The base class sender will automatically transmit it.
        
        Parameters:
        - player_id: Unique identifier for the player
        - root_node: The root node of the player's OSC structure
        - action: The type of action (ADD or UPDATE)
        """
        # Serialize immediately and create message
        message = {
            "__type__": "osc_player",
            "player_id": player_id,
            "action": action.value,
            "node_data": serialize_node(root_node)
        }
        
        # Use base class send_message which adds to self.outgoing queue
        await self.send_message(message)
        Logger.debug(f"Queued player {player_id} for sending with action {action.value}")
    
    async def remove_player(self, player_id: str):
        """
        Queue a player removal (node side).
        
        Parameters:
        - player_id: Unique identifier of the player to remove
        """
        # Create REMOVE message (no node_data needed)
        message = {
            "__type__": "osc_player",
            "player_id": player_id,
            "action": ActionType.REMOVE.value,
            "node_data": None
        }
        
        # Use base class send_message which adds to self.outgoing queue
        await self.send_message(message)
        Logger.debug(f"Queued player {player_id} for removal")
    
    # Note: start_player_sender() is no longer needed!
    # The base class _send_handler() already processes self.outgoing queue
    # which we now use directly via send_message() in add_player() and remove_player()
    
    async def get_player_operation(self) -> PlayerOperation | None:
        """
        Get the next player operation from the queue (controller side).
        
        This filters messages to only return OSC player operations.
        
        Returns:
        - PlayerOperation or None if no player operations available
        """
        try:
            message = await self.get_message()
            
            # message.data is already a dict (JSON-decoded by base class)
            data = message.data
            
            # Check if this is an OSC player message
            if data.get("__type__") == "osc_player":
                action = ActionType(data["action"])
                player_id = data["player_id"]
                node_data = data.get("node_data")
                
                return PlayerOperation(
                    action=action,
                    player_id=player_id,
                    node_data=node_data,
                    sender=message.sender
                )
            else:
                # Not a player operation, could be a regular message
                Logger.debug(f"Received non-player message type: {data.get('__type__')}")
                return None
                
        except Exception as e:
            Logger.error(f"Error getting player operation: {e}")
            return None
    
    async def start_player_receiver(self):
        """
        Continuously receive player operations and invoke callback (controller side).
        
        This runs in a loop, receiving player operations and invoking the callback
        if set. Should be run as a background task.
        
        The callback receives: (sender, player_id, node_data, action)
        - node_data will be None for REMOVE operations
        """
        while True:
            try:
                operation = await self.get_player_operation()
                
                if operation:
                    sender_key = str(operation.sender)
                    
                    Logger.info(
                        f"Received {operation.action.value} for player {operation.player_id} "
                        f"from {sender_key}"
                    )
                    
                    # Invoke callback if set
                    if self._on_player_received:
                        if asyncio.iscoroutinefunction(self._on_player_received):
                            await self._on_player_received(
                                sender_key,
                                operation.player_id,
                                operation.node_data,
                                operation.action
                            )
                        else:
                            self._on_player_received(
                                sender_key,
                                operation.player_id,
                                operation.node_data,
                                operation.action
                            )
                
                await asyncio.sleep(0.01)  # Small delay to prevent tight loop
                
            except Exception as e:
                Logger.error(f"Error in start_player_receiver: {e}")
                await asyncio.sleep(1)  # Back off on error
