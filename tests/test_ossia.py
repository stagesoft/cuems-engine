# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

from pyossia import ValueType
from pytest import approx, raises

from cuemsengine.osc.OssiaClient import OssiaClient
from cuemsengine.osc.OssiaServer import OssiaServer
from cuemsengine.tools.PortHandler import PORT_HANDLER

from .fixtures import _ossia_release, ossia_client_factory, ossia_server_factory

"""Logging testing functions"""


def print_callback(node, value):
    print(
        f"Parameter changed at {node} to {value} [node value:"
        f"{node.parameter.value}]"
    )


def test_client_empty_init(ossia_client_factory):
    with ossia_client_factory() as client:
        # Keep the live OSCDevice so fixture cleanup can release the port;
        # only swap .device for the AttributeError checks.
        real_device = client.device
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
        finally:
            client.device = real_device


def test_client_endpoint_str(ossia_client_factory):
    # String endpoints are ignored by create_endpoints (dict|list only).
    # Root "/" is intentionally omitted from nodes_from_device.
    with ossia_client_factory(endpoints="No_endpoint") as client:
        assert len(client.nodes) == 0
        assert len(client.device.root_node.children()) == 0

        try:
            client.set_value("/test", 10)
        except Exception as e:
            assert type(e) == ValueError
            assert str(e) == "Node not found"


