import asyncio
from typing import Optional, Callable, Any

from cuemsutils.log import Logger

from .AsyncCommsThread import AsyncCommsThread
from .NodesHub import NodesHub, ActionType, OperationType, NodeOperation


class NodeCommunications(AsyncCommsThread):
    def __init__(self, hub_address: str, node_id: str, 
                 command_callback: Optional[Callable[[str, Any], None]] = None):
        """
        Initialize AsyncCommsThread for NodeEngine.
        
        - Runs `OscNodesHub` in `DIALER` mode
        - Sends players to `ControllerEngine`
        - Receives COMMAND operations from ControllerEngine via NNG
        - Routes commands to NodeEngine handlers
        
        Parameters:
        - hub_address: TCP/IPC address for OSC hub (e.g., "tcp://127.0.0.1:5555")
        - node_id: Unique identifier for this node
        - command_callback: Optional callback for handling received commands.
                           Called with (command_name: str, value: Any)
        """
        super().__init__()
        self.nng_hub = NodesHub(
            hub_address, mode=NodesHub.Mode.DIALER
        )
        self.node_id = node_id
        self._command_callback = command_callback
        
        # Set up receive callbacks: COMMAND for local dispatch, STATUS for fade_complete.
        self.nng_hub.set_receive_callbacks({
            OperationType.COMMAND: self._handle_command_operation,
            OperationType.STATUS: self._handle_status_operation,
        })

    def set_command_callback(self, callback: Callable[[str, Any], None]) -> None:
        """Set the callback for handling received commands.
        
        Args:
            callback: Function to call when a command is received.
                     Called with (command_name: str, value: Any)
        """
        self._command_callback = callback
        Logger.debug(f"Command callback set in NodeCommunications")

    def create_all_tasks(self):
        """Create async tasks for node communications."""
        Logger.info('Starting all tasks in NodeCommunications')
        Logger.info(f'NNG hub mode: {self.nng_hub.mode}')
        Logger.info(f'NNG hub address: {self.nng_hub.address}')
        Logger.info(f'Command callbacks registered: {list(self.nng_hub._on_operation_received.keys()) if self.nng_hub._on_operation_received else "None"}')
        return [
            asyncio.create_task(self.nng_hub.start()),
            asyncio.create_task(self.nng_hub.start_message_receiver())
        ]
    
    def _handle_command_operation(self, operation: NodeOperation) -> None:
        """Handle a COMMAND operation received from ControllerEngine.
        
        IMPORTANT: Commands are executed in a separate thread to avoid blocking
        the NNG message receiver. Some commands like 'go' can block for the 
        duration of cue playback, which would prevent receiving STOP/LOAD commands.
        
        Args:
            operation: The NodeOperation containing the command
        """
        if operation.type != OperationType.COMMAND:
            return

        # gradient-motiond commands are forwarded over NNG but must not be executed
        # locally — the target field discriminates them from Python engine commands.
        if operation.target == "gradientengine":
            return

        command_name = operation.target
        data = operation.data or {}
        value = data.get('value')
        address = data.get('address', f'/engine/command/{command_name}')
        
        Logger.info(f"Received command via NNG: {command_name} = {repr(value)}")
        
        if self._command_callback:
            # Execute command in a separate thread to avoid blocking the NNG receiver
            # This is critical because commands like 'go' block until cue playback completes
            import threading
            def run_command():
                try:
                    self._command_callback(command_name, value, address)
                except Exception as e:
                    Logger.error(f"Error executing command callback for {command_name}: {e}")
            
            thread = threading.Thread(
                target=run_command,
                name=f"NNG-Command-{command_name}",
                daemon=True
            )
            thread.start()
            Logger.debug(f"Started command thread: {thread.name}")
        else:
            Logger.warning(f"No command callback set for NodeCommunications")

    def _handle_status_operation(self, operation: NodeOperation) -> None:
        """Handle STATUS operations on the NNG bus.

        gradient-motiond STATUS broadcasts (e.g. fade_complete) are logged at
        debug level and discarded — the Python engine no longer mutates state
        in response to them (general cue lifecycle handles all disarm). All
        other STATUS messages (e.g. nextcue updates) are not handled here —
        they originate from NodeEngine itself and do not arrive inbound.

        Args:
            operation: The received NodeOperation of type STATUS.
        """
        if operation.target == "gradientengine":
            data = operation.data or {}
            event = data.get("event")
            fade_id = data.get("fade_id", "")
            Logger.debug(
                f"gradient-motiond STATUS discarded: event={event} fade_id={fade_id}"
            )
            return

    ###############################
    # gradient-motiond NNG dispatch
    ###############################

    def send_fade_command(self, payload: dict, fade_id: str,
                          timeout: Optional[float] = None) -> None:
        """Send a start_fade command to gradient-motiond via NNG.

        Wraps the body returned by ActionHandler._build_fade_payload with the
        four envelope fields (command, fade_id, osc_host, curve_params) and
        sends as a COMMAND/UPDATE operation targeting gradientengine.

        Args:
            payload: FadeCommand body (osc_port, osc_path, start_value,
                target_value, start_time, duration_ms, curve_type).
            fade_id: Correlation key (FadeCue.uuid as string).
            timeout: Optional send timeout in seconds.
        """
        wrapped = {
            "command": "start_fade",
            "fade_id": fade_id,
            "osc_host": "127.0.0.1",
            "curve_params": {},
            **payload,
        }
        operation = NodeOperation(
            type=OperationType.COMMAND,
            action=ActionType.UPDATE,
            sender=self.node_id,
            target="gradientengine",
            data=wrapped,
        )
        self.send_operation(operation, timeout)

    def send_cancel_all(self, timeout: Optional[float] = None) -> None:
        """Send a cancel_all command to gradient-motiond via NNG.

        Args:
            timeout: Optional send timeout in seconds.
        """
        operation = NodeOperation(
            type=OperationType.COMMAND,
            action=ActionType.UPDATE,
            sender=self.node_id,
            target="gradientengine",
            data={"command": "cancel_all"},
        )
        self.send_operation(operation, timeout)

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

    def add_cue(self, cue_id: str, offset: str, timeout: Optional[float] = None):
        """
        Add a cue to the OSC hub (thread-safe).
        
        Parameters:
        - cue_id: Unique identifier of the cue to add
        - data: Data to send
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        operation = NodeOperation(
            type=OperationType.CUE,
            action=ActionType.ADD,
            sender=self.node_id,
            target=cue_id,
            data={
                'id': cue_id,
                'offset': offset
            }
        )
        return self.send_operation(operation, timeout)

    def remove_cue(self, cue_id: str, timeout: Optional[float] = None):
        """
        Remove a cue from the OSC hub (thread-safe).
        
        Parameters:
        - cue_id: Unique identifier of the cue to remove
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        operation = NodeOperation(
            type=OperationType.CUE,
            action=ActionType.REMOVE,
            sender=self.node_id,
            target=cue_id,
            data={'id': cue_id}
        )
        return self.send_operation(operation, timeout)

    def update_nextcue(self, cue_id: str, timeout: Optional[float] = None):
        """Send a nextcue status update to the controller (thread-safe).

        Parameters:
        - cue_id: UUID of the next cue (or empty string when no next cue)
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        operation = NodeOperation(
            type=OperationType.STATUS,
            action=ActionType.UPDATE,
            sender=self.node_id,
            target='nextcue',
            data={'nextcue': cue_id}
        )
        return self.send_operation(operation, timeout)

    def update_cue(self, cue_id: str, percentage: int, timeout: Optional[float] = None):
        """Send a cue percentage progress update to the controller (thread-safe).

        Used during playback to report in-progress status (values 1-99).

        Callers MUST throttle calls to CUE_STATUS_UPDATE_HZ (defined in loop_cue.py)
        before invoking this method to limit NNG traffic over the network in
        multi-node deployments (Tier 1 of the two-tier throttle strategy).
        The controller applies a second throttle (CUE_BROADCAST_MIN_INTERVAL) before
        forwarding to the UI via WebSocket (Tier 2).

        Parameters:
        - cue_id: Unique identifier of the cue being played
        - percentage: Playback progress (1-99); 1 = started, 99 = almost done
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        """
        operation = NodeOperation(
            type=OperationType.CUE,
            action=ActionType.UPDATE,
            sender=self.node_id,
            target=cue_id,
            data={'id': cue_id, 'percentage': percentage}
        )
        return self.send_operation(operation, timeout)
