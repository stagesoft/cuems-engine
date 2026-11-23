# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Increment 2 — chain timeline anchoring, under the pass (1amfwm7jnqf).

Covers the Σ (chain-advance) accumulation that turns prewait into a real
MTC-timeline gap honored identically on every node. Since 1amfwm7jnqf an
Auto-continue chain is "en serie" (`sequential`): a cue's prewait and postwait
push the cues after it, `arrival(k+1) = arrival(k) + prewait(k) + postwait(k)`.
The 2026-08-14 rule (ClickUp 869ej3cc8), every cue at the shared trigger, is
kept as the "en paralelo" (`parallel`) mode: TestChainAdvanceIsZero /
TestMedinaRegression run under it, beside their `sequential` twins.
- CueHandler._next_local_fire(cue, pass_) reads the pass's layout: the next
  local cue after `cue`, enabled or not (a disabled cue keeps its place and its
  waits, D26: it gets a silent thread), with its layout arrival;
- _effective_duration_ms surfaces an enabled-A/V body==0 as an error (silent
  cross-node desync source);
- ActionHandler._handle_play forwards the frozen anchor UNCHANGED via go_from
  (no +advance double-count — the frozen arriving there is already the
  action's slot).

Plan: cuems-RELATIONS Plans/2026-11-18-autocontinue-cumulative-waits.md.
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

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


def _cue(id, local, enabled, post_go="go", target=None):
    """A minimal chain node; its place comes from the pass's layout."""
    return SimpleNamespace(
        id=id,
        _local=local,
        enabled=enabled,
        post_go=post_go,
        _target_object=target,
    )


def _pass(epoch, anchor_ms, layout, root_seq=0, mode="sequential"):
    """A chain_pass.Pass."""
    from cuemsengine.cues.chain_pass import Pass

    return Pass(
        epoch=epoch,
        anchor_ms=anchor_ms,
        layout=list(layout),
        root_seq=root_seq,
        mode=mode,
    )


def _layout(entry, anchor_ms, mode):
    from cuemsengine.cues import chain_pass

    return chain_pass.layout(entry, anchor_ms, mode)


def _fire(cue, pass_):
    """_next_local_fire on a bare handler: it reads only the pass."""
    return CueHandler._next_local_fire(object.__new__(CueHandler), cue, pass_)


class TestNextLocalFire:
    """The next local cue of my pass's layout, with its arrival. The arrivals
    are the layout's; nothing is added on the way."""

    def test_immediate_local_target(self):
        b = _cue("B", local=True, enabled=True)
        a = _cue("A", local=True, enabled=True, target=b)
        p = _pass(1, 1000.0, [(a, 1000.0), (b, 1100.0)])
        cue, arrival = _fire(a, p)
        assert cue is b
        assert arrival == 1100.0

    def test_a_non_local_cue_is_walked_past(self):
        c = _cue("C", local=True, enabled=True)
        b = _cue("B", local=False, enabled=True, target=c)
        a = _cue("A", local=True, enabled=True, target=b)
        p = _pass(1, 1000.0, [(a, 1000.0), (b, 1100.0), (c, 1300.0)])
        cue, arrival = _fire(a, p)
        assert cue is c
        assert arrival == 1300.0  # C's own place, not recomputed

    def test_a_disabled_local_cue_is_not_skipped(self):
        """S07/S08 (D26): a disabled cue keeps its place and its waits; its
        node gives it a silent thread, so the walk stops at it."""
        c = _cue("C", local=True, enabled=True)
        b = _cue("B", local=True, enabled=False, target=c)
        a = _cue("A", local=True, enabled=True, target=b)
        p = _pass(1, 1000.0, [(a, 1000.0), (b, 1100.0), (c, 1300.0)])
        cue, arrival = _fire(a, p)
        assert cue is b
        assert arrival == 1100.0
        cue, arrival = _fire(b, p)
        assert cue is c
        assert arrival == 1300.0

    def test_mixed_remote_and_disabled(self):
        d = _cue("D", local=True, enabled=True)
        c = _cue("C", local=False, enabled=True, target=d)
        b = _cue("B", local=False, enabled=False, target=c)
        a = _cue("A", local=True, enabled=True, target=b)
        p = _pass(1, 1000.0, [(a, 1000.0), (b, 1100.0), (c, 1100.0), (d, 1400.0)])
        cue, arrival = _fire(a, p)
        assert cue is d
        assert arrival == 1400.0

    def test_the_end_of_the_layout_returns_none(self):
        b = _cue("B", local=False, enabled=True, post_go="pause")
        a = _cue("A", local=True, enabled=True, target=b)
        p = _pass(1, 1000.0, [(a, 1000.0), (b, 1100.0)])
        cue, _ = _fire(a, p)
        assert cue is None

    def test_a_single_cue_pass_returns_none(self):
        a = _cue("A", local=True, enabled=True, target=None)
        cue, _ = _fire(a, _pass(1, 1000.0, [(a, 1000.0)]))
        assert cue is None

    def test_an_all_remote_cycle_ends_with_the_layout(self):
        """The layout never holds a cue twice (chain_pass.layout stops before a
        cue it would reach a second time), so the walk cannot spin."""
        b = _wait_cue(id="B", _local=False, enabled=True)
        b._target_object = b
        a = _wait_cue(id="A", _local=True, enabled=True, _target_object=b)
        layout = _layout(a, 1000.0, "sequential")
        assert [c for c, _ in layout] == [a, b]
        cue, _ = _fire(a, _pass(1, 1000.0, layout))
        assert cue is None


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
            # A cue only reaches go_threaded armed: go() arms a fresh entry
            # before spawning, and a continuation arms itself on entry.
            loaded=True,
            _stop_requested=False,
            _go_generation=cur_gen,
            _revealed=False,
            post_go=post_go,
            _target_object=target,
            prewait=CTimecode(framerate=25, start_seconds=prewait_ms / 1000),
            postwait=CTimecode(framerate=25, start_seconds=postwait_ms / 1000),
        ),
        go_gen,
    )


