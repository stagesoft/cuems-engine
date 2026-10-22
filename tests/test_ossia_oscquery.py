# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""OSCQuery servers and clients across processes and threads.

The three cases that passed out of the old, uncollected ``testdev_ossia_oscquery.py``
(009, FR-048): they exercise a real OSCQuery server and clients, so they are integration tests.
"""

from pyossia import ValueType

from cuemsengine.osc.OssiaClient import OssiaClient
from cuemsengine.osc.OssiaServer import OssiaServer

from .fixtures import ossia_client_factory, ossia_server_factory  # noqa: F401


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
            endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 10]},
            local_port=LOCAL,
            server=ServerDevices.OSCQUERY,
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


def test_oscquery_context_server_in_separate_process(
    ossia_server_factory, process_cleanup
):
    # ARRANGE
    import threading
    from multiprocessing import Process, Queue
    from time import sleep

    from cuemsengine.osc.helpers import ServerDevices

    LOCAL = 9101

    server_res = Queue()
    stop_event = threading.Event()

    # Create OssiaServer in separate process
    def run_server(result_queue, stop_event):
        try:
            with ossia_server_factory(
                name="TestOSCQueryServer",
                endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 10]},
                local_port=LOCAL,
                server=ServerDevices.OSCQUERY,
            ) as server:
                sleep(0.5)  # Allow time for setup
                server.set_value("/test", 80)

                while not stop_event.is_set():
                    sleep(0.1)
        except Exception as e:
            error_type = type(e).__name__
            print(f"Error type: {error_type}")
            result_queue.put(error_type)

    # Start process (register with process_cleanup for automatic cleanup)
    server_process = process_cleanup(
        Process(target=run_server, args=(server_res, stop_event))
    )

    server_process.start()

    # Stop the processes
    stop_event.set()
    server_process.join(timeout=1)

    # ASSERT
    # Check if values were set correctly
    assert not server_res.empty(), "No value was set in the server"
    assert 10 == server_res.get(), "Server initial value was not set to 10"
    assert 80 == server_res.get(), "Server value was not set to 80"

    # Cleanup (handled by process_cleanup, but ensure it's terminated)
    if server_process.is_alive():
        server_process.terminate()


def test_oscquery_server_clients_main_thread():
    # ARRANGE
    from time import sleep

    from cuemsengine.osc.helpers import ClientDevices, ServerDevices
    from cuemsengine.osc.OssiaClient import OssiaClient
    from cuemsengine.osc.OssiaServer import OssiaServer

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
        server=ServerDevices.OSCQUERY,
    )
    server.set_node("/test")
    server.set_parameter(server.get_node("/test"), ValueType.Int, server_callback, 10)

    client1 = OssiaClient(
        host="127.0.0.1",
        local_port=CLIENT_LOCAL,
        remote_port=SERVER_REMOTE,
        remote_type=ClientDevices.OSCQUERY,
    )
    client1.set_node("/test")
    client1.set_parameter(
        client1.get_node("/test"), ValueType.Int, client1_callback, 20
    )

    client2 = OssiaClient(
        host="127.0.0.1",
        local_port=CLIENT_LOCAL + 1,
        remote_port=SERVER_REMOTE,
        remote_type=ClientDevices.OSCQUERY,
    )
    client2.set_node("/test")
    client2.set_parameter(
        client2.get_node("/test"), ValueType.Int, client2_callback, 30
    )

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
