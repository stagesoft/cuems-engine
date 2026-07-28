# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Tests for NodeCommunications.update_mixer_status (869cwpkz4).

The node reports an authoritative audio-mixer gain snapshot to the controller
as `OperationType.STATUS, target='audiomixer_status'`, carrying its own UUID as
sender so the controller can key mixer_status by node. Sent on settle events
(mixer startup / after reset_volumes), never per UI write.
"""

from unittest.mock import MagicMock

import pytest

from cuemsengine.comms.NodeCommunications import NodeCommunications
from cuemsengine.comms.NodesHub import ActionType, NodeOperation, OperationType

NODE_UUID = "aaaaaaaa-1111-2222-3333-444444444444"


@pytest.fixture
def comms(monkeypatch):
    """A NodeCommunications instance with the NNG hub mocked."""
    monkeypatch.setattr(
        "cuemsengine.comms.NodeCommunications.NodesHub",
        MagicMock(),
    )
    obj = NodeCommunications(hub_address="tcp://127.0.0.1:0", node_id=NODE_UUID)
    # Stub the thread-safe send so we assert on the op it builds.
    obj.send_operation = MagicMock()
    return obj


def test_update_mixer_status_builds_status_op(comms):
    entries = {"master": 1.0, "0": 0.5, "1": 0.25}
    comms.update_mixer_status(entries, output_index="0", timeout=0.1)

    comms.send_operation.assert_called_once()
    op = comms.send_operation.call_args[0][0]
    assert isinstance(op, NodeOperation)
    assert op.type == OperationType.STATUS
    assert op.action == ActionType.UPDATE
    assert op.target == "audiomixer_status"
    assert op.sender == NODE_UUID
    assert op.data == {"output_index": "0", "entries": entries}


def test_update_mixer_status_defaults_output_index(comms):
    comms.update_mixer_status({"master": 1.0})
    op = comms.send_operation.call_args[0][0]
    assert op.data["output_index"] == "0"
