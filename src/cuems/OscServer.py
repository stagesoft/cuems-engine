from pythonosc import dispatcher
from pythonosc import osc_server
import threading

from .log import logger

class OscServer():
    def __init__(self, host='127.0.0.1', port=1234, mappings=None):
        self.dispatcher = dispatcher.Dispatcher()

        self.init_func_mappings(mappings)

        self.server = osc_server.ThreadingOSCUDPServer((host, port), self.dispatcher)
        logger.info(f"Engine OSC server on {host} : {self.server.server_address} : {port}")

    def init_func_mappings(self, mappings):
        try:
            for k, v in mappings.items():
                self.dispatcher.map(k, v, k)
        except:
            self.dispatcher.map('*', self.default_handler, 'Default handler')

    def start(self):
        threaded_service = threading.Thread(name='osc_server_thread', target=self.server.serve_forever, kwargs={'poll_interval':0.05})
        threaded_service.start()
        '''Note: it is needed to run it in an internal thread because it stucks itself in the
        serve_forever method call. In this way we can still have control of our own thread'''

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def default_handler(self, address, args, value):
        logger.info(f'OSC message received: {address} {args} {value}')

