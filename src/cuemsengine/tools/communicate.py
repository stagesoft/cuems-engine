"""Utilites to call the hardware discovery tool."""
from cuemsutils.log import logged, Logger
from cuemsutils.tools.CommunicatorServices import Communicator
import asyncio

HWDISCOVERY_IPC = '/tmp/hwdiscovery.ipc'
NODECONF_IPC = '/tmp/nodeconf.ipc'
EDITOR_IPC = '/tmp/editor.ipc'
TIMEOUT = 25 #TODO: make it configurable, or get from settings

def communicate(ipc: str):
    """
    Communicate with external tools
    """

    message = f"Communicating with {ipc}"
    # context = zmq.Context()
    # socket = context.socket(zmq.REQ)
    # socket.connect(ipc)
    # socket.send_string('Hello')
    # message = socket.recv()
    return Communicator(ipc)
@logged
def hwdiscovery_callback(*args, **kwargs):
        nodeconf_msg = call_nodeconf()
        discovery_msg = call_hwdiscovery()
        return {
            'discovery': discovery_msg,
            'nodeconf': nodeconf_msg
        }

@logged
def call_hwdiscovery():
    """
    Call the hardware discovery tool
    """
    return communicate(HWDISCOVERY_IPC)

@logged
def call_nodeconf():
    """
    Call the node configuration tool
    """
    return communicate(NODECONF_IPC)

@logged
def editor_listener():
    """
    Call the editor tool
    """
    
    return communicate(EDITOR_IPC)

class EditorWsServer():
    def __init__(self, *args, **kwargs):
        self.editor = None

    def start(self):
        self.editor = editor_listener()
        return self.editor
    
    def stop(self):
        self.editor = None
        return self.editor
    
class CommunicatorListener():
    def __init__(self, editor_callback: callable):
        self.editor = editor_listener()
        self.editor_callback = editor_callback

    async def listen(self):
        Logger.info(f"Starting editor listener on {EDITOR_IPC}")
        await self.editor.reply(self.editor_callback)


class CominunicatorDialer():
    def __init__(self, communicator: Communicator):
        self.caller = communicator


    async def dial(self, msg: dict):
        try:
            async with asyncio.timeout(TIMEOUT):
                Logger.debug(f"Sending request to {self.caller}: {msg}")
                response = await self.caller.send_request(msg)
                return response
        except asyncio.TimeoutError:
            Logger.error("Timeout while waiting for response from the dialer")
            return False
        