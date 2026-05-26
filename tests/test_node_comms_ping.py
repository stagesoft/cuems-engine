# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Tests for the node-side ping/pong handler in NodeCommunications.

The controller broadcasts a cluster liveness ping as
`OperationType.COMMAND, target='ping'`. Each node must reply with
`OperationType.STATUS, target='pong'` carrying its own UUID. The reply
must be cheap and project-independent (works whether or not a project is
loaded), and must NOT route to the regular command callback (which is
reserved for cue lifecycle commands like load/go/stop).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from cuemsengine.comms.NodeCommunications import NodeCommunications
from cuemsengine.comms.NodesHub import ActionType, OperationType, NodeOperation


NODE_UUID = "aaaaaaaa-1111-2222-3333-444444444444"
CONTROLLER_UUID = "bbbbbbbb-1111-2222-3333-444444444444"


@pytest.fixture
def comms(monkeypatch):
    """A NodeCommunications instance with the NNG hub mocked."""
    # NodesHub constructor opens an actual NNG socket; mock it out.
    monkeypatch.setattr(
        "cuemsengine.comms.NodeCommunications.NodesHub",
        MagicMock(),
    )
    obj = NodeCommunications(
        hub_address="tcp://127.0.0.1:0",
        node_id=NODE_UUID,
    )
    # AsyncMock so asyncio.create_task(send_operation(...)) gets a real
    # awaitable, but no orphan coroutines are created when send_operation
    # isn't called.
    obj.nng_hub.send_operation = AsyncMock()
    obj._command_callback = MagicMock()
    return obj


def _ping_op() -> NodeOperation:
    return NodeOperation(
        type=OperationType.COMMAND,
        action=ActionType.UPDATE,
        sender=CONTROLLER_UUID,
        target="ping",
        data={},
    )


def _normal_command_op(name: str) -> NodeOperation:
    return NodeOperation(
        type=OperationType.COMMAND,
        action=ActionType.UPDATE,
        sender=CONTROLLER_UUID,
        target=name,
        data={"value": "foo", "address": f"/engine/command/{name}"},
    )


def test_ping_triggers_pong_with_own_uuid(comms):
    # We're not inside an async context; asyncio.create_task would raise.
    # Run the handler under an event loop so create_task works.
    async def runner():
        comms._handle_command_operation(_ping_op())
        # Let the scheduled task pick up.
        await asyncio.sleep(0)

    asyncio.run(runner())

    assert comms.nng_hub.send_operation.call_count == 1
    sent = comms.nng_hub.send_operation.call_args[0][0]
    assert isinstance(sent, NodeOperation)
    assert sent.type == OperationType.STATUS
    assert sent.action == ActionType.UPDATE
    assert sent.target == "pong"
    assert sent.sender == NODE_UUID


def test_ping_does_not_dispatch_to_command_callback(comms):
    async def runner():
        comms._handle_command_operation(_ping_op())
        await asyncio.sleep(0)

    asyncio.run(runner())

    # The user-facing command callback (load/go/stop dispatcher) must NOT
    # see ping — that would spawn a thread for it.
    comms._command_callback.assert_not_called()


def test_regular_command_still_routes_to_callback(comms):
    comms._handle_command_operation(_normal_command_op("load"))

    # _command_callback is invoked from a worker thread, so we wait briefly.
    import time

    for _ in range(10):
        if comms._command_callback.call_count > 0:
            break
        time.sleep(0.05)

    assert comms._command_callback.call_count == 1
    assert comms.nng_hub.send_operation.call_count == 0  # no pong


def test_non_command_type_returns_early(comms):
    """Status operations should be ignored — wrong direction."""
    status_op = NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=CONTROLLER_UUID,
        target="ping",
        data={},
    )
    comms._handle_command_operation(status_op)
    assert comms.nng_hub.send_operation.call_count == 0
    comms._command_callback.assert_not_called()