class _AdvancingMtc:
    """MTC that moves forward by the duration of each sleep.

    go_threaded now parks until `start - _RUN_AHEAD_MS` before its held setup,
    so a test whose timeline never moves would spin forever on any anchor that
    is still ahead.
    """

    def __init__(self, ms=0.0):
        self.main_tc = SimpleNamespace(
            milliseconds_exact=float(ms),
            milliseconds_rounded=int(ms),
            framerate=25.0,
            frames=int(round(ms / 1000 * 25)),
        )

    def advance(self, seconds):
        self.main_tc.milliseconds_exact += float(seconds) * 1000.0
        self.main_tc.milliseconds_rounded = int(self.main_tc.milliseconds_exact)


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
        p = _pass(3, 5000.0, [(cue, 5000.0), (nxt, 9000.0)])
        mtc = _mtc()
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=5000.0, go_gen=go_gen, pass_=p)
        # the pass is carried unchanged into the continuation, so every cue in
        # the chain is dispatched under one pass
        ch._next_local_fire.assert_called_once_with(cue, p)
        ch.go.assert_called_once_with(nxt, mtc, 9000.0, pass_=p, arm_epoch=None)

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

    def test_a_disabled_cue_passes_silent_and_still_unrolls(self):
        """S07 (D26): a disabled cue is the same cue without output. Its thread
        sets nothing up, lights nothing and reveals nothing; it waits for its
        start, says `passed silent`, and the chain behind it is still
        dispatched at its own place in the pass."""
        ch = self._ch()
        nxt = SimpleNamespace(id="n")
        ch._next_local_fire = MagicMock(return_value=(nxt, 15000.0))
        cue, go_gen = _go_threaded_cue(
            prewait_ms=5000, postwait_ms=10000, post_go="go", target=nxt
        )
        cue.enabled = False
        p = _pass(1, 0.0, [(cue, 0.0), (nxt, 15000.0)])
        mtc = _AdvancingMtc(0.0)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue") as run_cue,
            patch("cuemsengine.cues.CueHandler.reveal_cue") as reveal_cue,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=0.0, go_gen=go_gen, pass_=p)
        run_cue.assert_not_called()
        reveal_cue.assert_not_called()
        ch.communications_thread.add_cue.assert_not_called()
        ch.go.assert_called_once_with(nxt, mtc, 15000.0, pass_=p, arm_epoch=None)
        lines = [str(c.args[0]) for c in log.info.call_args_list if c.args]
        assert any(x.startswith("Cue c passed silent at mtc ") for x in lines), lines
        assert mtc.main_tc.milliseconds_exact >= 5000.0, "it waits for its start"


# ---------------------------------------------------------------------------
# The two advance modes: "en serie" (sequential, every Auto-continue chain
# since 1amfwm7jnqf) and "en paralelo" (parallel, the 2026-08-14 rule of
# Medina del Campo, 869ej3cc8, kept with its tests; no production path)
# ---------------------------------------------------------------------------


