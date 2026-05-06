"""Unit tests for NodeCommunications gradient-motiond routing (T005).

Covers:
- gradientengine-targeted COMMAND messages are swallowed (not forwarded to callback).
- STATUS messages from gradient-motiond are log-discarded (no Python state mutation).
- send_fade_command wraps a body payload with envelope fields and sends a COMMAND.
- send_cancel_all sends COMMAND with command='cancel_all'.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
            hub.set_receive_callbacks.assert_called_once()
            registered = hub.set_receive_callbacks.call_args[0][0]
            assert OperationType.STATUS in registered


# ---------------------------------------------------------------------------
# gradient-motiond STATUS log-and-discard
# ---------------------------------------------------------------------------


class TestGradientStatusDiscarded:
    def test_gradientengine_status_does_not_raise(self):
        """STATUS messages with target='gradientengine' are silently log-discarded."""
        comms, _ = _build_comms()
        op = _make_operation(
            OperationType.STATUS,
            target="gradientengine",
            sender="gradientengine_node1",
            data={"event": "fade_complete", "fade_id": "my-fade-uuid"},
        )
        # Must not raise; must not touch CUE_HANDLER (no on_fade_complete in scope).
        comms._handle_status_operation(op)

    def test_non_gradientengine_status_no_op(self):
        """STATUS with target != 'gradientengine' is a no-op in this handler."""
        comms, _ = _build_comms()
        op = _make_operation(
            OperationType.STATUS,
            target="nextcue",
            sender="node_1",
            data={"nextcue": "some-cue-id"},
        )
        comms._handle_status_operation(op)


# ---------------------------------------------------------------------------
# send_fade_command / send_cancel_all
# ---------------------------------------------------------------------------


class TestGradientEngineSendMethods:
    def test_send_fade_command_wraps_body_with_envelope(self):
        """send_fade_command injects command, fade_id, osc_host, curve_params."""
        comms, _ = _build_comms()
        body = {
            "osc_port": 12345,
            "osc_path": "/volmaster",
            "start_value": 0.5,
            "target_value": 80,
            "start_time": 1234,
            "duration_ms": 3000,
            "curve_type": "linear",
        }
        with patch.object(comms, "send_operation") as mock_send:
            comms.send_fade_command(body, fade_id="my-fade-uuid")
            mock_send.assert_called_once()
            op: NodeOperation = mock_send.call_args[0][0]
            assert op.type == OperationType.COMMAND
            assert op.target == "gradientengine"
            assert op.data["command"] == "start_fade"
            assert op.data["fade_id"] == "my-fade-uuid"
            assert op.data["osc_host"] == "127.0.0.1"
            assert op.data["curve_params"] == {}
            # body fields preserved
            assert op.data["osc_port"] == 12345
            assert op.data["osc_path"] == "/volmaster"
            assert op.data["target_value"] == 80
            assert op.data["start_time"] == 1234
            assert op.data["duration_ms"] == 3000
            assert op.data["curve_type"] == "linear"

    def test_send_cancel_all_builds_correct_operation(self):
        """send_cancel_all sends COMMAND/UPDATE with command='cancel_all'."""
        comms, _ = _build_comms()
        with patch.object(comms, "send_operation") as mock_send:
            comms.send_cancel_all()
            mock_send.assert_called_once()
            op: NodeOperation = mock_send.call_args[0][0]
            assert op.type == OperationType.COMMAND
            assert op.target == "gradientengine"
            assert op.data.get("command") == "cancel_all"
