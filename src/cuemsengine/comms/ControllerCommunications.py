"""Utilites for communications from ControllerEngine and NodeEngine."""
import asyncio
import json
from pynng import Context
from typing import Optional, Callable

from cuemsutils.log import Logger
from cuemsutils.tools.CommunicatorServices import Communicator, IpcAddress

from .AsyncCommsThread import AsyncCommsThread
from .NodesHub import NodesHub, PlayerOperation


class ControllerCommunications(AsyncCommsThread):
    """
    Communications class for ControllerEngine.
    
    Handles:
    - Editor messages
    - Player operation messages
    - Nodeconf messages
    - HWDiscovery messages
    """
    def __init__(self, 
                 osc_hub_address: str,
                 editor_callback: Callable,
                 player_operation_callback: Optional[Callable] = None):
        """
        Initialize AsyncCommsThread for ControllerEngine.
        
        Parameters:
        - osc_hub_address: TCP/IPC address for OSC hub (e.g., "tcp://127.0.0.1:5555")
        - editor_callback: Callback for editor messages
        - player_operation_callback: Callback for received player operations
        """
        super().__init__()
        
        # Initialize communicators
        Logger.debug('Initializing ControllerCommunications')
        self.editor_callback = editor_callback
        self.editor = Communicator(IpcAddress.EDITOR.value)
        self.hw_discovery = Communicator(IpcAddress.HWDISCOVERY.value)
        self.nodeconf = Communicator(IpcAddress.NODECONF.value)
        
        # Initialize OSC hub based on mode
        Logger.info(f'Initializing OSC hub: {osc_hub_address} in {NodesHub.Mode.LISTENER.value} mode')
        self.osc_hub = NodesHub(osc_hub_address, mode=NodesHub.Mode.LISTENER)
        
        # Set player callback
        self.player_operation_callback = player_operation_callback
        if not player_operation_callback:
            Logger.warning('No player_operation_callback provided in CONTROLLER mode')
        if player_operation_callback:
            self.osc_hub.set_player_received_callback(player_operation_callback)

    def create_all_tasks(self):
        Logger.info('Starting all tasks in ControllerCommunications')
        return [
            asyncio.create_task(self.editor_listener()),
            asyncio.create_task(self.osc_hub.start()),
            asyncio.create_task(self.osc_hub.start_player_receiver())
        ]


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
