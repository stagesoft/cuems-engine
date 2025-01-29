# from threading import Thread

from pyossia import LocalDevice, ValueType, Node, AccessMode

import time

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

class OssiaServer():
    def __init__(self, name: str = None):
        self.nodes = {}
        if not name:
            name = self.__class__.__name__
        self.device = LocalDevice(name)
        self.setup_server(True)

    def add_node(self, path: str):
        self.nodes[path] = self.device.add_node(path)

    def setup_server(self, logging: bool = False):
        """Create a local OSC server
        
        Create a local device and set it up to handle oscquery and osc requests
        
        Parameters:
        logging (bool): enable protocol logging. Default is False
        """
        try:
            self.device.create_oscquery_server(
                OSCQUERY_REQ_PORT, OSCQUERY_WS_PORT, logging
            )
            # self.device.create_osc_server(
            #     "127.0.0.1", OSC_CLIENT_PORT, OSC_REQ_PORT, logging
            # )
        except Exception as e:
            print(e)

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

def add_int_param(node, value):
    param = node.create_parameter(ValueType.Int)
    param.value = value
    # passes parameter value into it
    # param.add_callback(parameter_callback_print_value)

    # passes Node object and paramenter value into it
    param.add_callback_param(parameter_callback_print)
    param.access_mode = AccessMode.Bi # default value

def parameter_callback_print(node, value):
    print(f"Parameter changed at {node} to {value}")

def parameter_callback_print_value(value):
    print(f"[+] Recieved Parameter value: {value}")

def set_value(device, path: str, value):
    n_ = device.find_node(path)
    if isinstance(n_, Node):
        n_.parameter.push_value(value)
        # n_.parameter.fetch_value()
    else:
        print(f"[!] Node not found: {path}")

if __name__ == "__main__":
    os = OssiaServer()
    os.add_node("/test")
    os.add_node("/test2")
    os.add_node("/test/subcmd")
    add_int_param(os.nodes["/test"], 10)
    add_int_param(os.nodes["/test2"], 210)
    add_int_param(os.nodes["/test/subcmd"], 230)

    # iterate_on_devices(os.device.root_node)
    
    #time.sleep(5)

    os.add_node("/test3")
    add_int_param(os.nodes["/test3"], 310)
    
    #time.sleep(5)

    os.add_node("/test4")
    add_int_param(os.nodes["/test4"], 310)
    
    time.sleep(15)
    iterate_on_devices(os.device.root_node)

    time.sleep(15)
    try:
        while True:
            # pass
            in_str = input('[?] Usage: <path>:<value>\n')
            if in_str:
                path, value = in_str.split(":")
                print(f"[+] Path: {path}, Value: {int(value)}")
                set_value(os.device, path, int(value))
                in_str = None
            else:
                pass
    except KeyboardInterrupt as e:
        print(": KeyboardInterrupt recieved")
        print("Server Ending...")
