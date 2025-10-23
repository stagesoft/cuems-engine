"""Utilites to call the hardware discovery tool."""
from cuemsutils.log import logged, Logger
from cuemsutils.tools.CommunicatorServices import Communicator
from cuemsutils.tools.Osc_nodes_hub import OscNodesHub, ActionType
import threading
import asyncio
import json
from typing import Optional, Callable
from enum import Enum

HWDISCOVERY_IPC = '/tmp/hwdiscovery.ipc'
NODECONF_IPC = '/tmp/nodeconf.ipc'
EDITOR_IPC = '/tmp/editor.ipc'
TIMEOUT = 15  # seconds



@logged
def get_hwdiscovery_comm():
    """
    Call the hardware discovery tool
    """
    return Communicator(HWDISCOVERY_IPC)

@logged
def get_nodeconf_comm():
    """
    Call the node configuration tool
    """
    return Communicator(NODECONF_IPC)

@logged
def get_editor_comm():
    """
    Call the editor tool
    """
    return Communicator(EDITOR_IPC)

    

class AsyncCommsThread(threading.Thread):
    class Mode(Enum):
        """Operating mode for AsyncCommsThread."""
        CONTROLLER = "controller"  # Full communicators + OSC hub as controller
        NODE = "node"              # Only OSC hub as node
    
    def __init__(self, 
                 osc_hub_address: str,
                 editor_callback: Optional[Callable] = None,
                 osc_player_callback: Optional[Callable] = None,
                 mode: Mode = Mode.CONTROLLER):
        """
        Initialize AsyncCommsThread in CONTROLLER or NODE mode.
        
        CONTROLLER MODE:
        - Runs all communicators (editor, hwdiscovery, nodeconf)
        - Runs OscNodesHub in CONTROLLER mode
        - Receives players from nodes
        - Requires: editor_callback, osc_player_callback
        
        NODE MODE:
        - Only runs OscNodesHub in NODE mode
        - Sends players to controller
        - No communicators needed
        - Requires: None (callbacks ignored)
        
        Parameters:
        - osc_hub_address: TCP/IPC address for OSC hub (e.g., "tcp://127.0.0.1:5555")
        - editor_callback: Callback for editor messages (CONTROLLER mode only)
        - osc_player_callback: Callback for received players (CONTROLLER mode only)
        - mode: AsyncCommsThread.Mode.CONTROLLER (default) or AsyncCommsThread.Mode.NODE
        """
        Logger.info(f'Initializing communications thread in {mode.value} mode')
        self.mode = mode
        self.timeout = TIMEOUT * 1000
        self.stop_requested = False
        self.send_contexts = []
        threading.Thread.__init__(self, name=f'Communications-{mode.value}', daemon=True)
        
        # Initialize communicators only in CONTROLLER mode
        self.editor = None
        self.hw_discovery = None
        self.nodeconf = None
        self.editor_callback = None
        
        if self.mode == self.Mode.CONTROLLER:
            if not editor_callback:
                raise ValueError("editor_callback is required in CONTROLLER mode")
            
            Logger.debug('Initializing communicators (CONTROLLER mode)')
            self.editor_callback = editor_callback
            self.editor = get_editor_comm()
            self.hw_discovery = get_hwdiscovery_comm()
            self.nodeconf = get_nodeconf_comm()
        
        # Initialize OSC hub based on mode
        osc_hub_mode = OscNodesHub.Mode.CONTROLLER if mode == self.Mode.CONTROLLER else OscNodesHub.Mode.NODE
        Logger.info(f'Initializing OSC hub: {osc_hub_address} in {osc_hub_mode.value} mode')
        self.osc_hub = OscNodesHub(osc_hub_address, mode=osc_hub_mode)
        
        # Set player callback only in CONTROLLER mode
        self.osc_player_callback = osc_player_callback
        if self.mode == self.Mode.CONTROLLER:
            if not osc_player_callback:
                Logger.warning('No osc_player_callback provided in CONTROLLER mode')
            if osc_player_callback:
                self.osc_hub.set_player_received_callback(osc_player_callback)
        
        
 

    def run(self):
        Logger.debug('Comms thread run called')
        self.event_loop = asyncio.new_event_loop()
        self.event_loop.create_task(self.run_asyncio_comms())
        self.event_loop.run_forever()
    def stop(self):
        stop_requested = True
        asyncio.run_coroutine_threadsafe(self.stop_async(), self.event_loop)
    
    async def stop_async(self):
        self.event_loop.call_soon_threadsafe(self.event_loop.stop)
        Logger.info('event loop stoped')
                

    async def run_asyncio_comms(self):
        Logger.info(f'Starting asyncio communications in {self.mode.value} mode')
        tasks = []
        
        # Start communicators only in CONTROLLER mode
        if self.mode == self.Mode.CONTROLLER:
            Logger.info('Starting communicators (editor, hwdiscovery, nodeconf)')
            editor_task = asyncio.create_task(self.editor_listener())
            tasks.append(editor_task)
        
        # Start OSC hub (always)
        Logger.info('Starting OSC nodes hub')
        osc_hub_task = asyncio.create_task(self.osc_hub.start())
        tasks.append(osc_hub_task)
        
        # Start player receiver only in CONTROLLER mode
        if self.mode == self.Mode.CONTROLLER:
            Logger.info('Starting OSC player receiver')
            player_receiver_task = asyncio.create_task(self.osc_hub.start_player_receiver())
            tasks.append(player_receiver_task)
        
        # Wait for all tasks
        await asyncio.gather(*tasks, return_exceptions=True)
        
        Logger.debug('asyncio comms finished')
        #
    async def editor_listener(self):
        """Editor listener (CONTROLLER mode only)."""
        if self.mode != self.Mode.CONTROLLER:
            Logger.warning('editor_listener called in NODE mode, exiting')
            return
        
        Logger.info('Editor listener started')
        await self.editor.responder_connect()
        while not self.stop_requested:
            Logger.debug(f'waiting for editor message')
            await self.editor.responder_get_request(self.editor_callback)

    async def respond_to_editor(self, message, context):
        """Respond to editor (CONTROLLER mode only)."""
        if self.mode != self.Mode.CONTROLLER:
            Logger.warning('respond_to_editor called in NODE mode')
            return
        
        Logger.debug(f'Sending to editor: {message}, with context ')
        await context.asend(json.dumps(message).encode())
    
    def add_player(self, player_id: str, root_node, action: ActionType = ActionType.ADD):
        """
        Add a player to the OSC hub (NODE mode only, thread-safe).
        
        Parameters:
        - player_id: Unique identifier for the player
        - root_node: pyossia Node object (the player's device root)
        - action: ActionType (ADD or UPDATE)
        """
        if self.mode != self.Mode.NODE:
            Logger.warning('add_player should only be called in NODE mode')
            return
        
        # Schedule the coroutine in the event loop (thread-safe)
        asyncio.run_coroutine_threadsafe(
            self.osc_hub.add_player(player_id, root_node, action),
            self.event_loop
        )
        Logger.debug(f'Queued player {player_id} for sending')
    
    def remove_player(self, player_id: str):
        """
        Remove a player from the OSC hub (NODE mode only, thread-safe).
        
        Parameters:
        - player_id: Unique identifier of the player to remove
        """
        if self.mode != self.Mode.NODE:
            Logger.warning('remove_player should only be called in NODE mode')
            return
        
        # Schedule the coroutine in the event loop (thread-safe)
        asyncio.run_coroutine_threadsafe(
            self.osc_hub.remove_player(player_id),
            self.event_loop
        )
        Logger.debug(f'Queued player {player_id} for removal')

