# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""stop_project, controller side (ClickUp 869fhjdq5).

A stop_project ActionCue is the authored end of an unattended show. Every node
reveals it and sends the controller a STATUS op {cue, run_seq}; the controller
validates it like a follow message and runs stop_script, i.e. the operator
STOP. The first valid message wins; the others are expected duplicates and are
dropped at INFO. Two hardenings travel with it: cue ADD/UPDATE operations are
ignored while the show is not running (a node's late start report after a
STOP must not leave a cue at 1 or 100), and STOP restarts the arm watchdog so
a failed re-arm is logged instead of answering every /go with a silent 409.

Design: cuems-RELATIONS Plans/2026-10-15-engine-stop-project-actioncue.md §4.4.
"""

from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cuemsutils.cues import ActionCue, AudioCue

from cuemsengine.comms.NodesHub import ActionType, NodeOperation, OperationType
from tests.support.paths import DATA_DIR

STOP_CUE = "11111111-1111-4111-8111-111111111111"
AUDIO_CUE = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def set_config_path():
    test_conf_path = DATA_DIR
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
        mock_cm_instance.library_path = str(DATA_DIR)
        mock_cm_instance.tmp_path = "/tmp"

        from cuemsengine.ControllerEngine import ControllerEngine

        engine = ControllerEngine(with_mtc=False)
        engine.communications_thread = Mock()
        engine.communications_thread.broadcast_osc = Mock()
        engine.communications_thread.nng_hub = Mock()
        yield engine
        engine._cancel_arm_watchdog()
        engine.stop()


def _stop_cue_object():
    return ActionCue({"action_target": "", "action_type": "stop_project"})


@pytest.fixture
def running(controller):
    controller.set_status("running", "yes")
    controller._adopted_nodes = {"node-a", "node-b"}
    controller._required_nodes = {"node-a", "node-b"}
    controller.cue_status = {STOP_CUE: 1, AUDIO_CUE: 100}
    controller.cue_names = {STOP_CUE: "Fin", AUDIO_CUE: "Audio"}
    cues = {STOP_CUE: _stop_cue_object(), AUDIO_CUE: AudioCue()}
    controller.script = SimpleNamespace(find=lambda cid: cues.get(str(cid)), name="p")
    return controller


def _op(sender="node-a", cue=STOP_CUE, run_seq=None, data=None):
    payload = {"cue": cue, "run_seq": run_seq} if data is None else data
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target="stop_project",
        data=payload,
    )


def _stops(fwd):
    return [c for c in fwd.call_args_list if c.args[0] == "/engine/command/stop"]


def _logged(log_method, needle):
    return any(needle in str(c.args[0]) for c in log_method.call_args_list)


class TestStopProjectRelay:
    def test_stops_the_show_once(self, running):
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(_op(run_seq=running._run_seq))
        assert running.get_status("running") == "no"
        assert len(_stops(fwd)) == 1
        assert _logged(log.info, "stopping the show")
        # The operator STOP's reset: every cue back to 0.
        assert all(v == 0 for v in running.cue_status.values())

    def test_the_other_nodes_messages_are_dropped_at_info(self, running):
        seq = running._run_seq
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(_op(sender="node-a", run_seq=seq))
            running.status_operation_callback(_op(sender="node-b", run_seq=seq))
        assert len(_stops(fwd)) == 1
        assert _logged(log.info, "not part of the current run")
        assert not log.warning.called

    def test_drops_a_stale_run_seq(self, running):
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(_op(run_seq=running._run_seq - 1))
        assert not _stops(fwd)
        assert running.get_status("running") == "yes"
        assert _logged(log.info, "not part of the current run")

    def test_drops_when_not_running(self, running):
        running.set_status("running", "no")
        with patch.object(running, "_forward_command_to_nodes") as fwd:
            running.status_operation_callback(_op(run_seq=running._run_seq))
        assert not _stops(fwd)

    def test_drops_a_non_adopted_sender_with_a_warning(self, running):
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(
                _op(sender="stranger", run_seq=running._run_seq)
            )
        assert not _stops(fwd)
        assert _logged(log.warning, "not an adopted node")
        assert running.get_status("running") == "yes"

    def test_drops_an_unknown_cue_with_a_warning(self, running):
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(
                _op(cue="not-in-project", run_seq=running._run_seq)
            )
        assert not _stops(fwd)
        assert _logged(log.warning, "not in the loaded project")

    def test_drops_a_cue_that_is_not_a_stop_project_with_a_warning(self, running):
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(
                _op(cue=AUDIO_CUE, run_seq=running._run_seq)
            )
        assert not _stops(fwd)
        assert _logged(log.warning, "not a stop_project ActionCue")

    def test_drops_a_message_without_a_cue_with_a_warning(self, running):
        with (
            patch.object(running, "_forward_command_to_nodes") as fwd,
            patch("cuemsengine.ControllerEngine.Logger") as log,
        ):
            running.status_operation_callback(_op(data={}))
        assert not _stops(fwd)
        assert log.warning.called

    def test_releases_the_run_seq_lock(self, running):
        with patch.object(running, "_forward_command_to_nodes"):
            running.status_operation_callback(_op(run_seq=running._run_seq))
        # stop_script takes the lock in _bump_run_seq; the handler must have
        # released it before the call and left it free after.
        assert running._run_seq_lock.acquire(blocking=False)
        running._run_seq_lock.release()


def _cue_op(action, cue, **extra):
    data = {"id": cue, "offset": 0}
    data.update(extra)
    return NodeOperation(
        type=OperationType.CUE,
        action=action,
        sender="node-a",
        target=cue,
        data=data,
    )


class TestCueAddGate:
    def test_add_while_running_lights_the_cue(self, running):
        running.cue_status[AUDIO_CUE] = 0
        running.cue_operation_callback(_cue_op(ActionType.ADD, AUDIO_CUE))
        assert running.cue_status[AUDIO_CUE] == 1

    def test_add_while_not_running_is_ignored(self, running):
        running.set_status("running", "no")
        running.cue_status[STOP_CUE] = 0
        with patch.object(running, "_broadcast_cue_status") as bc:
            running.cue_operation_callback(_cue_op(ActionType.ADD, STOP_CUE))
        assert running.cue_status[STOP_CUE] == 0
        bc.assert_not_called()

    def test_update_while_not_running_is_ignored(self, running):
        running.set_status("running", "no")
        running.cue_status[AUDIO_CUE] = 0
        with patch.object(running, "_broadcast_cue_status") as bc:
            running.cue_operation_callback(
                _cue_op(ActionType.UPDATE, AUDIO_CUE, percentage=50)
            )
        assert running.cue_status[AUDIO_CUE] == 0
        bc.assert_not_called()

    def test_remove_is_not_gated(self, running):
        # A REMOVE that reaches a cue still at 1 while not running keeps its
        # pre-existing meaning (1 -> 100); after a STOP every cue is 0, so the
        # existing stale-REMOVE rule drops it anyway.
        running.set_status("running", "no")
        running.cue_status[AUDIO_CUE] = 1
        running.cue_operation_callback(_cue_op(ActionType.REMOVE, AUDIO_CUE))
        assert running.cue_status[AUDIO_CUE] == 100

    def test_late_start_after_an_authored_stop_cannot_reach_100(self, running):
        """The multi-node race the gate exists for: node-b dispatched the stop
        cue just before the STOP reached it, so its ADD and then its disarm's
        REMOVE arrive after the controller's reset."""
        with patch.object(running, "_forward_command_to_nodes"):
            running.status_operation_callback(_op(run_seq=running._run_seq))
        assert running.cue_status[STOP_CUE] == 0
        running.cue_operation_callback(_cue_op(ActionType.ADD, STOP_CUE))
        running.cue_operation_callback(_cue_op(ActionType.REMOVE, STOP_CUE))
        assert running.cue_status[STOP_CUE] == 0


