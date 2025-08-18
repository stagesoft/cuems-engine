"""Utilites to call the hardware discovery tool."""
from cuemsutils.log import logged, Logger
from cuemsutils.tools.CommunicatorServices import Communicator
import threading
from pynng import Req0, Rep0, Timeout, TryAgain
import json

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
    communicate(HWDISCOVERY_IPC)

@logged
def call_nodeconf():
    """
    Call the node configuration tool
    """
    communicate(NODECONF_IPC)

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
        Logger.info(f"Starting editor listener ######################### on {EDITOR_IPC}")
        await self.editor.reply(self.editor_callback)


class ComsThread(threading.Thread):
    def __init__(self, queue,  editor_callback: callable, listener_adresses: list = None, dialer_adresses: dict = None):
        self.editor_callback = editor_callback
        
        self.listener_adresses = listener_adresses if listener_adresses is not None else {}
        self.listeners = {}
        self.dialer_adresses = dialer_adresses if dialer_adresses is not None else {}
        self.dialers = {}
        self.queue = queue
        self.timeout = 20000
        threading.Thread.__init__(self)


    def run(self):
        Logger.info("Starting Coms_thread")
        for name, address in self.listener_adresses.items():
           self.listeners[name] = Rep0(listen=address, send_timeout=self.timeout, recv_timeout=self.timeout)
            
            
        for name, address in self.dialer_adresses.items():
            self.dialers[name] = Req0(dial=address, send_timeout=self.timeout, recv_timeout=self.timeout)
    
        while not self.stop_requested:
            for listener in self.listeners:
                try:
                    msg = listener.recv(blocking=False)
                    Logger.info(f"Received message: {msg}")
                    response = self.editor_callback(msg)
                    encoded_response = json.dumps(response).encode()
                    listener.send(encoded_response)
                except Exception as e:
                    Logger.error(f"Error in listener: {e}")
                except TryAgain:
                    pass  # no message received yet, try again    

            if not self.queue.empty():
                msg = self.engine_queue.get()
                Logger.debug(f'Received queue message from main thread: {msg}')
                match msg['destination']:
                    case 'nodeconf':
                        try:
                            encoded_request = json.dumps(msg).encode()
                            self.dialers['nodeconf'].send(encoded_request)
                        except Timeout:
                            Logger.error(f'Timeout in sending message to nodeconf')
                        
            for name, dialer in self.dialers.items():
                try:
                    response = dialer.recv(bloking=False)
                    decoded_response = json.loads(response.decode())
                    Logger.info(f"Received response: {decoded_response} from {name}")
                except Exception as e:
                    Logger.error(f"Error in dialer: {e}")
                except TryAgain:
                    pass  # no response received yet, try again


                

