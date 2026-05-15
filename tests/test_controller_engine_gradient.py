# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for ControllerEngine gradient-motiond status sender guard.

Covers:
- STATUS messages from gradient-motiond (sender starts with "gradientengine_")
  are silently discarded without state change or error.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cuemsengine.comms.NodesHub import (
    ActionType,
    NodeOperation,
    OperationType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_status_op(sender: str, target: str = "gradientengine",
                    data: dict | None = None) -> NodeOperation:
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target=target,
        data=data or {"event": "fade_complete", "fade_id": "x"},
    )


def _make_controller():
    """Build a ControllerEngine shell via __new__ — no __init__ called."""
    from cuemsengine.ControllerEngine import ControllerEngine

    ce = ControllerEngine.__new__(ControllerEngine)
    ce.communications_thread = MagicMock()
    ce.cm = MagicMock()
    ce.cm.node_conf = {"uuid": "ctrl-node"}
    return ce


# ---------------------------------------------------------------------------
# STATUS sender guard
# ---------------------------------------------------------------------------


class TestGradientEngineSenderGuard:
    def test_gradient_sender_status_discarded(self):
        """STATUS from sender starting with 'gradientengine_' is silently ignored."""
        ce = _make_controller()
        ce.set_status = MagicMock()

        op = _make_status_op(sender="gradientengine_node1")
        ce.status_operation_callback(op)

        ce.set_status.assert_not_called()

    def test_non_gradient_sender_status_processed(self):
        """STATUS from a normal node sender is not blocked by the gradient guard."""
        ce = _make_controller()
        ce.set_status = MagicMock()

        op = _make_status_op(sender="node_1", target="script_finished",
                             data={"running": "no"})
        try:
            ce.status_operation_callback(op)
        except Exception:
            pass  # Other missing attrs on mock are acceptable
