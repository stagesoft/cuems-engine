# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""stop_project, node side (ClickUp 869fhjdq5).

When a stop_project ActionCue is revealed, the node sends the controller a
STATUS op {cue, run_seq} and stops nothing itself; the controller's STOP does.
A 3 s watchdog compares STOP/load receipts at send time and at fire time and
only logs. The stop cue is a hard chain break on the node.

Design: cuems-RELATIONS Plans/2026-10-15-engine-stop-project-actioncue.md §4.3.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import ActionCue, AudioCue


def _node(run_seq=42, stop_pending=False, stops_received=3):
    from cuemsengine.NodeEngine import NodeEngine

    ne = object.__new__(NodeEngine)
    ne.cm = SimpleNamespace(node_uuid="node-a")
    ne._follow_relay = SimpleNamespace(
        run_seq=run_seq,
        stop_pending=stop_pending,
        stops_received=stops_received,
        end_run=MagicMock(),
        begin_run=MagicMock(),
    )
    ne._stop_project_watchdog = None
    return ne


class TestNotifyStopProject:
    def test_sends_the_cue_and_the_run_without_waiting(self):
        ne = _node()
        with (
            patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch,
            patch("cuemsengine.NodeEngine.threading.Timer") as timer,
        ):
            ne._notify_stop_project("cue-1")
        send = ch.communications_thread.send_operation_nowait
        send.assert_called_once()
        op = send.call_args.args[0]
        assert op.target == "stop_project"
        assert op.sender == "node-a"
        assert op.data == {"cue": "cue-1", "run_seq": 42}
        ch.communications_thread.send_operation.assert_not_called()
        timer.assert_called_once()
        timer.return_value.start.assert_called_once()

    def test_skips_when_a_stop_or_load_is_already_pending(self):
        ne = _node(stop_pending=True)
        with (
            patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch,
            patch("cuemsengine.NodeEngine.threading.Timer") as timer,
            patch("cuemsengine.NodeEngine.Logger") as log,
        ):
            ne._notify_stop_project("cue-1")
        ch.communications_thread.send_operation_nowait.assert_not_called()
        timer.assert_not_called()
        assert log.info.called
        assert not log.warning.called

    def test_skips_when_no_run_is_in_progress(self):
        ne = _node(run_seq=None)
        with (
            patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch,
            patch("cuemsengine.NodeEngine.threading.Timer") as timer,
            patch("cuemsengine.NodeEngine.Logger") as log,
        ):
            ne._notify_stop_project("cue-1")
        ch.communications_thread.send_operation_nowait.assert_not_called()
        timer.assert_not_called()
        assert log.info.called

    def test_warns_without_a_relay(self):
        ne = _node()
        ne._follow_relay = None
        with (
            patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch,
            patch("cuemsengine.NodeEngine.Logger") as log,
        ):
            ne._notify_stop_project("cue-1")
        ch.communications_thread.send_operation_nowait.assert_not_called()
        assert log.warning.called

    def test_a_send_failure_is_logged_not_raised(self):
        ne = _node()
        with (
            patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch,
            patch("cuemsengine.NodeEngine.threading.Timer") as timer,
            patch("cuemsengine.NodeEngine.Logger") as log,
        ):
            ch.communications_thread.send_operation_nowait.side_effect = RuntimeError(
                "loop down"
            )
            ne._notify_stop_project("cue-1")
        assert log.error.called
        timer.assert_not_called()


class TestWatchdog:
    def test_warns_when_no_stop_was_received(self):
        ne = _node(stops_received=3)
        with patch("cuemsengine.NodeEngine.Logger") as log:
            ne._on_stop_project_watchdog_fire("cue-1", 3)
        assert "no STOP received" in str(log.warning.call_args.args[0])

    def test_is_silent_when_a_stop_was_received(self):
        ne = _node(stops_received=4)
        with patch("cuemsengine.NodeEngine.Logger") as log:
            ne._on_stop_project_watchdog_fire("cue-1", 3)
        assert not log.warning.called

    @pytest.mark.parametrize("command", ["stop", "load"])
    def test_the_receipt_of_a_stop_or_load_cancels_the_timer(self, command):
        ne = _node()
        timer = MagicMock()
        ne._stop_project_watchdog = timer
        consumed = ne._on_command_received(command, None)
        assert consumed is False
        timer.cancel.assert_called_once()
        assert ne._stop_project_watchdog is None
        ne._follow_relay.end_run.assert_called_once_with(command)

    def test_a_go_does_not_cancel_it(self):
        ne = _node()
        timer = MagicMock()
        ne._stop_project_watchdog = timer
        ne._on_command_received("go", {"run_seq": 43})
        timer.cancel.assert_not_called()


class TestSink:
    def test_routes_an_applied_stop_project_to_the_notifier(self):
        ne = _node()
        with (
            patch("cuemsengine.cues.ActionHandler.ACTION_HANDLER._default_result_sink"),
            patch.object(ne, "_notify_stop_project") as notify,
        ):
            ne._action_result_sink(
                {
                    "action_type": "stop_project",
                    "status": "applied",
                    "target_id": None,
                    "origin_cue_id": "cue-1",
                }
            )
        notify.assert_called_once_with("cue-1")

    def test_ignores_a_rejected_stop_project(self):
        ne = _node()
        with (
            patch("cuemsengine.cues.ActionHandler.ACTION_HANDLER._default_result_sink"),
            patch.object(ne, "_notify_stop_project") as notify,
        ):
            ne._action_result_sink(
                {"action_type": "stop_project", "status": "rejected"}
            )
        notify.assert_not_called()


class TestChainBreak:
    def test_a_stop_project_cue_breaks_the_chain(self):
        from cuemsengine.cues.CueHandler import CueHandler

        cue = ActionCue({"action_target": "", "action_type": "stop_project"})
        assert CueHandler._chain_continues(cue) is False

    @pytest.mark.parametrize("action", ["play", "stop", "enable", "go_to"])
    def test_other_action_cues_continue(self, action):
        from cuemsengine.cues.CueHandler import CueHandler

        cue = ActionCue({"action_target": "", "action_type": action})
        assert CueHandler._chain_continues(cue) is True

    def test_media_cues_continue(self):
        from cuemsengine.cues.CueHandler import CueHandler

        assert CueHandler._chain_continues(AudioCue()) is True
