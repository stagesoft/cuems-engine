# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Cross-node Auto follow, controller side (ClickUp 869fc8ytz).

The controller only relays: a node that owns an Auto follow's source announces
the follow instant (or cancels it), and the controller forwards that to every
node. What it adds is the run counter, `run_seq`:

- it starts from the clock, so a restarted controller never reuses a value a
  node still holds;
- STOP, load and unload bump it BEFORE they forward anything to the nodes;
- every GO carries it, so every node knows the run it belongs to;
- a follow message is relayed only while the show runs and only if it carries
  the current value. The check and the forward share one lock with the bump,
  so a relayed follow can never be queued behind a STOP it predates.

Design: cuems-RELATIONS Plans/2026-10-05-engine-cross-node-auto-follow.md §3.3-3.4.
"""

import time
from os import environ
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from cuemsengine.comms.NodesHub import ActionType, NodeOperation, OperationType


@pytest.fixture(autouse=True)
def set_config_path():
    test_conf_path = Path(__file__).parent / ".." / "dev" / "test_xml_files"
    environ["CUEMS_CONF_PATH"] = str(test_conf_path)


@pytest.fixture
def controller():
    with (
        patch("cuemsengine.core.BaseEngine.ConfigManager") as MockCM,
        patch(
            "cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip",
            return_value="localhost",
        ),
    ):
        mock_cm_instance = MockCM.return_value
        mock_cm_instance.node_conf = {
            "uuid": "test-controller-uuid",
            "mtc_port": "MTC_MIDI_PORT",
        }
        mock_cm_instance.library_path = str(
            Path(__file__).parent / ".." / "dev" / "test_xml_files"
        )
        mock_cm_instance.tmp_path = "/tmp"

        from cuemsengine.ControllerEngine import ControllerEngine

        engine = ControllerEngine(with_mtc=False)
        engine.communications_thread = Mock()
        engine.communications_thread.broadcast_osc = Mock()
        engine.communications_thread.nng_hub = Mock()
        yield engine
        engine.stop()


def _seq_at_forward(controller, address):
    """Patch _forward_command_to_nodes and record run_seq at the moment the
    given address is forwarded."""
    seen = []

    def fwd(addr, value):
        if addr == address:
            seen.append(controller._run_seq)

    return seen, patch.object(controller, "_forward_command_to_nodes", side_effect=fwd)


class TestRunSeq:
    def test_starts_from_the_clock(self, controller):
        now_ms = time.time_ns() // 1_000_000
        assert isinstance(controller._run_seq, int)
        assert now_ms - 60_000 <= controller._run_seq <= now_ms

    def test_stop_bumps_it_before_forwarding(self, controller):
        controller.set_status("running", "yes")
        before = controller._run_seq
        seen, p = _seq_at_forward(controller, "/engine/command/stop")
        with p:
            controller.stop_script(None)
        assert seen == [before + 1]

    def test_stop_while_not_running_leaves_it(self, controller):
        controller.set_status("running", "no")
        before = controller._run_seq
        with patch.object(controller, "_forward_command_to_nodes"):
            controller.stop_script(None)
        assert controller._run_seq == before

    def test_unload_bumps_it_before_forwarding(self, controller):
        controller.set_status("running", "no")
        before = controller._run_seq
        seen, p = _seq_at_forward(controller, "/engine/command/stop")
        with p, patch.object(controller, "reset_script"):
            controller.unload_project(None)
        assert seen == [before + 1]

    def test_load_bumps_it_before_forwarding(self, controller):
        controller.set_status("running", "no")
        before = controller._run_seq
        seen, p = _seq_at_forward(controller, "/engine/command/load")

        def read_script(name):
            controller.script = MagicMock()

        with (
            p,
            patch.object(controller, "reset_script"),
            patch.object(controller, "read_script", side_effect=read_script),
            patch.object(controller, "_collect_cue_ids", return_value=[]),
            patch.object(controller, "_collect_cue_enabled", return_value={}),
            patch.object(controller, "_resolve_cluster_state"),
            patch.object(controller, "start_timecode"),
            patch.object(controller, "set_show_lock_file"),
        ):
            assert controller.load_project("p") is True
        assert seen == [before + 1]

    def test_every_go_carries_the_current_value(self, controller):
        controller.set_status("armed", "yes")
        controller.script = Mock()
        with patch.object(controller, "_forward_command_to_nodes") as fwd:
            controller.go_script(None)
            controller.go_script(None)
        values = [c.args[1] for c in fwd.call_args_list]
        assert [v["run_seq"] for v in values] == [controller._run_seq] * 2


def _follow(sender="node-a", **data):
    payload = {
        "op": "announce",
        "origin": sender,
        "source": "src",
        "target": "tgt",
        "seed_ms": 1000.0,
    }
    payload.update(data)
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target="follow",
        data=payload,
    )


class TestFollowRelay:
    @pytest.fixture
    def running(self, controller):
        controller.set_status("running", "yes")
        controller._adopted_nodes = {"node-a", "node-b"}
        controller.cue_status = {"src": 1, "tgt": 0}
        return controller

    def test_forwards_a_current_message_to_every_node(self, running):
        op = _follow(run_seq=running._run_seq)
        with patch.object(running, "_forward_command_to_nodes") as fwd:
            running.status_operation_callback(op)
        fwd.assert_called_once_with("/engine/command/follow", op.data)

    def test_forwards_a_cancel_too(self, running):
        op = _follow(op="cancel", reason="stop", run_seq=running._run_seq)
        with patch.object(running, "_forward_command_to_nodes") as fwd:
            running.status_operation_callback(op)
        fwd.assert_called_once_with("/engine/command/follow", op.data)

    def test_drops_a_stale_run_seq(self, running):
        op = _follow(run_seq=running._run_seq - 1)
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(op)
        fwd.assert_not_called()
        assert log.info.called

    def test_drops_when_not_running(self, running):
        running.set_status("running", "no")
        op = _follow(run_seq=running._run_seq)
        with patch.object(running, "_forward_command_to_nodes") as fwd:
            running.status_operation_callback(op)
        fwd.assert_not_called()

    def test_drops_a_message_sent_before_a_stop(self, running):
        """The node's run_seq predates the STOP: it must not reach the nodes
        after the STOP, whatever the order the two arrive in."""
        op = _follow(run_seq=running._run_seq)
        with patch.object(running, "_forward_command_to_nodes") as fwd:
            running.stop_script(None)
            running.set_status("running", "yes")  # even a new GO's state
            running.status_operation_callback(op)
        assert all(c.args[0] != "/engine/command/follow" for c in fwd.call_args_list)

    def test_drops_a_non_adopted_sender_with_a_warning(self, running):
        op = _follow(sender="stranger", run_seq=running._run_seq)
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(op)
        fwd.assert_not_called()
        assert log.warning.called

    def test_drops_an_unknown_cue_with_a_warning(self, running):
        op = _follow(target="not-in-project", run_seq=running._run_seq)
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(op)
        fwd.assert_not_called()
        assert log.warning.called

    def test_tolerates_a_message_without_data(self, running):
        op = _follow(run_seq=running._run_seq)
        op.data = None
        with patch.object(running, "_forward_command_to_nodes") as fwd:
            running.status_operation_callback(op)
        fwd.assert_not_called()
