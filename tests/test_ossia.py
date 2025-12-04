from cuemsengine.osc.OssiaServer import OssiaServer
from cuemsengine.osc.OssiaClient import OssiaClient

from pyossia import ValueType

from .fixtures import ossia_client_factory, ossia_server_factory
from pytest import raises

"""Logging testing functions"""
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
        assert len(client.nodes) == 1
        assert [i for i in client.nodes.keys()] == ["/"]
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
        assert len(client.nodes) == 2
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
        assert len(client.nodes) == 1
        assert [i for i in client.nodes.keys()] == ["/"]
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
        assert len(client.nodes) == 4
        assert [i for i in client.nodes.keys()] == ["/", "/test1", "/test2", "/test3"]
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
    assert len(out_lines) == 4
    assert out_lines[0] == test_string(2, 10)
    assert out_lines[1] == test_string(3, 20)
    assert out_lines[2] == test_string(4, 30)
    assert out_lines[3] == ''

class store_response():
        def __init__(self):
            self.response = []
        
        def set(self, value):
            self.response.append(value)

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
    LOCAL_PORT = 9191
    COMMON_PORT = 9292

    # ACT
    server = OssiaServer(
        endpoints=server_endpoints,
        remote_port = COMMON_PORT
    )
    sleep(0.5)
    client = OssiaClient(
        endpoints = client_endpoints,
        remote_port = COMMON_PORT,
        local_port = LOCAL_PORT
    )
    sleep(0.5)
    # ASSERT
    ## Check that the server started with default values
    assert server.started == True
    assert client_res.response[0] == 10
    assert server_res.response[0] == 30
    # assert server_res.response[1] == 10
    ## Check that client alters server values
    client.set_value("/test", 20)
    assert client_res.response[1] == 20
    sleep(0.5)
    # assert server_res.response[2] == 20
    ## Check that server does not alter client values
    server.set_value("/test", 40)
    sleep(0.5)
    assert server_res.response[1] == 40
    assert len(client_res.response) == 2

def test_oscclient_in_separate_process(process_cleanup):
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

    client_process = process_cleanup(Process(target=run_client, args=(client_res,)))
    client_process.start()

    # ASSERT
    # Wait for the process to complete
    client_process.join(timeout=2)

    # Check if the value was set correctly
    assert not client_res.empty(), "No value was set in the client"
    assert client_res.get() == 10, "Initial value was not set to 10"
    assert client_res.get() == 80, "Modified value was not set to 80"

    # Cleanup (handled by process_cleanup, but ensure it's terminated)
    if client_process.is_alive():
        client_process.terminate()

def test_server_node_removal_affects_children():
    # ARRANGE
    from cuemsengine.osc.OssiaServer import OssiaServer
    from cuemsengine.osc.helpers import ServerDevices
    from time import sleep

    server = OssiaServer(
        endpoints = {
            "/test": [ValueType.Int, print_callback, 10],
            "/test/test1": [ValueType.Int, print_callback, 20],
            "/test/test2": [ValueType.Int, print_callback, 30],
        },
        local_port = 9002
    )
    sleep(0.5)
    assert len(server.device.root_node.children()) == 1
    test_node = server.get_node("/test")
    assert len(test_node.children()) == 2
    server.device.root_node.remove_child("test")
    assert len(server.device.root_node.children()) == 0

def test_server_node_removal_affects_all_children():
    # ARRANGE
    from cuemsengine.osc.OssiaServer import OssiaServer
    from cuemsengine.osc.helpers import ServerDevices
    from time import sleep

    server = OssiaServer(
        endpoints = {
            "/test1": [ValueType.Int, print_callback, 20],
            "/testout": [ValueType.Int, print_callback, 20],
            "/test1/test22": [ValueType.Int, print_callback, 30],
            "/test1/test2/test3": [ValueType.Int, print_callback, 30],
            "/test1/test2/test3/test4": [ValueType.Int, print_callback, 30],
        },
        local_port = 9002
    )
    sleep(0.5)
    assert len(server.device.root_node.children()) == 2
    test_node = server.get_node("/test1")
    assert len(test_node.children()) == 2
    server.device.root_node.remove_child("/test1/test2")
    assert len(test_node.children()) == 1
    assert len(server.device.root_node.children()) == 2

    test_node = server.get_node("/test1/test22")
    assert len(test_node.children()) == 0
    
    server.remove_node("/test1")
    assert len(server.device.root_node.children()) == 1
