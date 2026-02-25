"""Utilites for communications from ControllerEngine and NodeEngine."""
import asyncio
import json
from pynng import Context
from typing import Optional, Callable, Any

from cuemsutils.log import Logger
from cuemsutils.tools.CommunicatorServices import Communicator, IpcAddress

from .AsyncCommsThread import AsyncCommsThread
from .NodesHub import NodesHub, NodeOperation, OperationType, ActionType
from ..osc.WebSocketOscHandler import (
    websocket_osc_listener,
    build_osc_message,
    WebSocketOscRouter
)


class ControllerCommunications(AsyncCommsThread):
    """
    Communications class for ControllerEngine.
    
    Handles:
    - Editor messages
    - Player operation messages
    - Nodeconf messages
    - HWDiscovery messages
    - WebSocket OSC messages (commands from UI)
    """
    def __init__(self, 
                 nng_hub_address: str,
                 editor_callback: Callable,
                 node_operation_callback: dict[OperationType, Callable],
                 websocket_osc_config: Optional[dict] = None):
        """
        Initialize AsyncCommsThread for ControllerEngine.
        
        Parameters:
        - nng_hub_address: TCP/IPC address for NNG hub (e.g., "tcp://127.0.0.1:5555")
        - editor_callback: Callback for editor messages
        - node_operation_callback: Callback dictionary for received node operations
        - websocket_osc_config: Optional dict with WebSocket OSC listener config:
            - host: Host to bind to (default: "0.0.0.0")
            - port: Port to listen on (default: 9190)
            - node_id: Node identifier for NNG operations
        """
        super().__init__()
        
        # Initialize communicators
        Logger.debug('Initializing ControllerCommunications')
        self.editor_callback = editor_callback
        self.editor = Communicator(IpcAddress.EDITOR.value)
        self.hw_discovery = Communicator(IpcAddress.HWDISCOVERY.value)
        self.nodeconf = Communicator(IpcAddress.NODECONF.value)
        
        # Initialize OSC hub based on mode
        Logger.info(f'Initializing NNG hub: {nng_hub_address} in {NodesHub.Mode.LISTENER.value} mode')
        self.nng_hub = NodesHub(
            hub_address=nng_hub_address, mode=NodesHub.Mode.LISTENER
        )
        
        # Set operation callbacks
        self.nng_hub.set_receive_callbacks(node_operation_callback)
        
        # WebSocket OSC configuration
        self._ws_osc_config = websocket_osc_config or {}
        self._ws_osc_host = self._ws_osc_config.get('host', '0.0.0.0')
        self._ws_osc_port = self._ws_osc_config.get('port', 9190)
        self._node_id = self._ws_osc_config.get('node_id', 'controller')
        
        # WebSocket OSC router for message handling
        self._osc_router = WebSocketOscRouter()
        
        # Track connected WebSocket clients for status broadcast (bidirectional)
        self._ws_clients: set = set()
        
        # Command handlers (set by ControllerEngine)
        self._command_handlers: dict[str, Callable] = {}

    def create_all_tasks(self):
        Logger.info('Starting all tasks in ControllerCommunications')
        tasks = [
            asyncio.create_task(self.editor_listener()),
            asyncio.create_task(self.nng_hub.start()),
            asyncio.create_task(self.nng_hub.start_message_receiver())
        ]
        
        # Add WebSocket OSC listener if configured
        if self._ws_osc_port:
            tasks.append(asyncio.create_task(self._websocket_osc_task()))
        
        return tasks
    
    #########################
    # WebSocket OSC handling
    #########################
    
    def register_command_handler(self, osc_path: str, handler: Callable[[Any], None], 
                                  forward_to_nodes: bool = True) -> None:
        """Register a handler for an OSC command path.
        
        Args:
            osc_path: The OSC address to handle (e.g., '/engine/command/go')
            handler: Callback function to handle the command value
            forward_to_nodes: If True, also forward the command to NodeEngine via NNG
        """
        self._command_handlers[osc_path] = {
            'handler': handler,
            'forward': forward_to_nodes
        }
        
        # Register with the OSC router
        self._osc_router.register(osc_path, lambda addr, args: self._handle_osc_command(addr, args))
        Logger.debug(f"Registered command handler for {osc_path} (forward={forward_to_nodes})")
    
    def register_osc_handler(self, osc_pattern: str, handler: Callable[[str, list], None]) -> None:
        """Register a generic OSC handler for a pattern (non-command messages).
        
        Args:
            osc_pattern: OSC address pattern (e.g., '/engine/players/*')
            handler: Callback function receiving (address, args)
        """
        self._osc_router.register(osc_pattern, handler)
        Logger.debug(f"Registered OSC handler for {osc_pattern}")
    
    def _handle_osc_command(self, address: str, args: list[Any]) -> None:
        """Handle an OSC command received via WebSocket.
        
        Calls the registered handler and optionally forwards to NodeEngine.
        """
        handler_info = self._command_handlers.get(address)
        if not handler_info:
            Logger.warning(f"No handler registered for OSC command: {address}")
            return
        
        # Get the value (first argument, or None for impulse)
        value = args[0] if args else None
        
        Logger.info(f"WebSocket OSC command received: {address} = {repr(value)}")
        
        # Call the handler
        try:
            handler_info['handler'](value)
        except Exception as e:
            Logger.error(f"Error executing command handler for {address}: {e}")
        
        # Forward to NodeEngine via NNG if configured
        if handler_info.get('forward', True):
            self._forward_command_to_nodes(address, value)
    
    def _forward_command_to_nodes(self, address: str, value: Any) -> None:
        """Forward a command to NodeEngine via NNG.
        
        Args:
            address: The OSC command address (e.g., '/engine/command/go')
            value: The command value
        """
        # Extract command name from address (e.g., '/engine/command/go' -> 'go')
        parts = address.strip('/').split('/')
        command_name = parts[-1] if parts else address
        
        operation = NodeOperation(
            type=OperationType.COMMAND,
            action=ActionType.UPDATE,
            sender=self._node_id,
            target=command_name,
            data={'value': value, 'address': address}
        )
        
        # Send via NNG (fire-and-forget)
        try:
            asyncio.run_coroutine_threadsafe(
                self.nng_hub.send_operation(operation),
                self.event_loop
            )
            Logger.debug(f"Forwarded command to nodes: {command_name} = {repr(value)}")
        except Exception as e:
            Logger.error(f"Error forwarding command to nodes: {e}")
    
    async def _websocket_osc_task(self) -> None:
        """Async task that runs the WebSocket OSC listener."""
        await websocket_osc_listener(
            host=self._ws_osc_host,
            port=self._ws_osc_port,
            message_handler=self._osc_router.route,
            stop_check=lambda: self.stop_requested,
            client_set=self._ws_clients
        )

    def broadcast_osc(self, address: str, value: Any) -> None:
        """Send an OSC status message to all connected WebSocket clients.
        
        Call from ControllerEngine when status changes (running, armed, load, timecode).
        Thread-safe: schedules send on the comms event loop.
        
        Args:
            address: OSC address (e.g. '/engine/status/armed')
            value: Value to send (str, int, or float)
        """
        data = build_osc_message(address, value)
        if not data or not self._ws_clients:
            return
        async def _send_all():
            for ws in list(self._ws_clients):
                try:
                    await ws.send(data)
                except Exception as e:
                    Logger.debug(f"WebSocket broadcast to client failed: {e}")
        try:
            asyncio.run_coroutine_threadsafe(_send_all(), self.event_loop)
        except Exception as e:
            Logger.debug(f"Could not schedule status broadcast: {e}")


    #########################
    # Editor messages
    #########################
    async def editor_listener(self):
        """Editor listener (thread-safe)."""
        Logger.info('Editor listener started')
        await self.editor.responder_connect()
        while not self.stop_requested:
            Logger.debug(f'waiting for editor message')
            await self.editor.responder_get_request(self.editor_callback)

    async def respond_to_editor(self, message, context: Context):
        """Respond to editor (thread-safe)."""
        Logger.debug(f'Sending to editor: {message}, with context ')
        await context.asend(json.dumps(message).encode())
    
    def reply_to_editor(self, message, context: Context):
        send_task = asyncio.run_coroutine_threadsafe(
            self.editor.responder_post_reply(message, context),
            self.event_loop
        )
        try:
            _ = send_task.result(timeout=self.timeout)
        except TimeoutError:
            Logger.debug('The coroutine took too long, cancelling the task...')
            send_task.cancel()
            raise
        except Exception as exc:
            Logger.debug(f'The coroutine raised an exception: {exc!r}')
            send_task.cancel()
            raise


    #########################
    # Nodeconf messages
    #########################
    def request_to_nodeconf(self, message: dict, timeout: Optional[float] = None) -> dict:
        """
        Send a request to nodeconf and get response (thread-safe).
        
        Parameters:
        - message: Dictionary containing the request message
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        
        Returns:
        - dict: Response from `nodeconf.send_request` via `run_coroutine` method
        
        Raises:
        - AttributeError: If `nodeconf` is not initialized
        """
        if not self.nodeconf:
            raise AttributeError('nodeconf communicator is not initialized')
        
        return self.run_coroutine(self.nodeconf.send_request, message, timeout)
    
    #########################
    # HWDiscovery messages
    #########################
    def request_to_hwdiscovery(self, message: dict, timeout: Optional[float] = None) -> dict:
        """
        Send a request to hardware discovery and get response (thread-safe).
        
        Parameters:
        - message: Dictionary containing the request message
        - timeout: Optional timeout in seconds (defaults to `self.timeout`)
        
        Returns:
        - dict: Response from `hwdiscovery.send_request` via `run_coroutine` method
        
        Raises:
        - AttributeError: If `hwdiscovery` is not initialized
        """
        if not self.hw_discovery:
            raise AttributeError('hw_discovery communicator is not initialized')
        
        return self.run_coroutine(self.hw_discovery.send_request, message, timeout)
