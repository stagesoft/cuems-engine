# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Coverage for the MTC-gated reveal mechanism (run_cue setup-held + reveal_cue
+ CueHandler._reveal_wait). Guards the regressions found reviewing the split:
- a CueList used as a chain target must reveal its first enabled child;
- reveal_audioCue must no-op if run_audioCue aborted setup before /offset.
"""
import sys
from unittest.mock import Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import VideoCue, AudioCue, ActionCue, CueList  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402
from cuemsengine.cues.run_cue import reveal_cue  # noqa: E402
from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _video(layer="L1"):
    cue = Mock(spec=VideoCue)
    cue.id = "v"
    cue._layer_ids = [layer]
    cue._osc = Mock()
    cue.enabled = True
    return cue


class TestRevealCue:
    def test_video_reveal_sends_visible(self):
        cue = _video()
        reveal_cue(cue, Mock())
        cue._osc.set_value.assert_any_call("/videocomposer/layer/L1/visible", 1)

    def test_action_reveal_executes(self):
        cue = Mock(spec=ActionCue)
        mtc = Mock()
        with patch("cuemsengine.cues.ActionHandler.ACTION_HANDLER") as ah:
            reveal_cue(cue, mtc, 123.0)
            ah.execute_action.assert_called_once_with(cue, mtc, 123.0)

    def test_cuelist_target_reveals_first_enabled_child(self):
        # HIGH-severity fix: a held child under a CueList target must be revealed.
        child = _video("LC")
        cl = Mock(spec=CueList)
        cl.contents = [child]
        reveal_cue(cl, Mock())
        child._osc.set_value.assert_any_call("/videocomposer/layer/LC/visible", 1)

    def test_audio_reveal_skips_when_setup_aborted(self):
        # MEDIUM fix: run_audioCue aborted before /offset -> reveal must no-op.
        cue = Mock(spec=AudioCue)
        cue.id = "a"
        cue._osc = Mock()
        cue._reveal_ready = False
        reveal_cue(cue, Mock())
        cue._osc.set_value.assert_not_called()

    def test_audio_reveal_follows_when_ready(self):
        cue = Mock(spec=AudioCue)
        cue.id = "a"
        cue._osc = Mock()
        cue._reveal_ready = True
        cue._start_mtc = CTimecode("00:00:02.000")
        reveal_cue(cue, Mock())
        cue._osc.set_value.assert_any_call("/mtcfollow", 1)


class TestRevealWait:
    def test_no_start_mtc_reaches_immediately(self):
        cue = Mock(spec=ActionCue)  # no _start_mtc -> immediate
        assert CueHandler._reveal_wait(None, cue, Mock(), 0) == "reached"

    def test_stop_requested_returns_stopped(self):
        cue = Mock(spec=VideoCue)
        cue._start_mtc = CTimecode("01:00:00.000")  # far future
        cue._stop_requested = True
        cue._go_generation = 0
        mtc = Mock()
        mtc.main_tc.milliseconds_exact = 0
        assert CueHandler._reveal_wait(None, cue, mtc, 0) == "stopped"

    def test_generation_change_returns_stopped(self):
        cue = Mock(spec=VideoCue)
        cue._start_mtc = CTimecode("01:00:00.000")
        cue._stop_requested = False
        cue._go_generation = 5  # != go_gen passed below
        mtc = Mock()
        mtc.main_tc.milliseconds_exact = 0
        assert CueHandler._reveal_wait(None, cue, mtc, 0) == "stopped"

    def test_reaches_when_mtc_past_start(self):
        cue = Mock(spec=VideoCue)
        cue._start_mtc = CTimecode("00:00:01.000")
        cue._stop_requested = False
        cue._go_generation = 0
        mtc = Mock()
        mtc.main_tc.milliseconds_exact = 5000  # already past start
        assert CueHandler._reveal_wait(None, cue, mtc, 0) == "reached"
