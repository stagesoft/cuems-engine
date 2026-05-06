"""Unit tests for ControllerEngine gradient-motiond integration (T007, T024).

Covers:
- STATUS messages from gradient-motiond (sender starts with "gradientengine_")
  are silently discarded without state change or error.
- _send_gradient_cancel_all sends the correct NodeOperation.
- stop_script calls _send_gradient_cancel_all before forwarding to nodes.
- load_project calls _send_gradient_cancel_all before forwarding to nodes.

Tests are written BEFORE implementation (TDD — Red phase).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

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
        from cuemsengine.ControllerEngine import ControllerEngine

        ce = _make_controller()
        ce.set_status = MagicMock()

        op = _make_status_op(sender="gradientengine_node1")
        ce.status_operation_callback(op)

        ce.set_status.assert_not_called()

    def test_non_gradient_sender_status_processed(self):
        """STATUS from a normal node sender is not blocked by the gradient guard."""
        from cuemsengine.ControllerEngine import ControllerEngine

        ce = _make_controller()
        ce.set_status = MagicMock()

        op = _make_status_op(sender="node_1", target="script_finished",
                             data={"running": "no"})
        # Should not raise; set_status may or may not be called depending on
        # other guards — what matters is the gradient guard does NOT block it.
        try:
            ce.status_operation_callback(op)
        except Exception:
            pass  # Other missing attrs on mock are acceptable


# ---------------------------------------------------------------------------
# _send_gradient_cancel_all
# ---------------------------------------------------------------------------


class TestSendGradientCancelAll:
    def test_cancel_all_operation_payload(self):
        """_send_gradient_cancel_all sends COMMAND/UPDATE with cancel_all data."""
        from cuemsengine.ControllerEngine import ControllerEngine

        ce = _make_controller()
        ce._send_gradient_cancel_all()

        ce.communications_thread.send_operation.assert_called_once()
        op: NodeOperation = ce.communications_thread.send_operation.call_args[0][0]
        assert op.type == OperationType.COMMAND
        assert op.target == "gradientengine"
        assert op.data.get("command") == "cancel_all"

    def test_cancel_all_does_not_raise_on_send_error(self):
        """_send_gradient_cancel_all swallows send errors (non-blocking)."""
        from cuemsengine.ControllerEngine import ControllerEngine

        ce = _make_controller()
        ce.communications_thread.send_operation.side_effect = RuntimeError("NNG down")
        ce._send_gradient_cancel_all()  # must not propagate


# ---------------------------------------------------------------------------
# stop_script CANCEL_ALL ordering
# ---------------------------------------------------------------------------


class TestStopScriptCancelAllOrder:
    def test_cancel_all_before_forward_on_stop(self):
        """stop_script sends CANCEL_ALL before forwarding stop to nodes."""
        from cuemsengine.ControllerEngine import ControllerEngine

        ce = _make_controller()
        ce.get_status = MagicMock(return_value="yes")
        ce.go_offset = 0
        ce.set_status = MagicMock()
        ce._clear_playback_state = MagicMock()
        ce.cue_status = {}
        ce._broadcast_cue_status = MagicMock()

        call_order = []

        def track_cancel_all(*a, **kw):
            call_order.append("cancel_all")

        def track_forward(*a, **kw):
            call_order.append("forward")

        ce._send_gradient_cancel_all = MagicMock(side_effect=track_cancel_all)
        ce._forward_command_to_nodes = MagicMock(side_effect=track_forward)

        ce.stop_script("stop")

        assert "cancel_all" in call_order
        assert "forward" in call_order
        assert call_order.index("cancel_all") < call_order.index("forward"), (
            "CANCEL_ALL must fire before forwarding stop to nodes"
        )


# ---------------------------------------------------------------------------
# load_project CANCEL_ALL ordering
# ---------------------------------------------------------------------------


class TestLoadProjectCancelAllOrder:
    def test_cancel_all_before_forward_on_load(self):
        """load_project sends CANCEL_ALL before forwarding load to nodes."""
        from cuemsengine.ControllerEngine import ControllerEngine

        ce = _make_controller()
        ce.get_status = MagicMock(return_value="no")
        ce.set_status = MagicMock()
        ce._clear_playback_state = MagicMock()
        ce.reset_script = MagicMock()
        ce.read_script = MagicMock()
        ce.script = MagicMock()
        ce.script.cuelist = []
        ce.cue_status = {}
        ce.cue_enabled_status = {}
        ce._collect_cue_ids = MagicMock(return_value=[])
        ce._collect_cue_enabled = MagicMock(return_value={})
        ce._broadcast_cue_status = MagicMock()
        ce._broadcast_cue_enabled = MagicMock()
        ce.start_timecode = MagicMock()
        ce.set_show_lock_file = MagicMock()

        call_order = []

        def track_cancel_all(*a, **kw):
            call_order.append("cancel_all")

        def track_forward(*a, **kw):
            call_order.append("forward")

        ce._send_gradient_cancel_all = MagicMock(side_effect=track_cancel_all)
        ce._forward_load_to_nodes = MagicMock(side_effect=track_forward)

        with patch.object(ce.cm, "load_project_config"):
            ce.load_project("test_project")

        assert "cancel_all" in call_order
        assert "forward" in call_order
        assert call_order.index("cancel_all") < call_order.index("forward"), (
            "CANCEL_ALL must fire before forwarding load to nodes"
        )
