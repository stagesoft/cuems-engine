"""Utilites to call the hardware discovery tool."""
from cuemsutils.log import logged
from cuemsutils.tools.CommunicatorServices import Communicator

HWDISCOVERY_IPC = '/tmp/hwdiscovery.ipc'
NODECONF_IPC = '/tmp/nodeconf.ipc'
EDITOR_IPC = '/tmp/editor.ipc'

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
    return message

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
    communicate(HWDISCOVERY_IPC)

@logged
def call_nodeconf():
    """
    Call the node configuration tool
    """
    communicate(NODECONF_IPC)

@logged
def call_editor():
    """
    Call the editor tool
    """
    communicate(EDITOR_IPC)
    return Communicator(EDITOR_IPC)

class EditorWsServer():
    def __init__(self, *args, **kwargs):
        self.editor = None

    def start(self):
        self.editor = call_editor()
        return self.editor
    
    def stop(self):
        self.editor = None
        return self.editor
