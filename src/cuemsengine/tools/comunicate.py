"""Utilites to call the hardware discovery tool."""
from cuemsutils.log import logged

HWDISCOVERY_IPC = 'ipc:///tmp/hwdiscovery.ipc'
NODECONF_IPC = 'ipc:///tmp/nodeconf.ipc'
EDITOR_IPC = 'ipc:///tmp/editor.ipc'

def comunicate(ipc: str):
    """
    Comunicate with external tools
    """
    message = f"Comunicating with {ipc}"
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
    comunicate(HWDISCOVERY_IPC)

@logged
def call_nodeconf():
    """
    Call the node configuration tool
    """
    comunicate(NODECONF_IPC)

@logged
def call_editor():
    """
    Call the editor tool
    """
    comunicate(EDITOR_IPC)

class EditorWsServer():
    def __init__(self, *args, **kwargs):
        self.editor = None

    def start(self):
        self.editor = call_editor()
        return self.editor
    
    def stop(self):
        self.editor = None
        return self.editor
