"""Utilites to call the hardware discovery tool."""
from cuemsutils.log import logged, Logger
from cuemsutils.tools.CommunicatorServices import Communicator
import threading
import pynng
import json
import time

HWDISCOVERY_IPC = '/tmp/hwdiscovery.ipc'
NODECONF_IPC = '/tmp/nodeconf.ipc'
EDITOR_IPC = '/tmp/editor.ipc'
TIMEOUT = 10  # seconds

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
    

class ComsThread(threading.Thread):
    def __init__(self, queue,  editor_callback: callable, listener_adresses: list = None, dialer_adresses: dict = None):
        self.editor_callback = editor_callback
        
        self.listener_adresses = listener_adresses if listener_adresses is not None else {}
        self.listeners = {}
        self.dialer_adresses = dialer_adresses if dialer_adresses is not None else {}
        self.dialers = {}
        self.queue = queue
        self.timeout = TIMEOUT * 1000
        self.stop_requested = False
        self.send_contexts= []
        threading.Thread.__init__(self, name='Communications', daemon=True)

 

    def run(self):
        Logger.info("Starting Coms_thread")
        for name, address in self.listener_adresses.items():
           Logger.debug(f"Creating listener for {name} at {address}")
           self.listeners[name] = pynng.Rep0(listen=address, send_timeout=self.timeout, recv_timeout=self.timeout)
            
            
        for name, address in self.dialer_adresses.items():
            Logger.debug(f"Creating dialer for {name} at {address}")
            self.dialers[name] = pynng.Req0(dial=address, send_timeout=self.timeout, recv_timeout=self.timeout)
    
        while not self.stop_requested:
            for name, listener in self.listeners.items():
                try:
                    msg = listener.recv(block=False)
                    decoded_msg =json.loads(msg.decode())
                    Logger.info(f"Received message: {decoded_msg}")
                    self.editor_callback(decoded_msg)
                    response = self.get_from_queue("editor")
                    Logger.debug(f"Response to send: {response}")
                    encoded_response = json.dumps(response).encode()
                    listener.send(encoded_response, block=False)
                except pynng.exceptions.TryAgain:
                    pass
                except Exception as e:
                    Logger.error(f"Error in listener: {e} {type(e)}")
                

            if not self.queue.empty():
                msg = self.queue.get()
                Logger.debug(f'Received queue message from main thread: {msg}')
                match msg['destination']:
                    case 'hw_discovery':
                        try:
                            Logger.debug(f"Sending message to hw_discovery with  dialer {self.dialers['hw_discovery']}")
                            new_context = self.dialers['hw_discovery'].new_context()
                            encoded_request = json.dumps(msg).encode()
                            new_context.send(encoded_request)
                            self.send_contexts.append(new_context)
                        except pynng.exceptions.Timeout:
                            Logger.error(f'Timeout in sending message to hw_dicovery')
                        

            for context in self.send_contexts:
                try:
                    Logger.debug(f'trying to receive response from {context}')
                    response = context.recv()
                    Logger.debug(f'Received response: {response}')
                    decoded_response = json.loads(response.decode())
                except pynng.exceptions.TryAgain:
                    pass
                except Exception as e:
                    Logger.error(f"Error triying to recevie msg: {e}")
                finally:
                    context.close()
                    self.send_contexts.remove(context)
                
            time.sleep(0.1)  # Sleep to prevent busy waiting

    def get_from_queue(self, destination):
        self.get_from_qeueue ()
    def get_from_qeueue(self):
        pass

                

