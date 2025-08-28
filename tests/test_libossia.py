from cuemsengine.osc.OssiaServer import OssiaServer
from cuemsengine.osc.OssiaClient import OssiaClient

from pyossia import ValueType

from .fixtures import ossia_client_factory, ossia_server_factory
from pytest import raises

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

def test_client_empty_init(ossia_client_factory):
    with ossia_client_factory() as client:
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

def test_client_endpoint_str(ossia_client_factory):
    with ossia_client_factory(endpoints = "No_endpoint") as client:
        assert len(client.nodes) == 0
        assert len(client.device.root_node.children()) == 0

        try:
            client.set_value("/test", 10)
        except Exception as e:
            assert type(e) == ValueError
            assert str(e) == "Node not found"

def test_client_failed_value(ossia_client_factory):
    with ossia_client_factory(
        endpoints = {"/test1": [ValueType.Int, None, None]}
    ) as client:
        assert len(client.nodes) == 1
        assert "/test1" in client.nodes.keys()
        with raises(ValueError) as e:
            client.set_value("/test1", "no_int")
        assert str(e.value) == "Could not set /test1 to no_int"
        
        client_node = client.get_node("/test1")
        assert client_node.parameter.value == 0
        with raises(ValueError) as e:
            client.set_value(client_node, "no_int")
        assert str(e.value) == "Could not set /test1 to no_int"

        client.remove_node("/test1")
        assert len(client.nodes) == 0
        with raises(KeyError) as e:
            client.get_node("/test1")
        assert str(e.value) == "'/test1'"
        
        with raises(ValueError) as e:
            client.set_value("/test1", 10)
        assert str(e.value) == "Node not found"

        with raises(ValueError) as e:
            client.create_endpoint("/test1", [int, None, None])
        assert str(e.value) == "value_type must be a pyossia.ValueType"

        with raises(ValueError) as e:
            client.create_endpoint("/test1", [ValueType.Int, lambda x, y, z: x+y+z, 10])
        assert str(e.value) == "callback must have 1 or 2 parameters"

def test_client_list_endpoints(ossia_client_factory):
    endpoints = ["/test1", "/test2", "/test3"]
    with ossia_client_factory(
        endpoints = endpoints,
        local_port = 9002
    ) as client:
        assert len(client.nodes) == 3
        assert len(client.device.root_node.children()) == 3

def test_server_empty_init(ossia_server_factory):
    with ossia_server_factory(
        name = "test_server",
        local_port = 9002
    ) as server:
        assert len(server.nodes) == 0
        assert len(server.device.root_node.children()) == 0

def test_server_failed_init(ossia_server_factory):
    def server_callback(server):
        return False
    try:
        with ossia_server_factory(server = server_callback) as server:
            assert False
    except Exception as e:
        assert str(e) == "Server setup failed"

def test_server_init(capfd, ossia_server_factory):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback, 10],
        "/test2": [ValueType.Int, print_callback, 20],
        "/test3": [ValueType.Int, print_callback, 30],
        "/test4": [ValueType.Int, print_callback, 40],
        "/test1/test1": [ValueType.Int, print_callback, 50],
    }
    with ossia_server_factory(
        log = False,
        endpoints = test_endpoints,
        local_port = 9002
    ) as server:
        assert server.started == True
        assert len(server.device.root_node.children()) == 4
        out, err = capfd.readouterr()

    assert "Parameter changed at" in out
    assert len(out) > 0
    assert len(err) == 0
    out_lines = out.split("\n")
    assert out_lines[-1] == ''
    assert len(out_lines) == 6

def test_server_iterate_on_devices(capfd, ossia_server_factory):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback, 10],
        "/test2": [ValueType.Int, print_callback, 20],
        "/test3": [ValueType.Int, print_callback, 30],
        "/test4": [ValueType.Int, print_callback, 40],
        "/test1/test1": [ValueType.Int, print_callback, 50],
    }
    with ossia_server_factory(
        log = False,
        endpoints = test_endpoints,
        local_port = 9002
    ) as server:
        _, _ = capfd.readouterr()
        iterate_on_devices(server.device.root_node)
        out, err = capfd.readouterr()
    assert len(out) > 0
    assert len(err) == 0
    assert "Parameter changed at" not in out
    assert "Parameter info" in out
    assert "No children" in out

