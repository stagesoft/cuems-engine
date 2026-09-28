# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Phase 2 increment 1 — the chain epoch.

Auto continue unrolls the whole local chain from one GO, so two independent
cascades (the original unroll and an ActionCue 'play' loop-back re-entering it)
can reach the same cue concurrently. Per-cue `_go_generation` is last-writer-
wins and cannot order them; the handler-wide **chain epoch** can:

- `_chain_epoch` is bumped for every fresh chain entry (manual GO, go_from,
  enable-rejoin) and carried unchanged through that chain's continuations;
- `cue._go_epoch` is the high-water mark of the newest chain event owning the
  cue, so a continuation carrying an older epoch is refused — including the
  same unroll reaching a cue twice through a cycle (`>=`);
- `_last_stop_chain_epoch` records the epoch STOP claimed for itself, which
  kills every continuation of a chain that started before it. That check runs
  AFTER go()'s re-arm fallback, which is what makes a STOP landing inside a
  ~15s audio arm window stick instead of being wiped by the unconditional
  `_stop_requested = False` (F4).

Fresh entries are never refused: a fresh epoch is by construction greater than
any recorded stop and any cue mark, so manual GO keeps its old contract.

Design: Plans/prewait-dispatch-reorder-phase2.md §3 (cuems-RELATIONS).
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _mtc(ms=0):
    mtc = MagicMock()
    mtc.main_tc.milliseconds_exact = float(ms)
    mtc.main_tc.milliseconds_rounded = ms
    return mtc


def _cue(id="c", loaded=True, enabled=True, local=True, **kw):
    return SimpleNamespace(id=id, loaded=loaded, enabled=enabled, _local=local, **kw)


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
            thread = ch.go(cue, _mtc(), 1000.0, chain_epoch=5)
        assert thread is None
        assert gt.call_count == 0
        assert cue._go_generation == 3, "a refused dispatch must not bump the gen"

    def test_equal_epoch_is_refused_as_a_cycle_guard(self):
        """A post_go='go' cycle would otherwise re-dispatch its own head
        forever, at thread-spawn rate, once dispatch happens at entry."""
        ch = _ch()
        cue = _cue(_go_epoch=4)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, chain_epoch=4) is None

    def test_newer_continuation_is_accepted(self):
        ch = _ch()
        cue = _cue(_go_epoch=3)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, chain_epoch=7) is not None
        assert cue._go_epoch == 7

    def test_unrelated_newer_chain_does_not_block_this_one(self):
        """A second chain bumps the handler counter, but only marks ITS OWN
        cues — so an in-flight chain's continuations keep flowing."""
        ch = _ch()
        ch._chain_epoch = 9
        cue = _cue(_go_epoch=3)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, chain_epoch=7) is not None

    def test_continuation_after_a_stop_is_refused(self):
        ch = _ch()
        ch._last_stop_chain_epoch = 6
        cue = _cue()
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), 0.0, chain_epoch=4) is None


class TestStopDuringArmWindow:
    """F4: the STOP race go() used to lose.

    `_stop_requested = False` sat AFTER the re-arm fallback, which can block
    ~15s on an audio cue waiting for its JACK ports. A STOP landing in that
    window was silently cleared and the cue played anyway. The reset now sits
    inside a validated commit that runs after the arm.
    """

    def test_stop_during_the_rearm_refuses_the_dispatch(self):
        ch = _ch()
        cue = _cue(loaded=False, _stop_requested=False)

        def slow_arm(target, init=False):
            # the operator hits STOP while the JACK ports are being waited on
            ch.stop_all_cues()
            target.loaded = True

        ch.arm = MagicMock(side_effect=slow_arm)
        ch._armed_cues = [cue]

        with patch.object(CueHandler, "go_threaded") as gt:
            thread = ch.go(cue, _mtc())

        assert thread is None
        assert gt.call_count == 0
        assert cue._stop_requested is True, "the STOP must survive go()"

    def test_a_continuation_does_not_arm_ahead_on_the_caller_thread(self):
        """_arm_ahead is synchronous and arm() can block ~15s per audio cue.
        A continuation's caller is the PREVIOUS cue's thread now that dispatch
        happens at chain entry, so running it there would delay that cue's own
        reveal — silently, since its LATE check already ran."""
        ch = _ch()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(_cue(), _mtc(), 0.0, chain_epoch=1)
        ch._arm_ahead.assert_not_called()

    def test_a_rejoin_does_not_arm_ahead_either(self):
        """unroll=False is the enable-rejoin, called from the command thread;
        the cue is already armed by then."""
        ch = _ch()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(_cue(), _mtc(), 0.0, unroll=False)
        ch._arm_ahead.assert_not_called()

    def test_a_manual_go_still_arms_ahead(self):
        ch = _ch()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(_cue(), _mtc())
        ch._arm_ahead.assert_called_once()

    def test_the_dispatch_anchor_is_recorded_before_the_thread_starts(self):
        """cancel_parked reads it to stamp a rejoin; if the spawned thread
        wrote it, a disable arriving first would find the previous cycle's."""
        ch = _ch()
        cue = _cue()
        with patch.object(CueHandler, "go_threaded"):
            ch.go(cue, _mtc(), 4200.0, chain_epoch=1)
        assert cue._dispatch_arrival_ms == 4200.0

    def test_a_continuation_does_not_arm_on_the_caller_thread(self):
        """Dispatch happens at chain entry, so go() for cue k+1 runs on cue
        k's thread — a ~15s audio arm there would delay k's own reveal. The
        cue arms on its own thread instead (go_threaded)."""
        ch = _ch()
        cue = _cue(loaded=False)
        with patch.object(CueHandler, "go_threaded"):
            thread = ch.go(cue, _mtc(), 0.0, chain_epoch=1)
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


class TestStampSkipped:
    """Disabled cues skipped by a chain walk are stamped with the pass that
    would have dispatched them, so enabling one later can rejoin it (§6).
    The stamp is written inside go()'s accept lock, with the epoch minted
    there — never read back afterwards, which could capture a newer
    unrelated dispatch's epoch."""

    def test_skipped_cues_are_stamped_with_this_pass(self):
        ch = _ch()
        skipped = [_cue("x", enabled=False), _cue("y", enabled=False)]
        with patch.object(CueHandler, "go_threaded"):
            ch.go(_cue("head"), _mtc(), 4000.0, stamp_skipped=skipped)
        assert skipped[0]._chain_pass == (1, 4000.0)
        assert skipped[1]._chain_pass == (1, 4000.0)

    def test_no_stamp_when_the_dispatch_is_refused(self):
        ch = _ch()
        skipped = [_cue("x", enabled=False)]
        cue = _cue(_go_epoch=9)
        with patch.object(CueHandler, "go_threaded"):
            ch.go(cue, _mtc(), 0.0, chain_epoch=2, stamp_skipped=skipped)
        assert not hasattr(skipped[0], "_chain_pass")

    def test_stamp_pass_stamps_without_dispatching(self):
        """When a node's whole local segment is disabled, go() is never
        called — but those cues must still be rejoin-able."""
        ch = _ch()
        skipped = [_cue("x", enabled=False)]
        epoch = ch.stamp_pass(skipped, 2500.0)
        assert epoch == 1
        assert skipped[0]._chain_pass == (1, 2500.0)


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
