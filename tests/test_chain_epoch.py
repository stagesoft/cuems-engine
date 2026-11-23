# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Phase 2 increment 1 — the chain epoch, carried by the pass (1amfwm7jnqf).

Auto continue unrolls the whole local chain from one GO, so two independent
cascades (the original unroll and an ActionCue 'play' loop-back re-entering it)
can reach the same cue concurrently. Per-cue `_go_generation` is last-writer-
wins and cannot order them; the handler-wide **chain epoch** can. Since
1amfwm7jnqf the epoch rides in the pass (`chain_pass.Pass`), which go() mints
for a fresh entry together with the pass's layout and anchor, and writes on
every cue of the layout (`cue._pass`):

- `_chain_epoch` is bumped for every fresh chain entry (manual GO, go_from)
  and carried unchanged, inside the pass, through that chain's continuations;
- `cue._go_epoch` is the high-water mark of the newest chain event owning the
  cue, so a continuation carrying an older epoch is refused — including the
  same unroll reaching a cue twice through a cycle (`>=`); a retake (an
  enable during the pass, `unroll=False`) re-dispatches in its own pass and is
  not refused as a duplicate;
- `_last_stop_chain_epoch` records the epoch STOP claimed for itself, which
  kills every continuation of a chain that started before it.

go() no longer arms a fresh entry (D32): the cue's own thread arms it or
waits for the arm in flight, so a STOP during that arm is the thread's case.

Fresh entries are never refused: a fresh epoch is by construction greater than
any recorded stop and any cue mark, so manual GO keeps its old contract.

Design: Plans/prewait-dispatch-reorder-phase2.md §3; Plans/2026-11-18-
autocontinue-cumulative-waits.md Design §1, §4 (cuems-RELATIONS).
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _mtc(ms=0):
    mtc = MagicMock()
    mtc.main_tc.milliseconds_exact = float(ms)
    mtc.main_tc.milliseconds_rounded = ms
    return mtc


def _cue(id="c", loaded=True, enabled=True, local=True, **kw):
    kw.setdefault("post_go", "pause")
    kw.setdefault("_target_object", None)
    kw.setdefault("prewait", CTimecode(start_seconds=0))
    kw.setdefault("postwait", CTimecode(start_seconds=0))
    return SimpleNamespace(id=id, loaded=loaded, enabled=enabled, _local=local, **kw)


def _pass(epoch, anchor_ms=0.0, layout=(), root_seq=0, mode="sequential"):
    """A chain_pass.Pass carrying `epoch`: a continuation is validated by it
    exactly as by the old bare chain_epoch. Before Step 2 the engine has
    none; the thread test below needs only its attributes."""
    try:
        from cuemsengine.cues.chain_pass import Pass
    except ImportError:
        layout = list(layout)
        return SimpleNamespace(
            epoch=epoch,
            anchor_ms=anchor_ms,
            layout=layout,
            root_seq=root_seq,
            mode=mode,
            arrival_of=lambda c: next((a for x, a in layout if x is c), None),
        )
    return Pass(
        epoch=epoch,
        anchor_ms=anchor_ms,
        layout=list(layout),
        root_seq=root_seq,
        mode=mode,
    )


def _ch():
    """A CueHandler with only the state go() touches, so no engine, no
    players and no comms are involved."""
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch._arm_ahead = MagicMock()
    ch.arm = MagicMock()
    return ch


