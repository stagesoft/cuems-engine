from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.osc_message import OscMessage
from pythonosc.udp_client import SimpleUDPClient
from threading import Thread

PYOSC_HOST = "127.0.0.1"
PYOSC_PORT = 10001
PYOSC_MSG_TIMEOUT = 0.001

def new_osc_client(cls) -> SimpleUDPClient:
    return SimpleUDPClient(cls.host, cls.port)

class PyOscClient(object):
    def __init__(self, host = PYOSC_HOST, port = PYOSC_PORT):
        self.host = host
        self.port = port
        self.client = new_osc_client(self)
    
    def send_message(self, address: str, *args) -> None:
        self.client.send_message(address, args)

    def get_first_message(self, timeout = PYOSC_MSG_TIMEOUT) -> OscMessage:
        res = self.client.get_messages(timeout)
        msg = next(res)
        return msg
    
    def send_with_response(self, address: str, *args) -> OscMessage:
        self.send_message(address, *args)
        return self.get_first_message()

class PyOscServer(object):
    def __init__(self, host = PYOSC_HOST, port = PYOSC_PORT, endpoints = []):
        self.host = host
        self.port = port
        self.endpoints = endpoints
        self.dispatcher = Dispatcher()
        self.handlers = {}
        self.server = self.new_server()
    
    def start(self) -> None:
        self.thread = Thread(
            target = self.server.serve_forever,
            daemon = True
        )
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def new_server(self) -> ThreadingOSCUDPServer:
        self.add_handlers()
        return ThreadingOSCUDPServer(
            (self.host, self.port),
            self.dispatcher
        )

    def add_handlers(self) -> None:
        """
        Add handlers to the dispatcher and store them in the handlers dict
        """
        if len(self.endpoints) == 0:
            return
        for endpoint_,function_ in self.endpoints.items():
            self.handlers[endpoint_] = self.dispatcher.map(
                endpoint_, function_
            )
