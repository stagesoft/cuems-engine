# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
"""The engine notices when its bus or its editor listener stops (cuems-utils H1, C8).

Real comms threads over a real NNG bus. Before cuems-utils 0.1.1's AsyncCommsThread, the
engine waited for *all* of its comms tasks, so a bus hub whose socket had closed left
the engine running with no bus: a controller reached no node, a node heard no
controller, and nothing but one log line said so. The thread now ends, and the engine is
signalled to stop (`terminate_process`, recorded here instead of sent, by the autouse
fixture in tests/conftest.py).
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pynng

from cuemsengine.comms.ControllerCommunications import ControllerCommunications
from cuemsengine.comms.NodeCommunications import NodeCommunications
from cuemsengine.comms.NodesHub import OperationType


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _controller(address, editor):
    with patch(
        "cuemsengine.comms.ControllerCommunications.Communicator", return_value=editor
    ):
        return ControllerCommunications(
            address,
            editor_callback=MagicMock(),
            node_operation_callback={OperationType.PLAYER: MagicMock()},
            websocket_osc_config={"port": 0},
        )


def _idle_editor():
    editor = MagicMock()
    editor.responder_connect = AsyncMock()

    async def wait_forever(callback):
        import asyncio

        await asyncio.Event().wait()

    editor.responder_get_request = wait_forever
    return editor


def test_a_closed_controller_bus_ends_the_comms_and_signals_the_engine(terminated):
    controller = _controller("tcp://127.0.0.1:15571", _idle_editor())
    controller.start()
    try:
        assert _wait_for(lambda: controller.nng_hub.connection is not None)
        controller.nng_hub.connection.close()
        assert controller.ended.wait(
            5
        ), "a closed bus left the controller's comms running"
    finally:
        controller.stop(timeout=5)
    assert controller.end_reason == "essential task NngBusHub.start ended"
    assert terminated == [controller]


def test_a_closed_node_bus_ends_the_comms_and_signals_the_engine(terminated):
    node = NodeCommunications("tcp://127.0.0.1:15572", node_id="test-node")
    node.start()
    try:
        assert _wait_for(lambda: node.nng_hub.connection is not None)
        node.nng_hub.connection.close()
        assert node.ended.wait(5), "a closed bus left the node's comms running"
    finally:
        node.stop(timeout=5)
    assert terminated == [node]


def test_a_failing_editor_listener_ends_the_controller_comms(terminated):
    editor = _idle_editor()

    async def closed(callback):
        raise pynng.Closed("Object closed", 7)

    editor.responder_get_request = closed
    controller = _controller("tcp://127.0.0.1:15573", editor)
    controller.start()
    try:
        assert controller.ended.wait(
            5
        ), "a failed editor listener left the controller running"
    finally:
        controller.stop(timeout=5)
    assert isinstance(controller.end_reason, pynng.Closed)
    assert terminated == [controller]


def test_an_operator_stop_does_not_signal_the_engine(terminated):
    controller = _controller("tcp://127.0.0.1:15574", _idle_editor())
    controller.start()
    assert _wait_for(lambda: controller.nng_hub.connection is not None)
    controller.stop(timeout=5)
    assert not controller.is_alive()
    assert controller.end_reason is None
    assert terminated == []
