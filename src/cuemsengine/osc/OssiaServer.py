# from threading import Thread
from pyossia import LocalDevice
from typing import Union

from .OssiaNodes import OssiaNodes

OSC_CLIENT_PORT = 9989
OSC_REQ_PORT = 9091
OSCQUERY_REQ_PORT = 40250
OSCQUERY_WS_PORT = 40255

"""LocalDevice.create_oscquery_server

    Make the local device able to handle oscquery request
    @param int port where OSC requests have to be sent by any remote client to
        deal with the local device
    @param int port where WebSocket requests have to be sent by any remote client
        to deal with the local device
    @param bool enable protocol logging
    @return bool */
"""

"""LocalDevice.create_osc_server

    Make the local device able to handle osc request and emit osc message
    @param int port where osc messages have to be sent to be catch by a remote
        client to listen to the local device
    @param int port where OSC requests have to be sent by any remote client to
        deal with the local device
    @param bool enable protocol logging
    @return bool
"""

class OssiaServer(OssiaNodes):
    def __init__(
            self,
            name: str = None,
            log: bool = False,
            endpoints: Union[dict, list] = None
        ):
        super().__init__()
        if not name:
            name = self.__class__.__name__
        self.device = LocalDevice(name)
        self.setup_server(log)
        if endpoints:
            self.create_endpoints(endpoints)

    def setup_server(self, logging: bool = False):
        """Create a local OSC server
        
        Create a local device and set it up to handle oscquery and osc requests
        
        Parameters:
        logging (bool): enable protocol logging. Default is False
        """
        try:
            # self.device.create_oscquery_server(
            #     OSCQUERY_REQ_PORT, OSCQUERY_WS_PORT, logging
            # )
            self.device.create_osc_server(
                "127.0.0.1", OSC_CLIENT_PORT, OSC_REQ_PORT + 1, logging
            )
        except Exception as e:
            print(e)
