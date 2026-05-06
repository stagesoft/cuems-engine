"""Unit tests for NodeCommunications gradient-motiond routing (T005).

Covers:
- gradientengine-targeted COMMAND messages are swallowed (not forwarded to callback).
- STATUS messages with event="fade_complete" call CUE_HANDLER.on_fade_complete.
- send_fade_command / send_cancel_all build correct NodeOperation payloads.

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


def _make_operation(
    type_: OperationType,
    target: str,
    sender: str = "node_1",
    data: dict | None = None,
    action: ActionType = ActionType.UPDATE,
) -> NodeOperation:
    return NodeOperation(
        type=type_,
        action=action,
        sender=sender,
        target=target,
        data=data or {},
    )


def _build_comms(command_callback=None):
    """Build a NodeCommunications with a mocked NodesHub."""
    from cuemsengine.comms.NodeCommunications import NodeCommunications

    with patch("cuemsengine.comms.NodeCommunications.NodesHub") as MockHub:
        hub = MagicMock()
        MockHub.return_value = hub
        comms = NodeCommunications(
            hub_address="tcp://127.0.0.1:5555",
            node_id="test-node",
            command_callback=command_callback,
        )
        comms.nng_hub = hub
        return comms, hub


# ---------------------------------------------------------------------------
# gradientengine COMMAND filter
# ---------------------------------------------------------------------------


class TestGradientEngineCommandFilter:
    def test_gradientengine_command_not_forwarded_to_callback(self):
        """COMMAND with target='gradientengine' must NOT reach the command callback."""
        callback = MagicMock()
        comms, _ = _build_comms(command_callback=callback)

        op = _make_operation(OperationType.COMMAND, target="gradientengine",
                             data={"command": "start_fade"})
        comms._handle_command_operation(op)

        callback.assert_not_called()

    def test_non_gradient_command_forwarded_to_callback(self):
        """COMMAND with other targets IS forwarded to the command callback."""
        callback = MagicMock()
        comms, _ = _build_comms(command_callback=callback)

        op = _make_operation(OperationType.COMMAND, target="go",
                             data={"value": None})
        # _handle_command_operation calls callback in a thread; call directly.
        with patch("threading.Thread") as mock_thread:
            comms._handle_command_operation(op)
            mock_thread.assert_called_once()

    def test_wrong_operation_type_ignored(self):
        """Non-COMMAND operation in _handle_command_operation is ignored."""
        callback = MagicMock()
        comms, _ = _build_comms(command_callback=callback)

        op = _make_operation(OperationType.STATUS, target="go")
        comms._handle_command_operation(op)
        callback.assert_not_called()


# ---------------------------------------------------------------------------
# STATUS callback registration
# ---------------------------------------------------------------------------


class TestStatusCallbackRegistration:
    def test_status_callback_registered_on_init(self):
        """NodeCommunications registers OperationType.STATUS on initialisation."""
        from cuemsengine.comms.NodeCommunications import NodeCommunications

        with patch("cuemsengine.comms.NodeCommunications.NodesHub") as MockHub:
            hub = MagicMock()
            MockHub.return_value = hub
            NodeCommunications(
                hub_address="tcp://127.0.0.1:5555",
                node_id="test-node",
            )
            # set_receive_callbacks must have been called with STATUS key
            hub.set_receive_callbacks.assert_called_once()
            registered = hub.set_receive_callbacks.call_args[0][0]
            assert OperationType.STATUS in registered


# ---------------------------------------------------------------------------
# fade_complete STATUS dispatch
# ---------------------------------------------------------------------------


class TestFadeCompleteStatusDispatch:
    def test_fade_complete_calls_cue_handler(self):
        """fade_complete STATUS triggers CUE_HANDLER.on_fade_complete(fade_id)."""
        comms, _ = _build_comms()
        op = _make_operation(
            OperationType.STATUS,
            target="gradientengine",
            sender="gradientengine_node1",
            data={"event": "fade_complete", "fade_id": "my-fade-uuid"},
        )
        mock_handler = MagicMock()
        # Patch the source of truth — the lazy import reads from this namespace.
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER", mock_handler):
            comms._handle_status_operation(op)
            mock_handler.on_fade_complete.assert_called_once_with("my-fade-uuid")

    def test_other_status_event_ignored(self):
        """STATUS messages with target='gradientengine' but other events are ignored."""
        comms, _ = _build_comms()
        op = _make_operation(
            OperationType.STATUS,
            target="gradientengine",
            sender="gradientengine_node1",
            data={"event": "some_other_event", "fade_id": "x"},
        )
        mock_handler = MagicMock()
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER", mock_handler):
            comms._handle_status_operation(op)
            mock_handler.on_fade_complete.assert_not_called()

    def test_non_gradientengine_status_ignored(self):
        """STATUS with target != 'gradientengine' does not call on_fade_complete."""
        comms, _ = _build_comms()
        op = _make_operation(
            OperationType.STATUS,
            target="nextcue",
            sender="node_1",
            data={"nextcue": "some-cue-id"},
        )
        mock_handler = MagicMock()
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER", mock_handler):
            comms._handle_status_operation(op)
            mock_handler.on_fade_complete.assert_not_called()


# ---------------------------------------------------------------------------
# send_fade_command / send_cancel_all
# ---------------------------------------------------------------------------


class TestGradientEngineSendMethods:
    def test_send_fade_command_builds_correct_operation(self):
        """send_fade_command sends COMMAND/UPDATE NodeOperation with target='gradientengine'."""
        comms, hub = _build_comms()
        payload = {
            "command": "start_fade",
            "fade_id": "abc",
            "osc_host": "127.0.0.1",
            "osc_port": 12345,
            "osc_path": "/volmaster",
            "start_value": 0.0,
            "end_value": 1.0,
            "start_mtc_ms": 0,
            "duration_ms": 3000,
            "curve_type": "linear",
            "curve_params": {},
        }
        with patch.object(comms, "send_operation") as mock_send:
            comms.send_fade_command(payload)
            mock_send.assert_called_once()
            op: NodeOperation = mock_send.call_args[0][0]
            assert op.type == OperationType.COMMAND
            assert op.target == "gradientengine"
            assert op.data == payload

    def test_send_cancel_all_builds_correct_operation(self):
        """send_cancel_all sends COMMAND/UPDATE with command='cancel_all'."""
        comms, hub = _build_comms()
        with patch.object(comms, "send_operation") as mock_send:
            comms.send_cancel_all()
            mock_send.assert_called_once()
            op: NodeOperation = mock_send.call_args[0][0]
            assert op.type == OperationType.COMMAND
            assert op.target == "gradientengine"
            assert op.data.get("command") == "cancel_all"
