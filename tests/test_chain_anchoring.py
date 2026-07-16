# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Increment 2 — chain timeline anchoring.

Covers the Σ (effective-duration) accumulation that turns prewait/body/postwait
into real MTC-timeline gaps honored identically on every node:
- CueHandler._next_local_fire (the go_threaded fire-walk): non-local ENABLED
  cues advance the timeline (+eff), disabled cues are transparent (+0), the walk
  stops at a chain break and terminates on an all-remote/all-disabled cycle;
- _effective_duration_ms surfaces an enabled-A/V body==0 as an error (silent
  cross-node desync source);
- ActionHandler._handle_play forwards the frozen anchor UNCHANGED (no +eff
  double-count — the frozen arriving there is already the action's slot).
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import ActionCue, AudioCue, VideoCue  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _mtc(ms=5000, framerate=25.0):
    mtc = MagicMock()
    mtc.main_tc.framerate = framerate
    mtc.main_tc.frames = int(round(ms / 1000 * framerate))
    mtc.main_tc.milliseconds_exact = float(ms)
    mtc.main_tc.milliseconds_rounded = ms
    return mtc


def _cue(id, local, enabled, eff, post_go="go", target=None):
    """A minimal chain node. _eff is the value the stubbed
    _effective_duration_ms returns for this cue."""
    return SimpleNamespace(
        id=id,
        _local=local,
        enabled=enabled,
        _eff=eff,
        post_go=post_go,
        _target_object=target,
    )


def _fire(head_cue, arrival):
    """Call _next_local_fire with a fake self whose _effective_duration_ms
    returns each cue's _eff — isolates the walk logic from duration math."""
    fake = SimpleNamespace(_effective_duration_ms=lambda c: c._eff)
    return CueHandler._next_local_fire(fake, head_cue, arrival)


class TestNextLocalFire:
    def test_immediate_local_target(self):
        b = _cue("B", local=True, enabled=True, eff=999)
        a = _cue("A", local=True, enabled=True, eff=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is b
        assert arrival == 1100  # 1000 + eff(A)

    def test_non_local_enabled_advances_timeline(self):
        c = _cue("C", local=True, enabled=True, eff=999)
        b = _cue("B", local=False, enabled=True, eff=200, target=c)
        a = _cue("A", local=True, enabled=True, eff=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is c
        assert arrival == 1300  # 1000 + eff(A)=100 + eff(B)=200

    def test_disabled_is_transparent(self):
        c = _cue("C", local=True, enabled=True, eff=999)
        b = _cue("B", local=True, enabled=False, eff=200, target=c)
        a = _cue("A", local=True, enabled=True, eff=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is c
        assert arrival == 1100  # disabled B adds 0

    def test_mixed_skip(self):
        d = _cue("D", local=True, enabled=True, eff=999)
        c = _cue("C", local=False, enabled=True, eff=300, target=d)  # +300
        b = _cue("B", local=True, enabled=False, eff=200, target=c)  # +0
        a = _cue("A", local=True, enabled=True, eff=100, target=b)  # +100
        cue, arrival = _fire(a, 1000)
        assert cue is d
        assert arrival == 1400  # 1000 + 100 + 0 + 300

    def test_chain_break_returns_none(self):
        b = _cue("B", local=False, enabled=True, eff=200, post_go="pause")
        a = _cue("A", local=True, enabled=True, eff=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is None
        assert arrival == 1100  # arrival of B, but nothing local to fire

    def test_end_of_chain_returns_none(self):
        a = _cue("A", local=True, enabled=True, eff=100, target=None)
        cue, arrival = _fire(a, 1000)
        assert cue is None
        assert arrival == 1100

    def test_all_remote_cycle_terminates(self):
        # Self-referential non-local chain — must hit the 1024 bound, not spin.
        b = _cue("B", local=False, enabled=True, eff=0, post_go="go")
        b._target_object = b
        a = _cue("A", local=True, enabled=True, eff=100, target=b)
        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            cue, _ = _fire(a, 1000)
        assert cue is None
        log.error.assert_called_once()


class TestEffectiveDurationBodyZero:
    def test_enabled_av_zero_body_logs_error(self):
        cue = Mock(spec=AudioCue)
        cue.id = "a"
        cue.enabled = True
        cue.media = None  # → body 0
        cue.prewait = SimpleNamespace(milliseconds_exact=0.0)
        cue.postwait = SimpleNamespace(milliseconds_exact=0.0)
        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            CueHandler._effective_duration_ms(cue)
        log.error.assert_called_once()

    def test_disabled_av_zero_body_quiet(self):
        cue = Mock(spec=VideoCue)
        cue.id = "v"
        cue.enabled = False
        cue.media = None
        cue.prewait = SimpleNamespace(milliseconds_exact=0.0)
        cue.postwait = SimpleNamespace(milliseconds_exact=0.0)
        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            CueHandler._effective_duration_ms(cue)
        log.error.assert_not_called()


class TestHandlePlayForwardsFrozen:
    def test_frozen_forwarded_unchanged(self):
        # _handle_play must pass the frozen anchor straight through — the value
        # arriving here is already the action's slot; +eff would double-count.
        from cuemsengine.cues import ActionHandler as AH

        ch = Mock()
        target = Mock()
        target.id = "t"
        mtc = Mock()
        with patch.object(AH, "_ready_action_target", return_value=None):
            AH._handle_play(ch, Mock(), target, mtc, 4242.0)
        ch.go.assert_called_once_with(target, mtc, 4242.0)


class TestRunActionCueStampsStartMtc:
    """run_actionCue must stamp _start_mtc (from frozen or live MTC) so
    _reveal_wait gates the action at its slot. Also proves the CTimecode(...)
    kwargs used to build it are a real constructor signature, not invented."""

    def test_frozen_branch(self):
        from cuemsengine.cues.run_cue import run_cue

        cue = Mock(spec=ActionCue)
        cue.id = "a"
        run_cue(cue, _mtc(), 6000.0)  # frozen
        assert abs(cue._start_mtc.milliseconds_exact - 6000.0) < 40  # ≤1 frame @25fps

    def test_live_branch(self):
        from cuemsengine.cues.run_cue import run_cue

        cue = Mock(spec=ActionCue)
        cue.id = "a"
        mtc = _mtc(ms=8000)  # frames = 200 @25fps
        run_cue(cue, mtc)  # frozen None → live
        assert cue._start_mtc.frames == 200


def _go_threaded_cue(
    prewait_ms=1000, postwait_ms=0, post_go="pause", go_gen=7, cur_gen=7, target=None
):
    return (
        SimpleNamespace(
            id="c",
            _local=True,
            _stop_requested=False,
            _go_generation=cur_gen,
            post_go=post_go,
            _target_object=target,
            prewait=CTimecode(framerate=25, start_seconds=prewait_ms / 1000),
            postwait=CTimecode(framerate=25, start_seconds=postwait_ms / 1000),
        ),
        go_gen,
    )


class TestGoThreadedAnchoring:
    """go_threaded: single prewait application point + superseded-generation
    guard on the outward postwait/fire (change-review Finding 1)."""

    def _ch(self):
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        ch.communications_thread = MagicMock()
        ch.disarm = MagicMock()
        ch.go = MagicMock(return_value=None)  # None → no wait_for_cue loop
        ch._reveal_wait = MagicMock(return_value="reached")
        ch._next_local_fire = MagicMock(return_value=(None, 0.0))
        return ch

    def test_start_ms_is_arrival_plus_prewait(self):
        ch = self._ch()
        cue, go_gen = _go_threaded_cue(prewait_ms=1000)
        mtc = _mtc()
        with (
            patch("cuemsengine.cues.CueHandler.run_cue") as run_cue,
            patch("cuemsengine.cues.CueHandler.reveal_cue") as reveal_cue,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=5000.0, go_gen=go_gen)
        # arrival 5000 + prewait 1000 = start 6000, passed to run_cue AND reveal
        assert run_cue.call_args.args[2] == 6000.0
        assert reveal_cue.call_args.args[2] == 6000.0
        ch.communications_thread.add_cue.assert_any_call("c", "6000.0", timeout=0.1)

    def test_fires_next_at_returned_arrival(self):
        ch = self._ch()
        nxt = SimpleNamespace(id="n")
        ch._next_local_fire = MagicMock(return_value=(nxt, 9000.0))
        cue, go_gen = _go_threaded_cue(post_go="go", target=SimpleNamespace(id="t"))
        mtc = _mtc()
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=5000.0, go_gen=go_gen)
        ch.go.assert_called_once_with(nxt, mtc, 9000.0)

    def test_superseded_generation_does_not_fire(self):
        # go_gen=7 but the cue's live generation is 8 (a fresh GO/reload took
        # over during the reveal wait). This stale thread must NOT fire the chain.
        ch = self._ch()
        ch._reveal_wait = MagicMock(return_value="stopped")
        ch._next_local_fire = MagicMock(return_value=(SimpleNamespace(id="n"), 9000.0))
        cue, go_gen = _go_threaded_cue(
            post_go="go", cur_gen=8, go_gen=7, target=SimpleNamespace(id="t")
        )
        mtc = _mtc()
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=5000.0, go_gen=go_gen)
        ch._next_local_fire.assert_not_called()
        ch.go.assert_not_called()