def _wait_cue(prewait_s=0.0, postwait_s=0.0, post_go="go", **kw):
    """A chain node carrying REAL CTimecode waits — for the tests that must
    exercise the actual _chain_advance_ms, not a stub."""
    kw.setdefault("_target_object", None)
    return SimpleNamespace(
        prewait=CTimecode(framerate=25, start_seconds=prewait_s),
        postwait=CTimecode(framerate=25, start_seconds=postwait_s),
        post_go=post_go,
        **kw,
    )


def _linked(waits, post_gos=None, local=None, enabled=None):
    """Cues with (prewait, postwait) in seconds, linked front to back."""
    n = len(waits)
    post_gos = post_gos or ["go"] * (n - 1) + ["pause"]
    local = local or [True] * n
    enabled = enabled or [True] * n
    cues = [
        _wait_cue(
            prewait_s=pre,
            postwait_s=post,
            post_go=pg,
            id=f"c{i}",
            _local=lo,
            enabled=en,
        )
        for i, ((pre, post), pg, lo, en) in enumerate(
            zip(waits, post_gos, local, enabled)
        )
    ]
    for a, b in zip(cues, cues[1:]):
        a._target_object = b
    return cues


def _starts(layout):
    return [arr + c.prewait.milliseconds_exact for c, arr in layout]


class TestChainAdvanceIsZero:
    """`parallel` ("en paralelo"): a cue's own waits do NOT push the following
    cues' arrival; every cue of the chain shares the trigger."""

    def test_prewait_does_not_advance_the_chain(self):
        cue = _wait_cue(prewait_s=35.0)
        assert CueHandler._chain_advance_ms(cue, mode="parallel") == 0.0

    def test_postwait_does_not_advance_the_chain(self):
        cue = _wait_cue(postwait_s=5.0)
        assert CueHandler._chain_advance_ms(cue, mode="parallel") == 0.0

    def test_both_waits_together_still_zero(self):
        cue = _wait_cue(prewait_s=95.0, postwait_s=12.0)
        assert CueHandler._chain_advance_ms(cue, mode="parallel") == 0.0

    def test_independent_of_cue_type(self):
        # DmxCue was the reported case, but the rule is type-agnostic: the same
        # prewait on a video cue must behave identically (plan §3).
        dmx = Mock(spec=DmxCue)
        dmx.prewait = CTimecode(framerate=25, start_seconds=35.0)
        dmx.postwait = CTimecode(framerate=25, start_seconds=0.0)
        vid = Mock(spec=VideoCue)
        vid.prewait = CTimecode(framerate=25, start_seconds=35.0)
        vid.postwait = CTimecode(framerate=25, start_seconds=0.0)
        a = CueHandler._chain_advance_ms(dmx, mode="parallel")
        assert a == CueHandler._chain_advance_ms(vid, mode="parallel") == 0.0


class TestChainAdvanceIsBothWaits:
    """`sequential` ("en serie"), the mode of every Auto-continue chain: a
    cue adds its prewait and its postwait, enabled or not (D1, D26)."""

    def test_the_default_mode_is_sequential(self):
        cue = _wait_cue(prewait_s=5.0, postwait_s=10.0)
        assert CueHandler._advance_mode(cue) == "sequential"
        assert CueHandler._chain_advance_ms(cue) == 15000.0

    def test_sequential_is_prewait_plus_postwait(self):
        cue = _wait_cue(prewait_s=95.0, postwait_s=12.0)
        assert CueHandler._chain_advance_ms(cue, mode="sequential") == 107000.0

    def test_a_disabled_cue_keeps_its_waits(self):
        cue = _wait_cue(prewait_s=5.0, postwait_s=10.0, enabled=False)
        assert CueHandler._chain_advance_ms(cue) == 15000.0

    def test_independent_of_cue_type(self):
        dmx = Mock(spec=DmxCue)
        dmx.prewait = CTimecode(framerate=25, start_seconds=35.0)
        dmx.postwait = CTimecode(framerate=25, start_seconds=1.0)
        vid = Mock(spec=VideoCue)
        vid.prewait = CTimecode(framerate=25, start_seconds=35.0)
        vid.postwait = CTimecode(framerate=25, start_seconds=1.0)
        a = CueHandler._chain_advance_ms(dmx)
        assert a == CueHandler._chain_advance_ms(vid) == 36000.0

    def test_an_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            CueHandler._chain_advance_ms(_wait_cue(prewait_s=1.0), mode="timed")


