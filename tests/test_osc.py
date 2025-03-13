
from pyossia import ValueType

from src.cuemsengine.osc.OssiaServer import OssiaServer
from src.cuemsengine.osc.OssiaClient import OssiaClient

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

def test_server_init(capfd):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback, 10],
        "/test2": [ValueType.Int, print_callback, 20],
        "/test3": [ValueType.Int, print_callback, 30],
        "/test4": [ValueType.Int, print_callback, 40]
    }
    os = OssiaServer(log = False, endpoints = test_endpoints)
    assert os.started == True

    out, err = capfd.readouterr()
    assert "Parameter changed at" in out
    assert len(out) > 0
    assert len(err) == 0
    assert len(os.device.root_node.children()) == 4
    out_lines = out.split("\n")
    assert out_lines[-1] == ''
    assert len(out_lines) == 5

    iterate_on_devices(os.device.root_node)
    out, err = capfd.readouterr()
    assert "Parameter changed at" not in out
    assert "Parameter info" in out
    assert "No children" in out

def test_client_init(capfd):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback],
        "/test2": [ValueType.Int, print_callback, 10],
        "/test3": [ValueType.Int, print_callback, 20],
        "/test4": [ValueType.Int, print_callback, 30]
    }
    client = OssiaClient(
        endpoints = test_endpoints,
        # remote_type = RemoteDevices.OSCQUERY
    )

    out, err = capfd.readouterr()
    assert "Parameter changed at" in out
    assert len(out) > 0
    assert len(err) == 0
    assert len(client.device.root_node.children()) == 4
    out_lines = out.split("\n")
    assert out_lines[-1] == ''
    assert len(out_lines) == 5

    iterate_on_devices(client.device.root_node)
    out, err = capfd.readouterr()
    assert "Parameter changed at" not in out
    assert "Parameter info" in out
    assert "No children" in out

class store_response():
        def __init__(self, response = None):
            self.response = response
        
        def set(self, value):
            self.response = value

def test_client_alters_server():
    # ARRANGE
    server_res = store_response()
    server_endpoints = {
        "/test": [ValueType.Int, server_res.set, 30],
    }
    client_res = store_response()
    client_endpoints = {
        "/test": [ValueType.Int, client_res.set, 10],
    }
    LOCAL = 9091
    REMOTE = 9991

    # ACT
    server = OssiaServer(
        endpoints=server_endpoints
    )
    client = OssiaClient(
        # local_port = 9000,
        # remote_port = 9001,
        endpoints = client_endpoints
    )
    
    # ASSERT
    ## Check that the server started with default values
    assert server.started == True
    assert server_res.response == 30
    assert client_res.response == 10
    ## Check that client alters server values
    client.set_value("/test", 20)
    client.set_value("/test", 20)
    assert client_res.response == 20
    assert server_res.response == 20
    ## Check that server does not alter client values
    server.set_value("/test", 40)
    assert server_res.response == 40
    assert client_res.response == 20
