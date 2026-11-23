# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Phase 2 increment 2 — dispatch at the trigger, held setup at the window.

Phase 1 gave every auto-continue cue the same arrival (the chain trigger) but
kept dispatching the chain cue by cue, at `start(k) + postwait(k)`. A chain
whose prewaits run BACKWARDS — ordinary authoring once prewait is an absolute
offset — was therefore reached after its own anchor and fired at dispatch.

Now the continuation is dispatched at thread ENTRY, so the whole local chain
unrolls from the trigger and each cue's thread parks on its own anchor. Two
consequences this file pins:

- the chain is dispatched before anything waits, so a descending chain is on
  time and silent (no LATE warning);
- `run_cue` (video decode at the offset, audio graph verify, the DMX scene
  send) is deferred to `start − _RUN_AHEAD_MS`, so unrolling at GO does not
  preload the whole chain at once.

Since 1amfwm7jnqf the chain is laid out once per pass (`chain_pass.layout`)
and "en serie" (`sequential`): a cue's prewait and postwait push the cues
after it. The 2026-08-14 tests that pin the common trigger
(`test_descending_prewait_chain_is_on_time_and_silent`,
`test_the_whole_chain_lights_at_the_trigger`) run on a `parallel` layout ("en
paralelo"), each with its `sequential` twin. A cue whose arm fails is silent
on its node and keeps its body and its hand-over (D32).

`_wait_mtc` polls live MTC and sleeps between polls, so a test whose MTC never
moves would spin forever on any future target. `_FakeMtc` advances the
timeline by exactly the duration each patched sleep asks for.
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import DmxCue  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


class _FakeMtc:
    """MTC whose timeline advances by the duration of each sleep, so the real
    _wait_mtc loop terminates on a future target instead of hanging."""

    def __init__(self, ms=0.0):
        self.main_tc = SimpleNamespace(
            milliseconds_exact=float(ms),
            milliseconds_rounded=int(ms),
            framerate=25.0,
            frames=0,
        )

    def advance(self, seconds):
        ms = float(seconds) * 1000.0
        self.main_tc.milliseconds_exact += ms
        self.main_tc.milliseconds_rounded = int(self.main_tc.milliseconds_exact)
        self.main_tc.frames = int(self.main_tc.milliseconds_exact / 1000 * 25)

    @property
    def now(self):
        return self.main_tc.milliseconds_exact


def _cue(id="c", prewait=0, postwait=0, post_go="go", target=None, local=True):
    return SimpleNamespace(
        id=id,
        _local=local,
        enabled=True,
        loaded=True,
        post_go=post_go,
        prewait=CTimecode(start_seconds=prewait),
        postwait=CTimecode(start_seconds=postwait),
        _target_object=target,
        _stop_requested=False,
        _go_generation=1,
        _revealed=False,
        _start_mtc=None,
    )


def _dmx_cue(prewait=0):
    """A real DmxCue (isinstance matters — DMX commits at run_cue, not at
    reveal), built without its constructor so no player is involved."""
    cue = DmxCue.__new__(DmxCue)
    cue.id = str(uuid4())
    cue._local = True
    cue.enabled = True
    cue.loaded = True
    cue.post_go = "go"
    cue.prewait = CTimecode(start_seconds=prewait)
    cue.postwait = CTimecode(start_seconds=0)
    cue._target_object = None
    cue._stop_requested = False
    cue._go_generation = 1
    cue._revealed = False
    cue._start_mtc = None
    return cue


def _pass(epoch=1, anchor_ms=0.0, layout=(), root_seq=0, mode="sequential"):
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


def _ch():
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    ch.disarm = MagicMock()
    ch.arm = MagicMock()
    ch._arm_ahead = MagicMock()
    ch.go = MagicMock(return_value=None)
    ch._next_local_fire = MagicMock(return_value=(None, 0.0))
    return ch


def _run(ch, cue, mtc, order=None, pass_=None, **kw):
    """Drive go_threaded with the players patched out, recording call order.

    The pass goes in positionally (go_threaded's fifth argument), so a test
    that does not look at it keeps running on the engine before Step 2."""
    calls = order if order is not None else []
    if pass_ is None:
        pass_ = _pass(1, 0.0, [(cue, 0.0)])

    def rec(name, ret=None):
        def _f(*a, **k):
            calls.append(name)
            return ret

        return _f

    go_gen = kw.pop("go_gen", cue._go_generation)
    frozen = kw.pop("frozen_mtc_ms", None)
    with (
        patch("cuemsengine.cues.CueHandler.run_cue", side_effect=rec("run_cue")) as rc,
        patch(
            "cuemsengine.cues.CueHandler.reveal_cue", side_effect=rec("reveal")
        ) as rv,
        patch("cuemsengine.cues.CueHandler.loop_cue", side_effect=rec("loop")),
        patch("cuemsengine.cues.CueHandler.blank_cue"),
        patch(
            "cuemsengine.cues.CueHandler.sleep", side_effect=lambda s: mtc.advance(s)
        ),
    ):
        ch.communications_thread.add_cue.side_effect = rec("add_cue")
        ch.go.side_effect = rec("dispatch")
        ch.go_threaded(cue, mtc, frozen, go_gen, pass_, **kw)
    return calls, rc, rv


class TestDispatchAtEntry:
    def test_continuation_is_dispatched_before_any_wait(self):
        """The whole point: cue k+1 leaves at the trigger, not after cue k's
        reveal + postwait."""
        ch = _ch()
        nxt = SimpleNamespace(id="n")
        ch._next_local_fire = MagicMock(return_value=(nxt, 0.0))
        cue = _cue(prewait=30)
        mtc = _FakeMtc(0)
        calls, _, _ = _run(ch, cue, mtc, pass_=_pass(4, 0.0, [(cue, 0.0), (nxt, 0.0)]))
        assert calls[0] == "dispatch"
        assert calls.index("dispatch") < calls.index("run_cue")
        assert calls.index("dispatch") < calls.index("reveal")

    def test_dispatch_carries_the_pass_unchanged(self):
        ch = _ch()
        nxt = SimpleNamespace(id="n")
        ch._next_local_fire = MagicMock(return_value=(nxt, 1234.0))
        mtc = _FakeMtc(0)
        cue = _cue()
        p = _pass(42, 0.0, [(cue, 0.0), (nxt, 1234.0)])
        _run(ch, cue, mtc, pass_=p)
        ch.go.assert_called_once_with(nxt, mtc, 1234.0, pass_=p, arm_epoch=None)

    def test_a_pause_cue_does_not_dispatch_its_target(self):
        """post_go='pause'/'go_at_end' cues carry a _target_object too — it is
        the next cue in sequence, waiting for a manual GO. Dispatching it here
        would turn every show into one long auto-continue chain."""
        ch = _ch()
        ch._next_local_fire = MagicMock(return_value=(SimpleNamespace(id="n"), 0.0))
        cue = _cue(post_go="pause", target=SimpleNamespace(id="t"))
        _run(ch, cue, _FakeMtc(0))
        ch.go.assert_not_called()

    def test_unroll_false_suppresses_the_dispatch(self):
        """A retake (an enable during the pass) re-enters a chain that is
        already unrolled."""
        ch = _ch()
        ch._next_local_fire = MagicMock(return_value=(SimpleNamespace(id="n"), 0.0))
        _run(ch, _cue(), _FakeMtc(0), unroll=False)
        ch.go.assert_not_called()

    def test_a_failing_dispatch_does_not_kill_this_cue(self):
        """A downstream arm blowing up must not cost this cue its own reveal."""
        ch = _ch()
        ch._next_local_fire = MagicMock(return_value=(SimpleNamespace(id="n"), 0.0))
        ch.go = MagicMock(side_effect=RuntimeError("boom"))
        cue = _cue()
        mtc = _FakeMtc(0)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue") as reveal,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        reveal.assert_called_once()

    def test_descending_prewait_chain_is_on_time_and_silent(self):
        """`parallel`: the field case, inverted: cue B's prewait is SMALLER
        than cue A's. Under Phase 1 B was dispatched after its own anchor and
        fired late."""
        ch = _ch()
        del ch._next_local_fire  # the real walk, on the pass's layout
        b = _cue("B", prewait=2, post_go="pause")
        a = _cue("A", prewait=10, target=b)
        p = _pass(1, 0.0, _layout(a, 0.0, "parallel"), mode="parallel")
        mtc = _FakeMtc(0)
        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            _run(ch, a, mtc, pass_=p)
        # B was dispatched at the trigger (mtc still 0), so its own thread
        # will park on 2s — no anchor was missed anywhere.
        ch.go.assert_called_once_with(b, mtc, 0.0, pass_=p, arm_epoch=None)
        assert not [c for c in log.warning.call_args_list if "LATE" in str(c)]

    def test_sequential_chain_is_dispatched_at_entry_with_its_place(self):
        """`sequential` twin: B arrives after A's prewait (10 s) and starts at
        12 s; it is still dispatched at A's entry, and on time."""
        ch = _ch()
        del ch._next_local_fire
        b = _cue("B", prewait=2, post_go="pause")
        a = _cue("A", prewait=10, target=b)
        p = _pass(1, 0.0, _layout(a, 0.0, "sequential"))
        mtc = _FakeMtc(0)
        order = []
        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            _run(ch, a, mtc, order=order, pass_=p)
        ch.go.assert_called_once_with(b, mtc, 10000.0, pass_=p, arm_epoch=None)
        assert order.index("dispatch") < order.index("run_cue")
        assert not [c for c in log.warning.call_args_list if "LATE" in str(c)]


class TestDeferredRunCue:
    def test_run_cue_waits_for_the_lookahead_window(self):
        ch = _ch()
        cue = _cue(prewait=60)
        mtc = _FakeMtc(0)
        seen = {}
        with (
            patch(
                "cuemsengine.cues.CueHandler.run_cue",
                side_effect=lambda *a, **k: seen.setdefault("at", mtc.now),
            ),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        assert seen["at"] >= 60000 - CueHandler._RUN_AHEAD_MS
        assert seen["at"] < 60000, "must still be held before its start"

    def test_run_cue_is_immediate_when_the_start_is_already_close(self):
        ch = _ch()
        cue = _cue(prewait=2)
        mtc = _FakeMtc(0)
        seen = {}
        with (
            patch(
                "cuemsengine.cues.CueHandler.run_cue",
                side_effect=lambda *a, **k: seen.setdefault("at", mtc.now),
            ),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        assert seen["at"] == 0.0

    def test_run_cue_failure_clears_the_illumination(self):
        """Illumination now happens BEFORE run_cue, so a run_cue that raises
        (missing media) would otherwise leave the cue lit forever."""
        ch = _ch()
        cue = _cue()
        mtc = _FakeMtc(0)
        with (
            patch(
                "cuemsengine.cues.CueHandler.run_cue",
                side_effect=AttributeError("media is None"),
            ),
            patch("cuemsengine.cues.CueHandler.reveal_cue") as reveal,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        ch.communications_thread.remove_cue.assert_called_once()
        reveal.assert_not_called()

    def test_dmx_commits_its_output_at_run_cue(self):
        """DMX has no reveal: run_cue sends the scene with an absolute
        mtc_time and the player self-schedules. The stop walk must therefore
        treat it as committed from run_cue on."""
        ch = _ch()
        cue = _dmx_cue()
        mtc = _FakeMtc(0)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        assert cue._revealed is True


class TestCancelWhileParked:
    def test_stop_while_parked_skips_run_and_reveal(self):
        ch = _ch()
        cue = _cue(prewait=60)
        mtc = _FakeMtc(0)

        def stop_after_a_bit(seconds):
            mtc.advance(seconds)
            if mtc.now >= 5000:
                cue._stop_requested = True

        with (
            patch("cuemsengine.cues.CueHandler.run_cue") as rc,
            patch("cuemsengine.cues.CueHandler.reveal_cue") as rv,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=stop_after_a_bit),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        rc.assert_not_called()
        rv.assert_not_called()

    def test_cancel_between_the_reveal_wait_and_the_reveal_is_honoured(self):
        """The commit is re-checked under the lock the stop walk also takes,
        so a cancel landing in the 20ms poll gap cannot leak a reveal."""
        ch = _ch()
        cue = _cue()
        mtc = _FakeMtc(0)

        def cancel(*a, **k):
            cue._go_generation += 1
            return "reached"

        ch._reveal_wait = MagicMock(side_effect=cancel)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue") as rv,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(cue, mtc, 0.0, 1, _pass(1, 0.0, [(cue, 0.0)]))
        rv.assert_not_called()
        assert cue._revealed is False

    def test_reveal_sets_the_commit_flag(self):
        ch = _ch()
        cue = _cue()
        mtc = _FakeMtc(0)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        assert cue._revealed is True


class TestOwnArm:
    def test_a_continuation_arms_on_its_own_thread(self):
        ch = _ch()
        cue = _cue()
        cue.loaded = False
        ch.arm = MagicMock(
            side_effect=lambda c, init=False, epoch=None, wait_report=None: setattr(
                c, "loaded", True
            )
        )
        mtc = _FakeMtc(0)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue") as rv,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        ch.arm.assert_called_once_with(cue, init=True, epoch=None, wait_report={})
        rv.assert_called_once()

    def test_an_unarmable_cue_dies_alone(self):
        """Its chain was already dispatched at entry, so a failed arm must
        take out this cue only — and say so. D32: it is silent on this node
        (`passed silent`), with the ERROR the plan names."""
        ch = _ch()
        nxt = SimpleNamespace(id="n")
        ch._next_local_fire = MagicMock(return_value=(nxt, 0.0))
        cue = _cue()
        cue.loaded = False
        mtc = _FakeMtc(0)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue") as rc,
            patch("cuemsengine.cues.CueHandler.reveal_cue") as rv,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        ch.go.assert_called_once()  # the chain still went out
        rc.assert_not_called()
        rv.assert_not_called()
        assert log.error.called
        errors = [str(c.args[0]) for c in log.error.call_args_list if c.args]
        assert any(
            "c could not be armed; it does not play in pass" in e for e in errors
        ), errors
        infos = [str(c.args[0]) for c in log.info.call_args_list if c.args]
        assert any(x.startswith("Cue c passed silent at mtc ") for x in infos), infos

    def test_an_unarmable_cue_keeps_its_body_and_its_hand_over(self):
        """D32, S100: the cue is enabled, so it keeps its body: an Auto-follow
        cue whose arm failed still hands over at body_end + postwait, as if
        it had played (a disabled cue would hand over at start + postwait)."""
        ch = _ch()
        target = SimpleNamespace(id="t", _go_generation=0)
        cue = _cue(post_go="go_at_end", target=target)
        cue.loaded = False
        cue.loop = 1
        ch.go_from = MagicMock(return_value=None)
        ch._follow_fired = MagicMock(return_value=True)
        ch._follow_instant_ms = MagicMock(return_value=4000.0)
        ch._chain_continues = MagicMock(return_value=True)
        ch._follows_out = MagicMock(return_value=False)
        ch._leave_follow = MagicMock()
        ch._wait_wrap_player_end = MagicMock()
        ch._end_cuelist_child = MagicMock()
        ch.wait_for_cue = MagicMock()
        mtc = _FakeMtc(0)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue") as rv,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.blank_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
            patch("cuemsengine.cues.CueHandler.Logger"),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        rv.assert_not_called()
        ch._follow_instant_ms.assert_called_once()
        ch.go_from.assert_called_once()
        assert ch.go_from.call_args.args[0] is target
        assert ch.go_from.call_args.args[2] == 4000.0

    def test_an_arm_that_overruns_the_runway_warns_late(self):
        """The entry LATE check ran before the arm; an arm longer than the
        cue's own runway would otherwise fire it late with no trace."""
        ch = _ch()
        cue = _cue(prewait=1)
        cue.loaded = False
        mtc = _FakeMtc(0)

        def slow_arm(c, init=False, epoch=None, wait_report=None):
            mtc.advance(20)  # 20s of JACK port waiting
            c.loaded = True

        ch.arm = MagicMock(side_effect=slow_arm)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
        ):
            ch.go_threaded(
                cue, mtc, 0.0, cue._go_generation, _pass(1, 0.0, [(cue, 0.0)])
            )
        assert [c for c in log.warning.call_args_list if "LATE" in str(c)]


class TestIllumination:
    def _lit_at(self, cue, arrival_ms, pass_):
        ch = _ch()
        mtc = _FakeMtc(0)
        seen = {}
        ch.communications_thread.add_cue.side_effect = lambda *a, **k: seen.setdefault(
            "at", mtc.now
        )
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(cue, mtc, arrival_ms, cue._go_generation, pass_)
        return seen["at"]

    def test_the_whole_chain_lights_at_the_trigger(self):
        """`parallel`: a cue illuminates when it ARRIVES, and in that mode
        every cue arrives at the trigger."""
        cue = _cue("C", prewait=60, post_go="pause")
        head = _cue("H", prewait=30, target=cue)
        p = _pass(1, 0.0, _layout(head, 0.0, "parallel"), mode="parallel")
        assert p.arrival_of(cue) == 0.0
        assert self._lit_at(cue, p.arrival_of(cue), p) == 0.0

    def test_a_sequential_cue_lights_at_its_own_arrival(self):
        """`sequential` twin: C arrives after H's 30 s prewait and lights then,
        whatever its own prewait."""
        cue = _cue("C", prewait=60, post_go="pause")
        head = _cue("H", prewait=30, target=cue)
        p = _pass(1, 0.0, _layout(head, 0.0, "sequential"))
        assert p.arrival_of(cue) == 30000.0
        assert self._lit_at(cue, p.arrival_of(cue), p) == 30000.0

    def test_the_dispatch_arrival_is_recorded_on_the_cue(self):
        """A retake re-dispatches the cue at this same arrival (Design §2)."""
        ch = _ch()
        cue = _cue()
        _run(ch, cue, _FakeMtc(0), frozen_mtc_ms=7000.0)
        assert cue._dispatch_arrival_ms == 7000.0
