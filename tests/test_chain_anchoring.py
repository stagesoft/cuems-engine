# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Increment 2 — chain timeline anchoring.

Covers the Σ (chain-advance) accumulation that turns prewait into a real
MTC-timeline gap honored identically on every node. Auto continue triggers the
WHOLE chain at once, so the advance is **zero**: every cue arrives at the shared
trigger and plays at `trigger + its own prewait` (2026-08-14, ClickUp 869ej3cc8
— see TestChainAdvanceIsZero / TestMedinaRegression below). The walk mechanics
are still exercised against a stubbed advance so they stay independent of that
value:
- CueHandler._next_local_fire (the go_threaded fire-walk): non-local ENABLED
  cues advance the timeline (+_chain_advance_ms), disabled cues are transparent
  (+0), the walk stops at a chain break and terminates on an
  all-remote/all-disabled cycle;
- _effective_duration_ms surfaces an enabled-A/V body==0 as an error (silent
  cross-node desync source);
- ActionHandler._handle_play forwards the frozen anchor UNCHANGED via go_from
  (no +advance double-count — the frozen arriving there is already the
  action's slot).
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import ActionCue, AudioCue, DmxCue, VideoCue  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _mtc(ms=5000, framerate=25.0):
    mtc = MagicMock()
    mtc.main_tc.framerate = framerate
    mtc.main_tc.frames = int(round(ms / 1000 * framerate))
    mtc.main_tc.milliseconds_exact = float(ms)
    mtc.main_tc.milliseconds_rounded = ms
    return mtc


def _cue(id, local, enabled, adv, post_go="go", target=None):
    """A minimal chain node. _adv is the value the stubbed
    _chain_advance_ms returns for this cue (prewait+postwait slot)."""
    return SimpleNamespace(
        id=id,
        _local=local,
        enabled=enabled,
        _adv=adv,
        post_go=post_go,
        _target_object=target,
    )


def _fire(head_cue, arrival):
    """Call _next_local_fire with a fake self whose _chain_advance_ms
    returns each cue's _adv — isolates the walk logic from duration math."""
    fake = SimpleNamespace(_chain_advance_ms=lambda c: c._adv)
    return CueHandler._next_local_fire(fake, head_cue, arrival)


class TestNextLocalFire:
    def test_immediate_local_target(self):
        b = _cue("B", local=True, enabled=True, adv=999)
        a = _cue("A", local=True, enabled=True, adv=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is b
        assert arrival == 1100  # 1000 + adv(A)

    def test_non_local_enabled_advances_timeline(self):
        c = _cue("C", local=True, enabled=True, adv=999)
        b = _cue("B", local=False, enabled=True, adv=200, target=c)
        a = _cue("A", local=True, enabled=True, adv=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is c
        assert arrival == 1300  # 1000 + adv(A)=100 + adv(B)=200

    def test_disabled_is_transparent(self):
        c = _cue("C", local=True, enabled=True, adv=999)
        b = _cue("B", local=True, enabled=False, adv=200, target=c)
        a = _cue("A", local=True, enabled=True, adv=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is c
        assert arrival == 1100  # disabled B adds 0

    def test_mixed_skip(self):
        d = _cue("D", local=True, enabled=True, adv=999)
        c = _cue("C", local=False, enabled=True, adv=300, target=d)  # +300
        b = _cue("B", local=True, enabled=False, adv=200, target=c)  # +0
        a = _cue("A", local=True, enabled=True, adv=100, target=b)  # +100
        cue, arrival = _fire(a, 1000)
        assert cue is d
        assert arrival == 1400  # 1000 + 100 + 0 + 300

    def test_chain_break_returns_none(self):
        b = _cue("B", local=False, enabled=True, adv=200, post_go="pause")
        a = _cue("A", local=True, enabled=True, adv=100, target=b)
        cue, arrival = _fire(a, 1000)
        assert cue is None
        assert arrival == 1100  # arrival of B, but nothing local to fire

    def test_end_of_chain_returns_none(self):
        a = _cue("A", local=True, enabled=True, adv=100, target=None)
        cue, arrival = _fire(a, 1000)
        assert cue is None
        assert arrival == 1100

    def test_all_remote_cycle_terminates(self):
        # Self-referential non-local chain — must hit the 1024 bound, not spin.
        b = _cue("B", local=False, enabled=True, adv=0, post_go="go")
        b._target_object = b
        a = _cue("A", local=True, enabled=True, adv=100, target=b)
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
        # _handle_play must pass the frozen anchor straight through go_from —
        # the value arriving here is already the action's slot; +advance would
        # double-count.
        from cuemsengine.cues import ActionHandler as AH

        ch = Mock()
        target = Mock()
        target.id = "t"
        target._local = True
        target.enabled = True
        target.loaded = True
        mtc = Mock()
        with patch.object(AH, "_ready_action_target", return_value=None):
            AH._handle_play(ch, Mock(), target, mtc, 4242.0)
        ch.go_from.assert_called_once_with(target, mtc, 4242.0)
        ch.go.assert_not_called()


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


# ---------------------------------------------------------------------------
# Auto continue == one common trigger (Medina del Campo, 869ej3cc8)
# ---------------------------------------------------------------------------


def _wait_cue(prewait_s=0.0, postwait_s=0.0, post_go="go", **kw):
    """A chain node carrying REAL CTimecode waits — for the tests that must
    exercise the actual _chain_advance_ms, not a stub."""
    return SimpleNamespace(
        prewait=CTimecode(framerate=25, start_seconds=prewait_s),
        postwait=CTimecode(framerate=25, start_seconds=postwait_s),
        post_go=post_go,
        **kw,
    )


class TestChainAdvanceIsZero:
    """Auto continue triggers the whole chain at once: a cue's own waits must
    NOT push the following cues' arrival. The advance is zero — prewait is a
    per-cue offset from the common trigger, and postwait does not gate a chain
    whose pointer has already advanced.
    """

    def test_prewait_does_not_advance_the_chain(self):
        assert CueHandler._chain_advance_ms(_wait_cue(prewait_s=35.0)) == 0.0

    def test_postwait_does_not_advance_the_chain(self):
        assert CueHandler._chain_advance_ms(_wait_cue(postwait_s=5.0)) == 0.0

    def test_both_waits_together_still_zero(self):
        cue = _wait_cue(prewait_s=95.0, postwait_s=12.0)
        assert CueHandler._chain_advance_ms(cue) == 0.0

    def test_independent_of_cue_type(self):
        # DmxCue was the reported case, but the rule is type-agnostic: the same
        # prewait on a video cue must behave identically (plan §3).
        dmx = Mock(spec=DmxCue)
        dmx.prewait = CTimecode(framerate=25, start_seconds=35.0)
        dmx.postwait = CTimecode(framerate=25, start_seconds=0.0)
        vid = Mock(spec=VideoCue)
        vid.prewait = CTimecode(framerate=25, start_seconds=35.0)
        vid.postwait = CTimecode(framerate=25, start_seconds=0.0)
        assert CueHandler._chain_advance_ms(dmx) == CueHandler._chain_advance_ms(vid)
        assert CueHandler._chain_advance_ms(dmx) == 0.0


class TestMedinaRegression:
    """The field case: DMX cues authored with prewait as ABSOLUTE offsets from
    GO (Castillo Medina del Campo, cupula2, project medina_cupula_2_torre-001).

    Authored 5/35/65/95/380 s; before the fix the engine played 5/40/105/200/580
    because each cue's prewait advanced the whole chain.
    """

    PREWAITS = [5.0, 35.0, 65.0, 95.0, 380.0]

    def _chain(self):
        # Botella 1..4 auto-continue; "Off Botella 4" breaks the chain (pause).
        post_gos = ["go", "go", "go", "go", "pause"]
        cues = [
            _wait_cue(
                prewait_s=p,
                post_go=pg,
                id=f"botella{i}",
                _local=True,
                enabled=True,
                _target_object=None,
            )
            for i, (p, pg) in enumerate(zip(self.PREWAITS, post_gos))
        ]
        for a, b in zip(cues, cues[1:]):
            a._target_object = b
        return cues

    def test_every_cue_starts_at_its_own_prewait(self):
        cues = self._chain()
        trigger = 0.0
        arrival = trigger
        starts = []
        for cue in cues:
            starts.append(arrival + cue.prewait.milliseconds_exact)
            if cue.post_go != "go":
                break
            arrival += CueHandler._chain_advance_ms(cue)
        assert starts == [p * 1000 for p in self.PREWAITS]

    def test_walk_keeps_every_arrival_at_the_trigger(self):
        # _next_local_fire must hand each following cue the SAME arrival.
        cues = self._chain()
        arrivals = []
        cue, arrival = CueHandler._next_local_fire(CueHandler, cues[0], 0.0)
        while cue is not None:
            arrivals.append(arrival)
            if cue.post_go != "go":
                break
            cue, arrival = CueHandler._next_local_fire(CueHandler, cue, arrival)
        assert arrivals == [0.0, 0.0, 0.0, 0.0]

    def test_skipped_non_local_cue_does_not_shift_later_local_segment(self):
        # A-B-A across nodes (plan §5.5 / review F6): under one common trigger a
        # skipped non-local cue contributes nothing, so this node's SECOND local
        # segment still anchors at the trigger.
        c = _wait_cue(prewait_s=9.0, id="C", _local=True, enabled=True)
        b = _wait_cue(
            prewait_s=60.0, id="B", _local=False, enabled=True, _target_object=c
        )
        a = _wait_cue(
            prewait_s=5.0, id="A", _local=True, enabled=True, _target_object=b
        )
        cue, arrival = CueHandler._next_local_fire(CueHandler, a, 0.0)
        assert cue is c
        assert arrival == 0.0


class TestLateDispatchIsLogged:
    """Known Phase-1 gap, made visible instead of silent (plan §5.3).

    Cue k+1 is dispatched at start(k)+postwait(k); its anchor is
    trigger+prewait(k+1). A chain whose prewaits run BACKWARDS therefore
    dispatches a cue after its own anchor, and it fires late. Phase 2 reorders
    the dispatch; until then the engine must say so.
    """

    def _ch(self):
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        ch.communications_thread = MagicMock()
        ch.disarm = MagicMock()
        ch.go = MagicMock(return_value=None)
        ch._reveal_wait = MagicMock(return_value="reached")
        ch._next_local_fire = MagicMock(return_value=(None, 0.0))
        return ch

    def _run(self, prewait_ms, live_mtc_ms, arrival_ms):
        ch = self._ch()
        cue, go_gen = _go_threaded_cue(prewait_ms=prewait_ms, post_go="go")
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
        ):
            ch.go_threaded(
                cue, _mtc(ms=live_mtc_ms), frozen_mtc_ms=arrival_ms, go_gen=go_gen
            )
        return log

    def test_warns_when_dispatched_after_its_anchor(self):
        # anchor = 0 + 10s = 10000, but live MTC is already at 100000.
        log = self._run(prewait_ms=10000, live_mtc_ms=100000, arrival_ms=0.0)
        assert log.warning.called
        msg = " ".join(str(c) for c in log.warning.call_args_list)
        assert "late" in msg.lower()

    def test_quiet_when_anchor_is_still_ahead(self):
        # anchor = 0 + 95s = 95000, live MTC 65000 → on time, no warning.
        log = self._run(prewait_ms=95000, live_mtc_ms=65000, arrival_ms=0.0)
        assert not log.warning.called


class TestPostwaitStillHoldsIllumination:
    """postwait stops advancing the CHAIN but keeps its illumination role
    (plan §4.1 / review F3): the sleep in go_threaded is the sole mechanism
    producing Auto continue's `prewait + max(body, postwait)` highlight —
    loop_cue never reads postwait. This guards it against removal.
    """

    def test_auto_continue_postwait_sleep_is_preserved(self):
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        ch.communications_thread = MagicMock()
        ch.disarm = MagicMock()
        ch.go = MagicMock(return_value=None)
        ch._reveal_wait = MagicMock(return_value="reached")
        ch._next_local_fire = MagicMock(return_value=(None, 0.0))
        cue, go_gen = _go_threaded_cue(prewait_ms=0, postwait_ms=5000, post_go="go")
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep") as slp,
        ):
            ch.go_threaded(cue, _mtc(), frozen_mtc_ms=0.0, go_gen=go_gen)
        assert slp.call_args_list, "postwait sleep was removed — illumination regresses"
        assert any(abs(c.args[0] - 5.0) < 1e-6 for c in slp.call_args_list)
