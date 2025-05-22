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
    LOCAL = 9791
    REMOTE = 9991

    # ACT
    server = OssiaServer(
        endpoints=server_endpoints,
        local_port = LOCAL,
        remote_port = REMOTE
    )
    client = OssiaClient(
        endpoints = client_endpoints,
        local_port = LOCAL + 1,
        remote_port = REMOTE
    )
    
    # ASSERT
    ## Check that the server started with default values
    assert server.started == True
    assert server_res.response == 30
    assert client_res.response == 10
    ## Check that client does not alter server values
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

def test_oscqueryserver_in_separate_process():
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ServerDevices

    server_res = Queue()
    LOCAL_PORT = 9095
    REMOTE_PORT = 9995

    # Create OssiaServer in separate process
    def run_server(result_queue):
        server = OssiaServer(
            name="TestOSCQueryServer",
            endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 10]},
            server=ServerDevices.OSCQUERY,
            local_port=LOCAL_PORT,
            remote_port=REMOTE_PORT
        )
        sleep(0.5)  # Allow time for setup
        server.set_value("/test", 80)
        sleep(0.5)  # Allow time for value to be set

    server_process = Process(target=run_server, args=(server_res,))
    server_process.start()

    # ASSERT
    # Wait for the process to complete
    server_process.join(timeout=2)

    # Check if the value was set correctly
    assert not server_res.empty(), "No value was set in the server"
    assert server_res.get() == 10, "Initial value was not set to 10"
    assert server_res.get() == 80, "Modified value was not set to 80"

    # Cleanup
    server_process.terminate()

def test_oscclient_and_server_in_separate_processes():
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ServerDevices, ClientDevices
    import threading

    server_res = Queue()
    client_res = Queue()
    SERVER_LOCAL = 9096
    SERVER_REMOTE = 9996
    CLIENT_LOCAL = 9097

    stop_event = threading.Event()

    # Create OssiaServer in separate process
    def run_server(result_queue, stop_event):
        server = OssiaServer(
            name="TestOSCQueryServer",
            endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 10]},
            server=ServerDevices.OSCQUERY,
            local_port=SERVER_LOCAL,
            remote_port=SERVER_REMOTE
        )
        sleep(1)  # Allow time for setup and client connection
        server.set_value("/test", 80)
        while not stop_event.is_set():
            sleep(0.1)

    # Create OssiaClient in separate process  
    def run_client(result_queue, stop_event):
        client = OssiaClient(
            endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 20]},
            remote_type=ClientDevices.OSCQUERY,
            local_port=CLIENT_LOCAL,
            remote_port=SERVER_REMOTE
        )
        sleep(1.5)  # Allow time for server to set value
        client.set_value("/test", 40)
        while not stop_event.is_set():
            sleep(0.1)

    # Start both processes
    server_process = Process(target=run_server, args=(server_res, stop_event))
    client_process = Process(target=run_client, args=(client_res, stop_event))
    
    server_process.start()
    sleep(0.5)  # Allow server to start before client
    client_process.start()

    # Allow processes to run for a short time
    sleep(3)

    # Stop the processes
    stop_event.set()
    server_process.join(timeout=1)
    client_process.join(timeout=1)

    # ASSERT
    # Check if values were set correctly
    assert not server_res.empty(), "No value was set in the server"
    assert not client_res.empty(), "No value was set in the client"

    assert 10 == server_res.get(), "Server initial value was not set to 10"
    assert 20 == server_res.get(), "Server initial value was not set to 10"
    assert 80 == server_res.get(), "Server value was not set to 80"
    assert 40 == server_res.get(), "Server did not receive client's value 40"
    
    assert 20 == client_res.get(), "Client initial value was not set to 20"
    assert 80 == client_res.get(), "Client did not receive server's value 80"
    assert 40 == client_res.get(), "Client value was not set to 40"

    # Cleanup
    server_process.terminate()
    client_process.terminate()

