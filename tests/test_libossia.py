from cuemsengine.osc.OssiaServer import OssiaServer
from cuemsengine.osc.OssiaClient import OssiaClient

from pyossia import ValueType

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

def test_client_empty_init():
    client = OssiaClient()
    client.device = None
    try:
        client.set_node("/test")
    except Exception as e:
        assert type(e) == AttributeError
        assert str(e) == "No device found"

    client.device = "device"
    try:
        client.set_node("/test")
    except Exception as e:
        assert type(e) == AttributeError
        assert str(e) == "'str' object has no attribute 'root_node'"

    client = OssiaClient(endpoints = "test")
    assert len(client.nodes) == 0
    assert len(client.device.root_node.children()) == 0

    try:
        client.set_value("/test", 10)
    except Exception as e:
        assert type(e) == ValueError
        assert str(e) == "Node not found"

def test_client_failed_value():
    client = OssiaClient(
        endpoints = {"/test1": [ValueType.Int, None, None]}
    )
    try:
        client.set_value("/test1", "no_int")
    except Exception as e:
        assert type(e) == ValueError
        assert str(e) == "Could not set /test1 to no_int"
    
    client_node = client.get_node("/test1")
    assert client_node.parameter.value == 0
    try:    
        client.set_value(client_node, "no_int")
    except Exception as e:
        assert type(e) == ValueError
        assert str(e) == "Could not set /test1 to no_int"

    client.remove_node("/test1")
    assert len(client.nodes) == 0
    try:
        client.get_node("/test1")
    except Exception as e:
        assert type(e) == KeyError

    try:
        client.create_endpoint("/test1", [int, None, None])
    except Exception as e:
        assert type(e) == ValueError
        assert str(e) == "value_type must be a pyossia.ValueType"

    try:
        client.create_endpoint("/test1", [ValueType.Int, lambda x, y, z: x+y+z, 10])
    except Exception as e:
        assert type(e) == ValueError
        assert str(e) == "callback must have 1 or 2 parameters"

def test_client_list_endpoints():
    endpoints = ["/test1", "/test2", "/test3"]
    client = OssiaClient(
        endpoints = endpoints
    )
    assert len(client.nodes) == 3
    assert len(client.device.root_node.children()) == 3

def test_server_empty_init():
    server = OssiaServer(name = "test_server")
    assert len(server.nodes) == 0
    assert len(server.device.root_node.children()) == 0

def test_server_failed_init():
    def server_callback(server):
        return False
    try:
        server = OssiaServer(
            server = server_callback
        )
    except Exception as e:
        assert str(e) == "Server setup failed"

def test_server_init(capfd):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback, 10],
        "/test2": [ValueType.Int, print_callback, 20],
        "/test3": [ValueType.Int, print_callback, 30],
        "/test4": [ValueType.Int, print_callback, 40],
        "/test1/test1": [ValueType.Int, print_callback, 50],
    }
    os = OssiaServer(
        log = False,
        endpoints = test_endpoints
    )
    assert os.started == True

    out, err = capfd.readouterr()
    assert "Parameter changed at" in out
    assert len(out) > 0
    assert len(err) == 0
    assert len(os.device.root_node.children()) == 4
    out_lines = out.split("\n")
    assert out_lines[-1] == ''
    assert len(out_lines) == 6

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

def test_no_transmission_on_same_thread():
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
    assert client_res.response == 20
    assert server_res.response == 30
    ## Check that server does not alter client values
    server.set_value("/test", 40)
    assert server_res.response == 40
    assert client_res.response == 20

def test_transmission_on_threaded_client():
    """Use threading to test the client transmission"""
    from threading import Thread
    from multiprocessing import Process
    from time import sleep

    # ARRANGE
    server_res = store_response()
    server_endpoints = {
        "/test": [ValueType.Int, server_res.set, 30],
    }
    client_res = store_response()
    client_endpoints = {
        "/test": [ValueType.Int, client_res.set, 10],
    }
    server = OssiaServer(endpoints=server_endpoints)
    client = OssiaClient(
        local_port = 9003,
        remote_port = 9001,
        endpoints = client_endpoints
    )

    thread_client = Thread(
        target = client.set_value,
        kwargs = {
            "node": "/test",
            "value": 20
        },
        daemon = True
    )

    # ACT
    thread_client.start()

    # ASSERT
    ## Check that client alters server values
    assert client_res.response == 20
    # assert server_res.response == 20
    ## Check that server alters client values
    server.set_value("/test", 40)
    assert server_res.response == 40
    # assert client_res.response == 40

    thread_client.join()
