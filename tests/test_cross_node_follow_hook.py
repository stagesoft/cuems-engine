# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Cross-node Auto follow: the node's receive hook (ClickUp 869fc8ytz).

NodeCommunications receives one bus message at a time, in order, and then runs
each command on its own thread, where the command lock decides the order.
The follow messages and the run counter must follow the BUS order, so they are
applied in a synchronous hook, before any command thread is started:

- a 'follow' message is applied there and never reaches the command lock;
- GO records the run counter, STOP and load clear it, there;
- the hook can never stop a GO, a STOP or a load from running: an exception
  in it is logged and the command thread still starts.

Design: cuems-RELATIONS Plans/2026-10-05-engine-cross-node-auto-follow.md §3.5.
"""

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cuemsengine.comms.NodeCommunications import NodeCommunications
from cuemsengine.comms.NodesHub import ActionType, NodeOperation, OperationType

NODE_UUID = "aaaaaaaa-1111-2222-3333-444444444444"
CONTROLLER_UUID = "bbbbbbbb-1111-2222-3333-444444444444"


@pytest.fixture
def comms(monkeypatch):
    monkeypatch.setattr("cuemsengine.comms.NodeCommunications.NodesHub", MagicMock())
    obj = NodeCommunications(hub_address="tcp://127.0.0.1:0", node_id=NODE_UUID)
    obj.nng_hub.send_operation = AsyncMock()
    obj._command_callback = MagicMock()
    return obj


def _op(name, value):
    return NodeOperation(
        type=OperationType.COMMAND,
        action=ActionType.UPDATE,
        sender=CONTROLLER_UUID,
        target=name,
        data={"value": value, "address": f"/engine/command/{name}"},
    )


def _threads_started(comms, op):
    started = []
    real = threading.Thread

    def fake_thread(*a, **k):
        t = real(*a, **k)
        started.append(k.get("name"))
        return t

    with patch("threading.Thread", side_effect=fake_thread):
        comms._handle_command_operation(op)
    return started


class TestReceiveHook:
    def test_a_consumed_message_starts_no_command_thread(self, comms):
        comms.set_receive_hook(MagicMock(return_value=True))
        assert _threads_started(comms, _op("follow", {"op": "announce"})) == []
        comms._command_callback.assert_not_called()

    def test_the_hook_sees_name_and_value_before_the_thread(self, comms):
        hook = MagicMock(return_value=False)
        comms.set_receive_hook(hook)
        started = _threads_started(comms, _op("go", {"run_seq": 7}))
        hook.assert_called_once_with("go", {"run_seq": 7})
        assert started == ["NNG-Command-go"]

    def test_a_hook_that_raises_never_loses_the_command(self, comms):
        comms.set_receive_hook(MagicMock(side_effect=RuntimeError("boom")))
        with patch("cuemsengine.comms.NodeCommunications.Logger") as log:
            started = _threads_started(comms, _op("stop", None))
        assert started == ["NNG-Command-stop"]
        assert log.error.called

    def test_no_hook_keeps_todays_behaviour(self, comms):
        assert _threads_started(comms, _op("go", None)) == ["NNG-Command-go"]


class _Relay:
    def __init__(self):
        self.calls = []

    def begin_run(self, value):
        self.calls.append(("begin_run", value))

    def end_run(self, why):
        self.calls.append(("end_run", why))

    def on_message(self, value):
        self.calls.append(("on_message", value))


class TestNodeEngineHook:
    """NodeEngine._on_command_received, called from the hook."""

    def _node(self):
        from cuemsengine.NodeEngine import NodeEngine

        node = object.__new__(NodeEngine)
        node._follow_relay = _Relay()
        return node

    def test_follow_is_consumed(self):
        node = self._node()
        assert node._on_command_received("follow", {"op": "cancel"}) is True
        assert node._follow_relay.calls == [("on_message", {"op": "cancel"})]

    @pytest.mark.parametrize("value", [{"run_seq": 5, "go_mtc_ms": 1.0}, None, "x"])
    def test_go_records_the_run_and_still_runs(self, value):
        node = self._node()
        assert node._on_command_received("go", value) is False
        assert node._follow_relay.calls == [("begin_run", value)]

    @pytest.mark.parametrize("name", ["stop", "load"])
    def test_stop_and_load_end_the_run_and_still_run(self, name):
        node = self._node()
        assert node._on_command_received(name, None) is False
        assert node._follow_relay.calls == [("end_run", name)]

    @pytest.mark.parametrize("name", ["setnextcue", "cue_enabled", "deploy"])
    def test_other_commands_are_untouched(self, name):
        node = self._node()
        assert node._on_command_received(name, "v") is False
        assert node._follow_relay.calls == []

    def test_without_a_relay_nothing_is_consumed(self):
        node = self._node()
        node._follow_relay = None
        assert node._on_command_received("follow", {}) is False


class TestReviewFixes:
    def test_a_follow_handler_that_raises_is_still_consumed(self):
        """MINOR-6: never let a follow message reach the command lock."""
        from cuemsengine.NodeEngine import NodeEngine

        node = object.__new__(NodeEngine)
        node._follow_relay = MagicMock()
        node._follow_relay.on_message.side_effect = RuntimeError("bug")
        with patch("cuemsengine.NodeEngine.Logger") as log:
            assert node._on_command_received("follow", {}) is True
        assert log.error.called

    @pytest.mark.parametrize("name", ["stop", "load"])
    def test_stop_and_load_are_marked_applied_after_they_run(self, name):
        """MINOR-4: the node's own STOP/load has run (or was refused)."""
        from cuemsengine.NodeEngine import NodeEngine

        node = object.__new__(NodeEngine)
        node._command_lock = threading.Lock()
        node._follow_relay = MagicMock()
        node.commands_dict = {name: MagicMock(side_effect=RuntimeError("x"))}
        with pytest.raises(RuntimeError):
            node.run_command(name, None)
        node._follow_relay.stop_applied.assert_called_once()
