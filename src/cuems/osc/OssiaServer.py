# from threading import Thread
from pyossia import LocalDevice, ValueType
from typing import Union

from OSCNodes import OSCNodes

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

class OssiaServer(OSCNodes):
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


"""Logging testing functions"""
def print_node(node):
    print(node)
    params = node.get_parameters()
    # print(str(params)) # Parameter objects addresses
    for param in params:
        print(f"Parameter info: [node: {param.node}, value: {param.value}, value_type: {param.value_type}]")

def iterate_on_devices(node):
    print_node(node)
    for child in node.children():
        print_node(child)
        if child.children():
            iterate_on_devices(child)
        else:
            print("No children")

def print_callback(node, value):
    print(
        f"Parameter changed at {node} to {value} [node value: {node.parameter.value}]"
    )

TEST_STR = 'goo'
import sys
import inspect
def print_test(x: str = TEST_STR):
    frame = sys._getframe(0)
    print(frame)
    print(frame.f_back)
    print(inspect.getmodule(frame))
    print(inspect.getmodule(frame.f_back))
    print(frame.f_code.co_name)
    print(f'name: {__name__}')
    print(f'func name: {print_test.__name__}')
    print(f'module: {print_test.__module__}')
    print(f'constant: {x}')

if __name__ == "__main__":

    from time import sleep

    test_endpoints = {
        # "/test1": [ValueType.Int, print_callback, 10],
        # "/test2": [ValueType.Int, print_callback, 20],
        "/test3": [ValueType.Int, print_callback, 30],
        "/test4": [ValueType.Int, print_callback, 40],
        # "/test/subcmd": [ValueType.Int, None, 330]
    }
    os = OssiaServer(log = True, endpoints = test_endpoints)
        
    iterate_on_devices(os.device.root_node)

    try:
        while True:
            pass
            # in_str = input('[?] Usage: <path>:<value>\n')
            # if in_str:
            #     path, value = in_str.split(":")
            #     try:
            #         print(f"[+] Path: {path}, Value: {int(value)}")
            #         os.set_value(path, int(value))
            #     except Exception as e:
            #         print(f'[!] {e}')
            #     in_str = None
            # else:
            #     sleep(0.01)
    except KeyboardInterrupt as e:
        print(": KeyboardInterrupt recieved")
        print("Server Ending...")