def test_client_failed_value(ossia_client_factory):
    with ossia_client_factory(
        endpoints={"/test1": [ValueType.Int, None, None]}
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
            client.create_endpoint(
                "/test1", [ValueType.Int, lambda x, y, z: x + y + z, 10]
            )
        assert str(e.value) == "callback must have 1 or 2 parameters"


def test_client_list_endpoints(ossia_client_factory):
    endpoints = ["/test1", "/test2", "/test3"]
    with ossia_client_factory(endpoints=endpoints) as client:
        assert len(client.nodes) == 3
        assert [i for i in client.nodes.keys()] == [
            "/test1",
            "/test2",
            "/test3",
        ]
        assert len(client.device.root_node.children()) == 3


def test_get_value_if_set_returns_none_when_never_set(ossia_client_factory):
    """A freshly-created endpoint has never had set_value() called on it —
    get_value_if_set() must return None, not pyossia's raw type-default
    (get_value() alone would return 0 here, indistinguishable from an
    explicit set_value(path, 0))."""
    with ossia_client_factory(
        endpoints={"/test1": [ValueType.Float, None, None]}
    ) as client:
        assert client.get_value_if_set("/test1") is None


def test_get_value_if_set_returns_value_after_set_value(ossia_client_factory):
    with ossia_client_factory(
        endpoints={"/test1": [ValueType.Float, None, None]}
    ) as client:
        client.set_value("/test1", 0.42)
        assert client.get_value_if_set("/test1") == approx(0.42)


def test_get_value_if_set_distinguishes_explicit_zero_from_unset(
    ossia_client_factory,
):
    """The whole point of this method: an explicit set_value(path, 0.0)
    must be reported as set (0.0), not conflated with "never set" (None)."""
    with ossia_client_factory(
        endpoints={"/test1": [ValueType.Float, None, None]}
    ) as client:
        assert client.get_value_if_set("/test1") is None
        client.set_value("/test1", 0.0)
        assert client.get_value_if_set("/test1") == 0.0
        assert client.get_value_if_set("/test1") is not None


def test_record_value_returned_by_get_value_if_set(ossia_client_factory):
    """record_value() stores engine-side without an OSC push — the value an
    external actor (gradient-motiond) is driving the player to must be
    reported by get_value_if_set() even though nothing was pushed."""
    with ossia_client_factory(
        endpoints={"/test1": [ValueType.Float, None, None]}
    ) as client:
        assert client.get_value_if_set("/test1") is None
        client.record_value("/test1", 0.4)
        assert client.get_value_if_set("/test1") == approx(0.4)


def test_record_value_wins_over_pushed_value(ossia_client_factory):
    """A recorded value is fresher than the last real push (the fade moved
    the player after that push) — it must win until the next real push."""
    with ossia_client_factory(
        endpoints={"/test1": [ValueType.Float, None, None]}
    ) as client:
        client.set_value("/test1", 1.0)
        client.record_value("/test1", 0.0)
        assert client.get_value_if_set("/test1") == 0.0


def test_set_value_supersedes_recorded_value(ossia_client_factory):
    """A later real set_value() push is the freshest truth — it must pop the
    recorded value so get_value_if_set() reads the parameter again."""
    with ossia_client_factory(
        endpoints={"/test1": [ValueType.Float, None, None]}
    ) as client:
        client.record_value("/test1", 0.0)
        client.set_value("/test1", 0.66)
        assert client.get_value_if_set("/test1") == approx(0.66)


def test_server_empty_init(ossia_server_factory):
    with ossia_server_factory(name="test_server") as server:
        assert len(server.nodes) == 0
        assert len(server.device.root_node.children()) == 0


def test_server_failed_init(ossia_server_factory):
    def server_callback(server):
        return False

    try:
        with ossia_server_factory(server=server_callback) as server:
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
    with ossia_server_factory(log=False, endpoints=test_endpoints) as server:
        assert server.started == True
        assert len(server.device.root_node.children()) == 4
        out, err = capfd.readouterr()

    param_lines = [
        ln for ln in out.splitlines() if ln.startswith("Parameter changed at")
    ]
    assert len(param_lines) == 5
    assert all("Parameter changed at" in ln for ln in param_lines)


def test_client_init(capfd, ossia_client_factory):
    def test_string(n, v):
        return f"Parameter changed at /test{n} to {v} [node value:{v}]"

    test_endpoints = {
        "/test1": [ValueType.Int, print_callback],
        "/test2": [ValueType.Int, print_callback, 10],
        "/test3": [ValueType.Int, print_callback, 20],
        "/test4": [ValueType.Int, print_callback, 30],
    }
    with ossia_client_factory(endpoints=test_endpoints) as client:
        assert len(client.device.root_node.children()) == 4
        out, err = capfd.readouterr()

    param_lines = [
        ln for ln in out.splitlines() if ln.startswith("Parameter changed at")
    ]
    assert len(param_lines) == 3
    assert param_lines[0] == test_string(2, 10)
    assert param_lines[1] == test_string(3, 20)
    assert param_lines[2] == test_string(4, 30)


class store_response:
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
    # Shared remote (outbound only); distinct listen ports. Matches prior
    # working layout — crossed local/remote duplex aborts inside libossia.
    local_port = PORT_HANDLER.new_random_port()
    common_port = PORT_HANDLER.new_random_port()
    server_local = PORT_HANDLER.new_random_port()

    # ACT
    server = OssiaServer(
        endpoints=server_endpoints,
        local_port=server_local,
        remote_port=common_port,
    )
    sleep(0.5)
    client = OssiaClient(
        endpoints=client_endpoints,
        remote_port=common_port,
        local_port=local_port,
    )
    sleep(0.5)
    try:
        # ASSERT
        ## Check that the server started with default values
        assert server.started == True
        assert client_res.response[0] == 10
        assert server_res.response[0] == 30
        ## Check that client alters server values
        client.set_value("/test", 20)
        assert client_res.response[1] == 20
        sleep(0.5)
        ## Check that server does not alter client values
        server.set_value("/test", 40)
        sleep(0.5)
        assert server_res.response[1] == 40
        assert len(client_res.response) == 2
    finally:
        _ossia_release(client)
        _ossia_release(server)


def test_oscclient_in_separate_process(process_cleanup):
    # ARRANGE
    from multiprocessing import Process, Queue
    from time import sleep

    from cuemsengine.osc.helpers import ClientDevices

    client_res = Queue()
    LOCAL = PORT_HANDLER.new_random_port()
    REMOTE = PORT_HANDLER.new_random_port()

    # Create OssiaClient in separate process
    def run_client(result_queue):
        client = OssiaClient(
            endpoints={"/test": [ValueType.Int, lambda x: result_queue.put(x), 10]},
            remote_type=ClientDevices.OSC,
            local_port=LOCAL,
            remote_port=REMOTE,
        )
        sleep(0.5)  # Allow time for setup
        client.set_value("/test", 80)
        sleep(0.5)  # Allow time for value to be set
        _ossia_release(client)

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

    PORT_HANDLER.remove_random_port(LOCAL)
    PORT_HANDLER.remove_random_port(REMOTE)


def test_server_node_removal_affects_children():
    # ARRANGE
    from time import sleep

    server = OssiaServer(
        endpoints={
            "/test": [ValueType.Int, print_callback, 10],
            "/test/test1": [ValueType.Int, print_callback, 20],
            "/test/test2": [ValueType.Int, print_callback, 30],
        },
        local_port=PORT_HANDLER.new_random_port(),
        remote_port=PORT_HANDLER.new_random_port(),
    )
    try:
        sleep(0.5)
        assert len(server.device.root_node.children()) == 1
        test_node = server.get_node("/test")
        assert len(test_node.children()) == 2
        server.device.root_node.remove_child("test")
        assert len(server.device.root_node.children()) == 0
    finally:
        _ossia_release(server)


def test_server_node_removal_affects_all_children():
    # ARRANGE
    from time import sleep

    server = OssiaServer(
        endpoints={
            "/test1": [ValueType.Int, print_callback, 20],
            "/testout": [ValueType.Int, print_callback, 20],
            "/test1/test22": [ValueType.Int, print_callback, 30],
            "/test1/test2/test3": [ValueType.Int, print_callback, 30],
            "/test1/test2/test3/test4": [ValueType.Int, print_callback, 30],
        },
        local_port=PORT_HANDLER.new_random_port(),
        remote_port=PORT_HANDLER.new_random_port(),
    )
    try:
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
    finally:
        _ossia_release(server)


def test_remove_device_tolerates_incomplete_init():
    """__del__/remove_device must not raise when __init__ was skipped.

    MixerClient tests patch PlayerClient.__init__, leaving no ``nodes``;
    an unguarded destructor surfaces as PytestUnraisableExceptionWarning.
    """
    from cuemsengine.osc.OssiaNodes import OssiaNodes

    incomplete = OssiaNodes.__new__(OssiaNodes)
    incomplete.remove_device()  # must not raise
    assert getattr(incomplete, "nodes", None) in (None, {})
    assert getattr(incomplete, "device", None) is None