def test_oscquery_multiple_clients_in_separate_processes():
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ServerDevices, ClientDevices
    from threading import Event

    SERVER_LOCAL = 9096
    SERVER_REMOTE = 9996
    CLIENT_LOCAL = 9097
    server_res = Queue()
    client1_res = Queue()
    client2_res = Queue()
    stop_event = Event()

    # Create OssiaServer in separate process
    def run_server(result_queue, stop_event):
        server = OssiaServer(
            endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 10]},
            server=ServerDevices.OSCQUERY,
            local_port=SERVER_LOCAL,
            remote_port=SERVER_REMOTE
        )
        sleep(1)
        server.set_value("/test", 80)
        while not stop_event.is_set():
            sleep(0.1)

    # Create two OssiaClients in separate process
    def run_clients(result_queue1, result_queue2, stop_event):
        client1 = OssiaClient(
            endpoints={"/test": [ValueType.Int, lambda x: result_queue1.put(x), 20]},
            remote_type=ClientDevices.OSCQUERY,
            local_port=CLIENT_LOCAL,
            remote_port=SERVER_REMOTE
        )
        
        client2 = OssiaClient(
            endpoints={"/test": [ValueType.Int, lambda x: result_queue2.put(x), 30]},
            remote_type=ClientDevices.OSCQUERY,
            local_port=CLIENT_LOCAL + 1,
            remote_port=SERVER_REMOTE
        )
        
        sleep(1.5)  # Allow time for server to set value
        client1.set_value("/test", 40)
        sleep(0.5)
        client2.set_value("/test", 50)
        
        while not stop_event.is_set():
            sleep(0.1)

    # Start processes
    server_process = Process(target=run_server, args=(server_res, stop_event))
    clients_process = Process(target=run_clients, args=(client1_res, client2_res, stop_event))
    
    server_process.start()
    sleep(0.5)  # Allow server to start before clients
    clients_process.start()

    # Allow processes to run for a short time
    sleep(4)

    # Stop the processes
    stop_event.set()
    server_process.join(timeout=1)
    clients_process.join(timeout=1)

    # ASSERT
    # Check if values were set correctly
    assert not server_res.empty(), "No value was set in the server"
    assert not client1_res.empty(), "No value was set in client1"
    assert not client2_res.empty(), "No value was set in client2"

    assert 10 == server_res.get(), "Server initial value was not set to 10"
    assert 20 == server_res.get(), "Server did not receive client1's initial value"
    assert 30 == server_res.get(), "Server did not receive client2's initial value"
    assert 80 == server_res.get(), "Server value was not set to 80"
    assert 40 == server_res.get(), "Server did not receive client1's value 40"
    assert 50 == server_res.get(), "Server did not receive client2's value 50"
    
    assert 20 == client1_res.get(), "Client1 initial value was not set to 20"
    assert 80 == client1_res.get(), "Client1 did not receive server's value 80"
    assert 40 == client1_res.get(), "Client1 value was not set to 40"

    assert 30 == client2_res.get(), "Client2 initial value was not set to 30"
    assert 80 == client2_res.get(), "Client2 did not receive server's value 80"
    assert 50 == client2_res.get(), "Client2 value was not set to 50"

    # Cleanup
    server_process.terminate()
    clients_process.terminate()

def test_oscquery_server_clients_main_thread():
    # ARRANGE
    from cuemsengine.osc.OssiaServer import OssiaServer
    from cuemsengine.osc.OssiaClient import OssiaClient
    from cuemsengine.osc.helpers import ServerDevices, ClientDevices
    from time import sleep
    
    SERVER_LOCAL = 9096
    SERVER_REMOTE = 9996
    CLIENT_LOCAL = 9097
    server_res = []
    client1_res = []
    client2_res = []

    def server_callback(value):
        server_res.append(value)

    def client1_callback(value):
        client1_res.append(value)

    def client2_callback(value):
        client2_res.append(value)

    sleep(0.5)

    # ACT
    # Create server and clients
    server = OssiaServer(
        name="test_server",
        host="127.0.0.1",
        local_port=SERVER_LOCAL,
        remote_port=SERVER_REMOTE,
        server=ServerDevices.OSCQUERY
    )
    server.set_node("/test")
    server.set_parameter(server.get_node("/test"), ValueType.Int, server_callback, 10)

    client1 = OssiaClient(
        host="127.0.0.1",
        local_port=CLIENT_LOCAL,
        remote_port=SERVER_REMOTE,
        remote_type=ClientDevices.OSCQUERY
    )
    client1.set_node("/test")
    client1.set_parameter(client1.get_node("/test"), ValueType.Int, client1_callback, 20)

    client2 = OssiaClient(
        host="127.0.0.1",
        local_port=CLIENT_LOCAL + 1,
        remote_port=SERVER_REMOTE,
        remote_type=ClientDevices.OSCQUERY
    )
    client2.set_node("/test")
    client2.set_parameter(client2.get_node("/test"), ValueType.Int, client2_callback, 30)

    # Allow time for initial values to propagate
    sleep(0.5)

    # Server sets new value
    server.set_value("/test", 80)
    sleep(0.15)  # Allow time for server to set value
    
    client1.set_value("/test", 40)
    sleep(0.05)
    client2.set_value("/test", 50)
    sleep(0.05)

    # ASSERT
    # Check if values were set correctly
    assert len(server_res) > 0, "No value was set in the server"
    assert len(client1_res) > 0, "No value was set in client1"
    assert len(client2_res) > 0, "No value was set in client2"

    assert 10 == server_res[0], "Server initial value was not set to 10"
    assert 20 == server_res[1], "Server did not receive client1's initial value"
    assert 30 == server_res[2], "Server did not receive client2's initial value"
    assert 80 == server_res[3], "Server value was not set to 80"
    assert 40 == server_res[4], "Server did not receive client1's value 40"
    assert 50 == server_res[5], "Server did not receive client2's value 50"
    
    assert 20 == client1_res[0], "Client1 initial value was not set to 20"
    assert 80 == client1_res[1], "Client1 did not receive server's value 80"
    assert 40 == client1_res[2], "Client1 value was not set to 40"

    assert 30 == client2_res[0], "Client2 initial value was not set to 30"
    assert 80 == client2_res[1], "Client2 did not receive server's value 80"
    assert 50 == client2_res[2], "Client2 value was not set to 50"