class TestIonsChain:
    """The plan's first example, A 0/0, B 5/10, C 2/0, D 3/0 (S01, S06)."""

    WAITS = [(0, 0), (5, 10), (2, 0), (3, 0)]

    def test_sequential(self):
        cues = _linked(self.WAITS)
        layout = _layout(cues[0], 0.0, "sequential")
        assert [arr for _, arr in layout] == [0.0, 0.0, 15000.0, 17000.0]
        assert _starts(layout) == [0.0, 5000.0, 17000.0, 20000.0]

    def test_sequential_with_b_disabled_is_the_same(self):
        """S07: B keeps its place and its waits; only its output is missing."""
        cues = _linked(self.WAITS, enabled=[True, False, True, True])
        layout = _layout(cues[0], 0.0, "sequential")
        assert _starts(layout) == [0.0, 5000.0, 17000.0, 20000.0]

    def test_parallel(self):
        cues = _linked(self.WAITS)
        layout = _layout(cues[0], 0.0, "parallel")
        assert [arr for _, arr in layout] == [0.0] * 4
        assert _starts(layout) == [0.0, 5000.0, 2000.0, 3000.0]


class TestMedinaRegression:
    """The field case: DMX cues authored with prewait as ABSOLUTE offsets from
    GO (Castillo Medina del Campo, cupula2, project medina_cupula_2_torre-001).

    Authored 5/35/65/95/380 s. Under `parallel` (the 2026-08-14 rule) they
    play as authored; under `sequential` (this plan) they play
    5/40/105/200/580, and the show re-authored with relative prewaits
    5/30/30/30/285 plays 5/35/65/95/380 again (S03, S04, S05).
    """

    PREWAITS = [5.0, 35.0, 65.0, 95.0, 380.0]
    RELATIVE = [5.0, 30.0, 30.0, 30.0, 285.0]

    def _chain(self, prewaits=None):
        # Botella 1..4 auto-continue; "Off Botella 4" breaks the chain (pause).
        return _linked([(p, 0.0) for p in (prewaits or self.PREWAITS)])

    def test_every_cue_starts_at_its_own_prewait(self):
        cues = self._chain()
        trigger = 0.0
        arrival = trigger
        starts = []
        for cue in cues:
            starts.append(arrival + cue.prewait.milliseconds_exact)
            if cue.post_go != "go":
                break
            arrival += CueHandler._chain_advance_ms(cue, mode="parallel")
        assert starts == [p * 1000 for p in self.PREWAITS]

    def test_walk_keeps_every_arrival_at_the_trigger(self):
        # The parallel layout hands each following cue the SAME arrival, and
        # _next_local_fire passes it on unchanged.
        cues = self._chain()
        p = _pass(1, 0.0, _layout(cues[0], 0.0, "parallel"), mode="parallel")
        arrivals = []
        cue, arrival = _fire(cues[0], p)
        while cue is not None:
            arrivals.append(arrival)
            cue, arrival = _fire(cue, p)
        assert arrivals == [0.0, 0.0, 0.0, 0.0]

    def test_skipped_non_local_cue_does_not_shift_later_local_segment(self):
        # A-B-A across nodes (plan §5.5 / review F6): under one common trigger a
        # skipped non-local cue contributes nothing, so this node's SECOND local
        # segment still anchors at the trigger.
        cues = _linked([(5.0, 0.0), (60.0, 0.0), (9.0, 0.0)], local=[True, False, True])
        p = _pass(1, 0.0, _layout(cues[0], 0.0, "parallel"), mode="parallel")
        cue, arrival = _fire(cues[0], p)
        assert cue is cues[2]
        assert arrival == 0.0

    def test_sequential_cascades_the_absolute_offsets(self):
        layout = _layout(self._chain()[0], 0.0, "sequential")
        assert _starts(layout) == [5000.0, 40000.0, 105000.0, 200000.0, 580000.0]

    def test_sequential_with_relative_prewaits_gives_the_authored_times(self):
        layout = _layout(self._chain(self.RELATIVE)[0], 0.0, "sequential")
        assert _starts(layout) == [5000.0, 35000.0, 65000.0, 95000.0, 380000.0]

    def test_sequential_a_skipped_non_local_cue_still_counts(self):
        # A-B-A again: B is another node's, but its waits are in the layout
        # every node computes, so the second local segment is at 5 + 60.
        cues = _linked([(5.0, 0.0), (60.0, 0.0), (9.0, 0.0)], local=[True, False, True])
        p = _pass(1, 0.0, _layout(cues[0], 0.0, "sequential"))
        cue, arrival = _fire(cues[0], p)
        assert cue is cues[2]
        assert arrival == 65000.0


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
        # Advancing clock: the run-ahead park blocks until the cue's slot is
        # near, which a frozen timeline would never reach.
        mtc = _AdvancingMtc(live_mtc_ms)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=arrival_ms, go_gen=go_gen)
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
