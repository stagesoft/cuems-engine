from cuemsengine.osc.OssiaServer import OssiaServer
from cuemsengine.osc.OssiaClient import OssiaClient

from pyossia import ValueType

from .fixtures import ossia_client_factory, ossia_server_factory
from .helpers import timeout
from pytest import raises

def test_oscquery_server_in_separate_process(process_cleanup):
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ServerDevices

    LOCAL = 9102
    
    server_res = Queue()

    # Create OssiaServer in separate process
    def run_server(result_queue):
        server = OssiaServer(
            name="TestOSCQueryServer",
            endpoints={
                "/test": [
                    ValueType.Int,
                    lambda x: result_queue.put(x),
                    10
                ]
            },
            local_port=LOCAL,
            server=ServerDevices.OSCQUERY
        )
        server.set_value("/test", 80)

    server_process = process_cleanup(Process(target=run_server, args=(server_res,)))
    server_process.start()

    # ASSERT
    # Wait for the process to complete
    server_process.join(timeout=2)

    # Check if the value was set correctly
    assert not server_res.empty(), "No value was set in the server"
    assert server_res.get() == 10, "Initial value was not set to 10"
    assert server_res.get() == 80, "Modified value was not set to 80"

    # Cleanup - now handled automatically by process_cleanup fixture
    server_process.terminate()


def test_oscquery_context_server_in_separate_process(ossia_server_factory):
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ServerDevices
    import threading

    LOCAL = 9101
    
    server_res = Queue()
    stop_event = threading.Event()

    # Create OssiaServer in separate process
    def run_server(result_queue, stop_event):
        try:
            with ossia_server_factory(
                name="TestOSCQueryServer",
                endpoints={
                    "/test": [
                        ValueType.Int,
                        lambda x: result_queue.put(x),
                        10
                    ]
                },
                local_port=LOCAL,
                server=ServerDevices.OSCQUERY
            ) as server:
                sleep(0.5)  # Allow time for setup
                server.set_value("/test", 80)

                while not stop_event.is_set():
                    sleep(0.1)
        except Exception as e:
            error_type = type(e).__name__
            print(f"Error type: {error_type}")
            result_queue.put(error_type)

    # Start both processes
    server_process = Process(target=run_server, args=(server_res, stop_event))

    server_process.start()

    # Stop the processes
    stop_event.set()
    server_process.join(timeout=1)

    # ASSERT
    # Check if values were set correctly
    assert not server_res.empty(), "No value was set in the server"
    assert 10 == server_res.get(), "Server initial value was not set to 10"
    assert 80 == server_res.get(), "Server value was not set to 80"

    # Cleanup
    server_process.terminate()

def test_oscquery_context_client_fails_alone(ossia_client_factory, capfd):
    # ARRANGE
    from cuemsengine.osc.helpers import ClientDevices
    from time import sleep
    
    LOCAL = 9097
    error_type = None

    client_res = []

    # Create OssiaClient in separate within a timeout context manager
    try:
        with timeout(2):
            with ossia_client_factory(
                endpoints={
                    "/test": [
                        ValueType.Int,
                        lambda x: client_res.append(x),
                        20
                    ]
                },
                local_port=LOCAL,
                remote_type=ClientDevices.OSCQUERY
            ) as client:
                initial_value = client_res[0]
                try:
                    client.set_value("/test", 40)
                except Exception as e:
                    error_type = type(e).__name__
    except TimeoutError:
        assert False, "Timeout reached"

    # out, err = capfd.readouterr()
    # err_split = err.split("\n")[-1]
    # for line in err_split:
    #     assert line.split(" ")[4:] == [
    #         "HTTP", "Error:", "Connection", "refused"
    #     ], "Error missing in client"
    # assert "Using remote device" in out, "Device bound"
    # assert initial_value == 20, "Initial client value was not set"
    # if error_type:
    #     assert error_type == "ValueError", "Error type was not ValueError"
    # else:
    #     assert client_res[1] == 40, "Client value was not set"

def test_oscquery_client_and_server_in_separate_processes(ossia_client_factory, ossia_server_factory, capfd):
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ServerDevices, ClientDevices
    import threading

    server_res = Queue()
    client_res = Queue()
    stop_event = threading.Event()
    SERVER_LOCAL = 9296
    SERVER_REMOTE = 9396
    CLIENT_LOCAL = 9297

    # Create OssiaServer in separate process
    def run_server(result_queue, stop_event):
        with ossia_server_factory(
            name="TestOSCQueryServer",
            endpoints={
                "/test": [
                    ValueType.Int,
                    lambda x: result_queue.put(x),
                    10
                ]
            },
            local_port=SERVER_LOCAL,
            remote_port=SERVER_REMOTE,
            server=ServerDevices.OSCQUERY
        ) as server:
            srv_out, srv_err = capfd.readouterr()
            print(f"Server output: {srv_out}")
            print(f"Server error: {srv_err}")
            server.set_value("/test", 80)
            while not stop_event.is_set():
                sleep(0.1)

    # Create OssiaClient in separate process  
    def run_client(result_queue, stop_event):
        with ossia_client_factory(
            endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 20]},
            remote_type=ClientDevices.OSCQUERY,
            local_port=CLIENT_LOCAL,
            remote_port=SERVER_REMOTE
        ) as client:
            client.set_value("/test", 40)
            while not stop_event.is_set():
                sleep(0.1)

    # Start both processes
    server_process = Process(target=run_server, args=(server_res, stop_event))
    client_process = Process(target=run_client, args=(client_res, stop_event))

    server_process.start()
    sleep(3)
    client_process.start()
    print("Server started")

    # Stop the processes
    stop_event.set()
    server_process.join(timeout=1)
    server_process.terminate()
    client_process.join(timeout=1)
    client_process.terminate()

    # ASSERT
    # Check if values were set correctly
    assert not server_res.empty(), "No value was set in the server"
    assert not client_res.empty(), "No value was set in the client"

    assert 10 == server_res.get(), "Server initial value was not set to 10"
    assert 80 == server_res.get(), "Server value was not set to 80"
    assert 20 == server_res.get(), "Server did not receive client's value 20"
    assert 40 == server_res.get(), "Server did not receive client's value 40"

def test_oscquery_multiple_clients_in_separate_processes():
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep
    from cuemsengine.osc.helpers import ServerDevices, ClientDevices
    from threading import Event

    SERVER_LOCAL = 9798
    SERVER_REMOTE = 9898
    CLIENT_LOCAL = 9799
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
    
    SERVER_LOCAL = 9296
    SERVER_REMOTE = 9396
    CLIENT_LOCAL = 9297
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
