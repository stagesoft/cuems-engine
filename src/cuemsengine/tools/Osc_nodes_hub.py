from enum import Enum
from dataclasses import dataclass
from cuemsutils.tools.CommunicatorServices import Message, Nng_bus_hub
from cuemsutils.log import Logger
import pyossia
import json
import asyncio
from typing import Optional, Dict, Callable

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
    
    def __init__(self, hub_address: str, mode=Nng_bus_hub.Mode.CONTROLLER):
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
    
    @staticmethod
    def serialize_node(node: pyossia.ossia.Node) -> dict:
        """
        Serialize a pyossia node and its children to a dictionary structure.
        
        Parameters:
        - node: The pyossia node to serialize
        
        Returns:
        - dict: Serialized node structure
        """
        node_dict = {
            "name": node.name,
            "children": [],
            "parameter": None
        }
        
        # Serialize parameter if exists
        param = node.parameter
        if param:
            param_dict = {
                "access": str(param.access_mode),
                "bounding": str(param.bounding_mode),
                "type": str(param.value_type) if hasattr(param, 'value_type') else None,
            }
            
            # Try to get current value
            try:
                value = param.value
                # Convert value to JSON-serializable format
                if hasattr(value, '__iter__') and not isinstance(value, str):
                    param_dict["value"] = list(value)
                else:
                    param_dict["value"] = value
            except:
                param_dict["value"] = None
            
            # Get other parameter properties
            try:
                param_dict["domain"] = str(param.domain) if hasattr(param, 'domain') else None
                param_dict["unit"] = str(param.unit) if hasattr(param, 'unit') else None
            except:
                pass
                
            node_dict["parameter"] = param_dict
        
        # Recursively serialize children
        for child in node.children():
            node_dict["children"].append(OscNodesHub.serialize_node(child))
        
        return node_dict
    
    @staticmethod
    def deserialize_node(node_data: dict, parent_node: Optional[pyossia.ossia.Node] = None) -> pyossia.ossia.Node:
        """
        Deserialize a dictionary structure into pyossia nodes.
        
        Parameters:
        - node_data: The serialized node structure
        - parent_node: Optional parent node to attach to
        
        Returns:
        - pyossia.ossia.Node: The reconstructed node
        """
        if parent_node is None:
            raise ValueError("Parent node required for deserialization")
        
        # Create the node
        node = parent_node.add_node(node_data["name"])
        
        # Recreate parameter if it existed
        if node_data.get("parameter"):
            param_dict = node_data["parameter"]
            param = node.create_parameter(pyossia.ossia.ValueType.Float)  # Default type
            
            # Set parameter properties
            if param_dict.get("value") is not None:
                try:
                    param.value = param_dict["value"]
                except:
                    Logger.warning(f"Could not set value for parameter at {node.name}")
        
        # Recursively create children
        for child_data in node_data.get("children", []):
            OscNodesHub.deserialize_node(child_data, node)
        
        return node
    
    async def add_player(self, player_id: str, root_node: pyossia.ossia.Node, action: ActionType = ActionType.ADD):
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
            "node_data": self.serialize_node(root_node)
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
    
    async def get_player_operation(self) -> Optional[PlayerOperation]:
        """
        Get the next player operation from the queue (controller side).
        
        This filters messages to only return OSC player operations.
        
        Returns:
        - PlayerOperation or None if no player operations available
        """
        try:
            message = await self.get_message()
            
            # Try to parse as JSON
            if isinstance(message.data, str):
                try:
                    data = json.loads(message.data)
                except json.JSONDecodeError:
                    # Not a JSON message, not a player operation
                    Logger.debug("Received non-JSON message, skipping")
                    return None
            else:
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