def test_client_init(capfd, ossia_client_factory):
    def test_string(n, v):
        return f"Parameter changed at /test{n} to {v} [node value: {v}]"
    
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback],
        "/test2": [ValueType.Int, print_callback, 10],
        "/test3": [ValueType.Int, print_callback, 20],
        "/test4": [ValueType.Int, print_callback, 30]
    }
    with ossia_client_factory(
        endpoints = test_endpoints,
        local_port = 9095
    ) as client:
        assert len(client.device.root_node.children()) == 4
        out, err = capfd.readouterr()

    assert "Parameter changed at" in out
    assert len(out) > 0
    assert len(err) == 0
    out_lines = out.split("\n")
    assert len(out_lines) == 7
    assert out_lines[0] == "Using remote device: <class 'pyossia.ossia_python.OSCDevice'>"
    assert out_lines[1] == "Device bound"
    assert "<pyossia.ossia_python.OSCDevice object at " in out_lines[2]
    assert out_lines[3] == test_string(2, 10)
    assert out_lines[4] == test_string(3, 20)
    assert out_lines[5] == test_string(4, 30)
    assert out_lines[6] == ''

def test_client_iterate_on_devices(capfd, ossia_client_factory):
    test_endpoints = {
        "/test1": [ValueType.Int, print_callback],
        "/test2": [ValueType.Int, print_callback, 10],
        "/test3": [ValueType.Int, print_callback, 20],
        "/test4": [ValueType.Int, print_callback, 30]
    }
    with ossia_client_factory(
        endpoints = test_endpoints,
        local_port = 9996
    ) as client:
        _, _ = capfd.readouterr()
        iterate_on_devices(client.device.root_node)
        out, err = capfd.readouterr()
    assert "Parameter changed at" not in out
    assert "Parameter info" in out
    assert "No children" in out
    assert len(out) > 0
    assert len(err) == 0
    out_lines = out.split("\n")
    assert out_lines[-1] == ''
    assert len(out_lines) == 14

class store_response():
        def __init__(self, response = None):
            self.response = response
        
        def set(self, value):
            self.response = value

def test_osc_client_to_server_transmission():
    # ARRANGE
    from time import sleep
    server_res = store_response()
    server_endpoints = {
        "/test": [ValueType.Int, server_res.set, 30],
    }
    client_res = store_response()
    client_endpoints = {
        "/test": [ValueType.Int, client_res.set, 10],
    }
    LOCAL = 9191
    REMOTE = 9292

    # ACT
    server = OssiaServer(
        endpoints=server_endpoints,
        local_port = LOCAL,
        remote_port = REMOTE
    )
    client = OssiaClient(
        endpoints = client_endpoints,
        local_port = REMOTE,
        remote_port = LOCAL
    )
    
    # ASSERT
    ## Check that the server started with default values
    assert server.started == True
    assert server_res.response == 30
    assert client_res.response == 10
    ## Check that client alters server values
    client.set_value("/test", 20)
    assert client_res.response == 20
    sleep(0.5)
    assert server_res.response == 20
    ## Check that server does not alter client values
    server.set_value("/test", 40)
    assert server_res.response == 40
    assert client_res.response == 20

def test_oscclient_in_separate_process():
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ClientDevices

    client_res = Queue()
    LOCAL = 9094
    REMOTE = 9994

    # Create OssiaClient in separate process
    def run_client(result_queue):
        client = OssiaClient(
            endpoints = {"/test": [ValueType.Int, lambda x: result_queue.put(x), 10]},
            remote_type = ClientDevices.OSC,
            local_port = LOCAL,
            remote_port = REMOTE
        )
        sleep(0.5)  # Allow time for setup
        client.set_value("/test", 80)
        sleep(0.5)  # Allow time for value to be set

    client_process = Process(target=run_client, args=(client_res,))
    client_process.start()

    # ASSERT
    # Wait for the process to complete
    client_process.join(timeout=2)

    # Check if the value was set correctly
    assert not client_res.empty(), "No value was set in the client"
    assert client_res.get() == 10, "Initial value was not set to 10"
    assert client_res.get() == 80, "Modified value was not set to 80"

    # Cleanup
    client_process.terminate()