class TestFreshEntry:
    def test_mints_a_new_epoch_and_marks_the_cue(self):
        ch = _ch()
        cue = _cue()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(cue, _mtc())
        assert ch._chain_epoch == 1
        assert cue._go_epoch == 1

    def test_each_fresh_entry_takes_the_next_epoch(self):
        ch = _ch()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(_cue("a"), _mtc())
            ch.go(_cue("b"), _mtc())
        assert ch._chain_epoch == 2

    def test_go_after_a_stop_is_not_refused(self):
        """A GO pressed after a STOP mints a newer epoch than the STOP
        recorded, so the barrier cannot refuse it — replay keeps working."""
        ch = _ch()
        cue = _cue()
        ch._chain_epoch = 5
        ch._last_stop_chain_epoch = 5
        cue._go_epoch = 5
        with patch.object(CueHandler, "go_threaded"):
            thread = ch.go(cue, _mtc())
        assert thread is not None
        assert cue._go_epoch == 6

    def test_mints_a_pass_and_writes_it_on_every_cue_of_the_layout(self):
        """Design §1: the pass (epoch, anchor, layout) is minted in go()'s
        commit section and written on every cue of the layout, local or
        not."""
        ch = _ch()
        b = _cue("b", local=False)
        a = _cue("a", post_go="go", _target_object=b)
        with patch.object(CueHandler, "go_threaded"):
            ch.go(a, _mtc(), 1000.0, layout=[(a, 1000.0), (b, 1500.0)])
        assert a._pass is b._pass
        assert a._pass.epoch == 1 and a._pass.anchor_ms == 1000.0
        assert a._pass.layout == [(a, 1000.0), (b, 1500.0)]

    def test_a_disabled_cue_gets_a_thread(self):
        """S07 (D26, Design §2): go() no longer refuses a disabled cue; its
        thread is a silent one."""
        ch = _ch()
        cue = _cue(enabled=False)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0) is not None
        assert cue._go_epoch == 1

    def test_clears_stop_requested_and_resets_revealed(self):
        ch = _ch()
        cue = _cue(_stop_requested=True, _revealed=True)
        with patch.object(CueHandler, "go_threaded"):
            ch.go(cue, _mtc())
        assert cue._stop_requested is False
        assert cue._revealed is False
        assert cue._playing is True


class TestContinuationRefusal:
    def test_stale_continuation_is_refused(self):
        """The loop-back case: a fresh cascade already claimed the cue with a
        newer epoch, so the older cascade's dispatch must not spawn a second
        thread with a stale arrival."""
        ch = _ch()
        cue = _cue(_go_epoch=7, _go_generation=3)
        with patch.object(CueHandler, "go_threaded") as gt:
            thread = ch.go(cue, _mtc(), 1000.0, pass_=_pass(5))
        assert thread is None
        assert gt.call_count == 0
        assert cue._go_generation == 3, "a refused dispatch must not bump the gen"

    def test_equal_epoch_is_refused_as_a_cycle_guard(self):
        """A post_go='go' cycle would otherwise re-dispatch its own head
        forever, at thread-spawn rate, once dispatch happens at entry."""
        ch = _ch()
        cue = _cue(_go_epoch=4)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, pass_=_pass(4)) is None

    def test_newer_continuation_is_accepted(self):
        ch = _ch()
        cue = _cue(_go_epoch=3)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, pass_=_pass(7)) is not None
        assert cue._go_epoch == 7

    def test_unrelated_newer_chain_does_not_block_this_one(self):
        """A second chain bumps the handler counter, but only marks ITS OWN
        cues — so an in-flight chain's continuations keep flowing."""
        ch = _ch()
        ch._chain_epoch = 9
        cue = _cue(_go_epoch=3)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, pass_=_pass(7)) is not None

    def test_continuation_after_a_stop_is_refused(self):
        ch = _ch()
        ch._last_stop_chain_epoch = 6
        cue = _cue()
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, pass_=_pass(4)) is None


