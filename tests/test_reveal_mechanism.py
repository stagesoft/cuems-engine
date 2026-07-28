# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Coverage for the MTC-gated reveal mechanism (run_cue setup-held + reveal_cue
+ CueHandler._reveal_wait). Guards the regressions found reviewing the split:
- a CueList used as a chain target must reveal its first enabled child;
- reveal_audioCue must no-op if run_audioCue aborted setup before /offset.
"""

import sys
from unittest.mock import ANY, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import ActionCue, AudioCue, CueList, VideoCue  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CUE_HANDLER  # noqa: E402
from cuemsengine.cues.run_cue import (  # noqa: E402
    reveal_cue,
    reveal_cueList,
    run_cueList,
)


def _video(layer="L1"):
    cue = Mock(spec=VideoCue)
    cue.id = "v"
    cue._layer_ids = [layer]
    cue._osc = Mock()
    cue.enabled = True
    # A cue reaching run/reveal is armed; the CueList guard checks these, and
    # reveal_videoCue itself ignores them. Set so CueList-target reveal tests
    # pass the loaded/_local guard.
    cue.loaded = True
    cue._local = True
    return cue


def _child(loaded=False, local=True, enabled=True, cid="c", layer="LX"):
    """A CueList child double: a spec'd VideoCue mock with the engine-attached
    attributes (loaded/_local/_osc/_layer_ids) the guard and reveal_videoCue read.
    singledispatch dispatches on `__class__`, which spec sets to VideoCue, so a
    real reveal_cue(child) lands in reveal_videoCue.
    """
    cue = Mock(spec=VideoCue)
    cue.id = cid
    cue.enabled = enabled
    cue._local = local
    cue.loaded = loaded
    cue._osc = Mock()
    cue._layer_ids = [layer]
    return cue


def _cuelist(children, cid="cl"):
    cl = Mock(spec=CueList)
    cl.id = cid
    cl.contents = children
    return cl


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
        assert CUE_HANDLER._reveal_wait(cue, Mock(), 0) == "reached"

    def test_stop_requested_returns_stopped(self):
        cue = Mock(spec=VideoCue)
        cue._start_mtc = CTimecode("01:00:00.000")  # far future
        cue._stop_requested = True
        cue._go_generation = 0
        mtc = Mock()
        mtc.main_tc.milliseconds_exact = 0
        assert CUE_HANDLER._reveal_wait(cue, mtc, 0) == "stopped"

    def test_generation_change_returns_stopped(self):
        cue = Mock(spec=VideoCue)
        cue._start_mtc = CTimecode("01:00:00.000")
        cue._stop_requested = False
        cue._go_generation = 5  # != go_gen passed below
        mtc = Mock()
        mtc.main_tc.milliseconds_exact = 0
        assert CUE_HANDLER._reveal_wait(cue, mtc, 0) == "stopped"

    def test_reaches_when_mtc_past_start(self):
        cue = Mock(spec=VideoCue)
        cue._start_mtc = CTimecode("00:00:01.000")
        cue._stop_requested = False
        cue._go_generation = 0
        mtc = Mock()
        mtc.main_tc.milliseconds_exact = 5000  # already past start
        assert CUE_HANDLER._reveal_wait(cue, mtc, 0) == "reached"


class TestRunCueListRearm:
    """run_cueList gives its first-enabled child go()'s re-arm safety net
    (869e2dat9). CUE_HANDLER is patched at its definition site because
    _ensure_child_loaded imports it lazily (from .CueHandler import CUE_HANDLER)."""

    def test_loaded_child_dispatches_without_rearm(self):
        child = _child(loaded=True)
        cl = _cuelist([child])
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER") as ch, patch(
            "cuemsengine.cues.run_cue.run_cue"
        ) as rc:
            run_cueList(cl, Mock(), 100.0)
        ch.arm.assert_not_called()
        rc.assert_called_once_with(child, ANY, 100.0)

    def test_unloaded_local_child_rearmed_then_dispatched(self):
        child = _child(loaded=False)

        def _arm(c, init=False):
            c.loaded = True  # successful re-arm

        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER") as ch, patch(
            "cuemsengine.cues.run_cue.run_cue"
        ) as rc:
            ch.arm.side_effect = _arm
            run_cueList(_cuelist([child]), Mock(), 100.0)
        ch.arm.assert_called_once_with(child, init=True)
        rc.assert_called_once_with(child, ANY, 100.0)

    def test_rearm_leaves_unloaded_skips_dispatch(self):
        child = _child(loaded=False)
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER") as ch, patch(
            "cuemsengine.cues.run_cue.run_cue"
        ) as rc:
            # arm() is a no-op mock -> child.loaded stays False
            run_cueList(_cuelist([child]), Mock(), 100.0)
        ch.arm.assert_called_once_with(child, init=True)
        rc.assert_not_called()

    def test_rearm_raising_is_contained(self):
        # arm() wraps arm_cue in try/FINALLY: a raise would otherwise kill the
        # parent CueList's go_threaded thread. _ensure_child_loaded must swallow.
        child = _child(loaded=False)
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER") as ch, patch(
            "cuemsengine.cues.run_cue.run_cue"
        ) as rc:
            ch.arm.side_effect = ValueError("boom")
            run_cueList(_cuelist([child]), Mock(), 100.0)  # must NOT raise
        ch.arm.assert_called_once_with(child, init=True)
        rc.assert_not_called()

    def test_nonlocal_child_dispatched_without_rearm(self):
        # Non-local child is owned by another node; guard leaves dispatch as-is.
        child = _child(loaded=False, local=False)
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER") as ch, patch(
            "cuemsengine.cues.run_cue.run_cue"
        ) as rc:
            run_cueList(_cuelist([child]), Mock(), 100.0)
        ch.arm.assert_not_called()
        rc.assert_called_once_with(child, ANY, 100.0)

    def test_no_enabled_child_is_noop(self):
        child = _child(enabled=False)
        cl = _cuelist([child])
        with patch("cuemsengine.cues.CueHandler.CUE_HANDLER") as ch, patch(
            "cuemsengine.cues.run_cue.run_cue"
        ) as rc:
            run_cueList(cl, Mock(), 100.0)
            run_cueList(_cuelist([]), Mock(), 100.0)  # empty contents
        ch.arm.assert_not_called()
        rc.assert_not_called()


class TestRevealCueListGuard:
    """reveal_cueList reveals the first-enabled child but SKIPS (never re-arms)
    a local child that never got set up (869e2dat9)."""

    def test_loaded_child_revealed(self):
        child = _child(loaded=True, layer="LR")
        reveal_cueList(_cuelist([child]), Mock())
        child._osc.set_value.assert_any_call("/videocomposer/layer/LR/visible", 1)

    def test_unloaded_local_child_skips_reveal(self):
        child = _child(loaded=False, local=True)
        reveal_cueList(_cuelist([child]), Mock())
        child._osc.set_value.assert_not_called()

    def test_nonlocal_unloaded_child_revealed(self):
        # Parity with run_cueList: non-local children keep existing dispatch.
        child = _child(loaded=False, local=False, layer="LN")
        reveal_cueList(_cuelist([child]), Mock())
        child._osc.set_value.assert_any_call("/videocomposer/layer/LN/visible", 1)

    def test_no_enabled_child_is_noop(self):
        child = _child(enabled=False)
        reveal_cueList(_cuelist([child]), Mock())
        child._osc.set_value.assert_not_called()