def _armed_ready(sender):
    return NodeOperation(
        type=OperationType.STATUS,
        action=ActionType.UPDATE,
        sender=sender,
        target="armed_ready",
        data={"armed": "yes"},
    )


class TestArmWatchdogAfterStop:
    def test_stop_starts_the_watchdog(self, running):
        with patch.object(running, "_forward_command_to_nodes"):
            running.stop_script(None)
        assert running._arm_watchdog is not None
        assert running._arm_watchdog_what == "Re-arm after STOP"

    def test_every_node_re_armed_cancels_it(self, running):
        with (
            patch.object(running, "_forward_command_to_nodes"),
            patch.object(running, "start_timecode"),
        ):
            running.stop_script(None)
            running.status_operation_callback(_armed_ready("node-a"))
            assert running._arm_watchdog is not None
            running.status_operation_callback(_armed_ready("node-b"))
        assert running.get_status("armed") == "yes"
        assert running._arm_watchdog is None

    def test_fire_names_the_operation_and_the_pending_nodes(self, running):
        running._arm_watchdog_what = "Re-arm after STOP"
        running._armed_nodes = {"node-a"}
        with patch("cuemsengine.ControllerEngine.Logger") as log:
            running._on_arm_watchdog_fire()
        msg = str(log.error.call_args.args[0])
        assert msg.startswith("Re-arm after STOP stalled")
        assert "node-b" in msg

    def test_load_keeps_its_wording(self, running):
        running._arm_arm_watchdog()
        running._cancel_arm_watchdog()
        running._armed_nodes = set()
        with patch("cuemsengine.ControllerEngine.Logger") as log:
            running._on_arm_watchdog_fire()
        assert str(log.error.call_args.args[0]).startswith("Load stalled")


