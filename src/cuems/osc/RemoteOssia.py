from time import sleep

from pyossia import OSCQueryDevice, ossia
from OssiaServer import iterate_on_devices, add_int_param, set_value, OSC_CLIENT_PORT, OSC_REQ_PORT, OSCQUERY_REQ_PORT, OSCQUERY_WS_PORT

class RemoteOssia():
    def __init__(self, host: str = "127.0.0.1"):
        print(self.__class__.__name__)
        self.host = host
        self.url = f"ws://{host}:{OSCQUERY_WS_PORT}"
        self.client = OSCQueryDevice(
            "cuems", self.url, OSCQUERY_REQ_PORT
        )
        self.client.update()

    def new_osc_device(self):
        self.osc = ossia.OSCDevice(
            "cuems", self.host, OSC_REQ_PORT, OSC_CLIENT_PORT
        )
    
    def add_device(self, path: str):
        self.client.add_node(path)

if __name__ == "__main__":

    ro = RemoteOssia()
    # ro.new_osc_device()
    # iterate_on_devices(ro.osc.root_node)
    base_node = ro.client.find_node("/")
    sleep(3)

    # Add new node
    root_node = base_node.add_node("/")

    new_node = root_node.add_node("/test3")
    add_int_param(new_node, 80)

    # Try adding value from OSCDevice
    new_node = root_node.add_node("/test4")
    add_int_param(new_node, 40)
    
    iterate_on_devices(root_node)
    sleep(3)

    try:
        while True:
            pass
            # in_str = input('[?] Usage: <path>:<value>\n')
            # if in_str:
            #     path, value = in_str.split(":")
            #     print(f"[+] Path: {path}, Value: {int(value)}")
            #     set_value(ro.osc, path, int(value))
            #     in_str = None
            # else:
            #     pass
    except KeyboardInterrupt as e:
        print(": KeyboardInterrupt recieved")
        print("Remote Ending...")
