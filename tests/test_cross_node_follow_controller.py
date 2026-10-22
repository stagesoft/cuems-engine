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
        # Nodes get an unload, not a STOP (869fh8kef).
        seen, p = _seq_at_forward(controller, "/engine/command/unload")
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


def test_follow_senders_are_the_adopted_nodes_of_the_go_gate(tmp_path):
    """R-4 (009): the follow relay and the GO gate share one adoption rule.

    The relay accepts an adopted node whether or not it answered the liveness
    probe, and refuses a node the map marks not adopted and a uuid it does not
    hold, exactly the set ``_adopted_node_uuids`` gives the GO gate.
    """
    from cuemsutils.tools.ids import coerce_identity as as_id

    from .network_map_helpers import (
        controller_with_map,
        resolve_cluster,
        typed_network_map,
    )

    controller_id, online, offline = (
        "3f2b8c1e-5d4a-4b6e-9c7f-1a2b3c4d5e6f",
        "9a8b7c6d-1e2f-4a3b-8c4d-5e6f7a8b9c0d",
        "5b1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f",
    )
    not_adopted, stranger = (
        "7c7c7c7c-0000-4000-8000-000000000007",
        "8e8e8e8e-0000-4000-8000-000000000008",
    )
    source, target = (
        "2c2c2c2c-0000-4000-8000-00000000000a",
        "3d3d3d3d-0000-4000-8000-00000000000b",
    )
    network_map = typed_network_map(
        tmp_path,
        [
            {"uuid": controller_id, "node_role": "controller", "adopted": True},
            {"uuid": online, "adopted": True},
            {"uuid": offline, "adopted": True},
            {"uuid": not_adopted, "adopted": False},
        ],
    )
    with controller_with_map(controller_id, network_map) as engine:
        resolve_cluster(engine, alive=[online])
        engine.set_status("running", "yes")
        engine.cue_status = {as_id(source): 0, as_id(target): 0}

        accepted = set()
        for sender in (controller_id, online, offline, not_adopted, stranger):
            message = NodeOperation(
                type=OperationType.STATUS,
                action=ActionType.UPDATE,
                sender=sender,
                target="follow",
                data={
                    "op": "announce",
                    "source": source,
                    "target": target,
                    "seed_ms": 0,
                    "run_seq": engine._run_seq,
                },
            )
            with patch.object(engine, "_forward_command_to_nodes") as forward:
                engine.status_operation_callback(message)
            if forward.called:
                accepted.add(sender)

        assert accepted == {str(uuid) for uuid in engine._adopted_node_uuids()}
        assert accepted == {controller_id, online, offline}