class TestStopProjectBuiltInCode:
    """R-3 (009): the cue as code builds it, with no target, reaches its handler.

    The action guard rejects a missing target unless the action is project
    scoped. A ``stop_project`` ActionCue built from a dict, the way the
    controller tests build one, must get past both the "unsupported" and the
    "missing target" guards of ``ActionHandler.execute_action``.
    """

    @pytest.fixture
    def action_handler(self):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER
        from cuemsengine.cues.CueHandler import CUE_HANDLER

        ACTION_HANDLER.bind_cue_handler(Mock())
        ACTION_HANDLER.set_emit_enabled(False)
        yield ACTION_HANDLER
        ACTION_HANDLER.bind_cue_handler(CUE_HANDLER)
        ACTION_HANDLER.set_emit_enabled(True)

    def test_a_targetless_stop_project_is_applied_not_rejected(self, action_handler):
        cue = _stop_cue_object()
        assert not cue.action_target

        result = action_handler.execute_action(cue, Mock())

        assert result["status"] == "applied"
        assert result["action_type"] == "stop_project"
        assert result["target_id"] is None

    def test_other_project_actions_are_still_rejected(self, action_handler):
        for action_type in ("pause_project", "resume_project", "load", "unload"):
            cue = ActionCue({"action_target": "", "action_type": action_type})
            result = action_handler.execute_action(cue, Mock())
            assert result["status"] == "rejected", action_type


def test_stop_project_senders_are_the_adopted_nodes_of_the_go_gate(tmp_path):
    """R-4 (009): one adoption rule for the GO gate and for stop_project.

    Adopted nodes are accepted whether or not they answered the liveness
    probe (an adopted node that went quiet may still report), a node the map
    marks not adopted is refused, and so is a uuid the map does not hold.
    """
    from cuemsutils.tools.ids import coerce_identity as as_id

    from tests.support.network_map_helpers import (
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
        engine.cue_status = {as_id(STOP_CUE): 1}
        cue = _stop_cue_object()
        engine.script = SimpleNamespace(find=lambda cue_id: cue)

        accepted = set()
        for sender in (controller_id, online, offline, not_adopted, stranger):
            with patch.object(engine, "stop_script") as stop_script:
                engine.status_operation_callback(_op(sender, run_seq=engine._run_seq))
            if stop_script.called:
                accepted.add(sender)

        assert accepted == {str(uuid) for uuid in engine._adopted_node_uuids()}
        assert accepted == {controller_id, online, offline}