class TestStopDuringArmWindow:
    """F4: the STOP race go() used to lose, now on the cue's own thread.

    go() no longer arms a fresh entry (D32, Design §4): it dispatches at once
    and the cue's thread arms it, or waits for the arm in flight. A STOP that
    lands during that arm moves the arm epoch, and the thread then leaves
    without setting anything up or revealing: the STOP wins.
    """

    def test_a_fresh_go_does_not_arm_its_cue(self):
        ch = _ch()
        cue = _cue(loaded=False)
        with patch.object(CueHandler, "go_threaded"):
            thread = ch.go(cue, _mtc())
        assert thread is not None
        ch.arm.assert_not_called()

    def test_stop_during_the_arm_on_the_thread_wins(self):
        ch = _ch()
        ch.communications_thread = MagicMock()
        ch.disarm = MagicMock()
        ch.go = MagicMock(return_value=None)
        ch._next_local_fire = MagicMock(return_value=(None, 0.0))
        ch.describe_arm_in_flight = MagicMock(return_value=None)
        cue = _cue(
            loaded=False,
            _stop_requested=False,
            _go_generation=1,
            _revealed=False,
            _start_mtc=None,
        )

        def slow_arm(target, init=False, epoch=None, wait_report=None, **kw):
            # the operator hits STOP while the JACK ports are being waited on
            ch.stop_all_cues()
            target.loaded = True

        ch.arm = MagicMock(side_effect=slow_arm)
        arm_epoch = ch._disarm_epoch
        mtc = _mtc()
        with (
            patch("cuemsengine.cues.CueHandler.run_cue") as rc,
            patch("cuemsengine.cues.CueHandler.reveal_cue") as rv,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep"),
        ):
            ch.go_threaded(
                cue, mtc, 0.0, 1, _pass(1, 0.0, [(cue, 0.0)]), arm_epoch=arm_epoch
            )
        ch.arm.assert_called_once()
        rc.assert_not_called()
        rv.assert_not_called()

    def test_a_continuation_does_not_arm_ahead_on_the_caller_thread(self):
        """_arm_ahead is synchronous and arm() can block ~15s per audio cue.
        A continuation's caller is the PREVIOUS cue's thread now that dispatch
        happens at chain entry, so running it there would delay that cue's own
        reveal — silently, since its LATE check already ran."""
        ch = _ch()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(_cue(), _mtc(), 0.0, pass_=_pass(1))
        ch._arm_ahead.assert_not_called()

    def test_a_retake_does_not_arm_ahead_either(self):
        """A retake (an enable during the pass, Design §2) calls go() for the
        cue alone, `unroll=False`, from the command thread, in the pass that
        holds it: it is not refused as a duplicate of that pass, and it does
        not run the lookahead."""
        ch = _ch()
        cue = _cue()
        p = _pass(3, 0.0, [(cue, 0.0)])
        cue._pass = p
        cue._go_epoch = 3
        cue._dispatch_arrival_ms = 0.0
        with patch.object(CueHandler, "go_threaded"):
            thread = ch.go(cue, _mtc(), 0.0, pass_=p, unroll=False, retake=True)
        assert thread is not None
        assert cue._pass is p
        ch._arm_ahead.assert_not_called()

    def test_a_manual_go_still_arms_ahead(self):
        ch = _ch()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(_cue(), _mtc())
        ch._arm_ahead.assert_called_once()

    def test_the_dispatch_anchor_is_recorded_before_the_thread_starts(self):
        """A retake re-dispatches at this arrival; if the spawned thread wrote
        it, an enable arriving first would find the previous cycle's."""
        ch = _ch()
        cue = _cue()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(cue, _mtc(), 4200.0, pass_=_pass(1))
        assert cue._dispatch_arrival_ms == 4200.0

    def test_a_continuation_does_not_arm_on_the_caller_thread(self):
        """Dispatch happens at chain entry, so go() for cue k+1 runs on cue
        k's thread — a ~15s audio arm there would delay k's own reveal. The
        cue arms on its own thread instead (go_threaded)."""
        ch = _ch()
        cue = _cue(loaded=False)
        with patch.object(CueHandler, "go_threaded"):
            thread = ch.go(cue, _mtc(), 0.0, pass_=_pass(1))
        assert thread is not None
        ch.arm.assert_not_called()

    def test_stop_all_cues_records_the_barrier_and_marks_armed_cues(self):
        ch = _ch()
        cue = _cue(_go_generation=2)
        ch._armed_cues = [cue]
        ch.stop_all_cues()
        assert ch._last_stop_chain_epoch == ch._chain_epoch == 1
        assert cue._go_epoch == 1
        assert cue._stop_requested is True
        assert cue._playing is False

    def test_go_after_stop_still_plays(self):
        ch = _ch()
        cue = _cue()
        ch._armed_cues = [cue]
        ch.stop_all_cues()
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc()) is not None
        assert cue._stop_requested is False


class TestHandlerIsolation:
    def test_two_handlers_keep_independent_epochs(self):
        """The production singleton and a test-built handler must not share
        counters — the class attribute is only a default."""
        a, b = _ch(), _ch()
        with patch.object(CueHandler, "go_threaded"):
            a.go(_cue("1"), _mtc())
            a.go(_cue("2"), _mtc())
            b.go(_cue("3"), _mtc())
        assert a._chain_epoch == 2
        assert b._chain_epoch == 1
        assert CueHandler._chain_epoch == 0
