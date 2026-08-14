# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Phase 2 increment 3 — a cue enabled mid-pass still fires at its own slot.

Auto continue walks the chain once, at the trigger, and a disabled cue is
transparent to that walk. Enabling it a moment later must not mean "nothing
happens until the next GO": if a cue is enabled it must fire when it was
supposed to fire.

So the walk stamps every disabled cue it passes with the pass that would have
dispatched it (`_chain_pass = (epoch, arrival)`), and enabling one rejoins it
at that same anchor — provided the pass is still alive and its slot has not
gone by. It rejoins with `unroll=False`: the rest of the chain is already
running and must not be re-dispatched.

Refused when the slot has passed (firing late by surprise mid-show is worse
than not firing), when a STOP ended that pass, and when a stop-action already
claimed the cue — decision 2 (a stop takes its descendants) outranks this.

Design: Plans/prewait-dispatch-reorder-phase2.md §6 (cuems-RELATIONS).
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _mtc(ms=0.0):
    mtc = MagicMock()
    mtc.main_tc.milliseconds_exact = float(ms)
    mtc.main_tc.milliseconds_rounded = int(ms)
    return mtc


def _cue(id, enabled=True, local=True, prewait=0, post_go="go", target=None):
    return SimpleNamespace(
        id=id,
        enabled=enabled,
        _local=local,
        loaded=True,
        post_go=post_go,
        prewait=CTimecode(start_seconds=prewait),
        postwait=CTimecode(start_seconds=0),
        _target_object=target,
        _stop_requested=False,
        _go_generation=0,
        _revealed=False,
    )


def _ch():
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    ch._arm_ahead = MagicMock()
    ch.arm = MagicMock()
    return ch


class TestStamping:
    def test_the_walk_stamps_a_disabled_cue_it_passes(self):
        b = _cue("B", enabled=False)
        c = _cue("C")
        a = _cue("A", target=b)
        b._target_object = c
        ch = _ch()
        found, arrival = ch._next_local_fire(a, 1000.0, stamp_epoch=7)
        assert found is c
        assert b._chain_pass == (7, 1000.0)

    def test_the_walk_stamps_a_disabled_cue_that_is_the_chain_break(self):
        """It is walked TO, not walked past — the loop returns there, so the
        stamp has to happen before the break check."""
        b = _cue("B", enabled=False, post_go="pause")
        a = _cue("A", target=b)
        ch = _ch()
        found, _ = ch._next_local_fire(a, 0.0, stamp_epoch=7)
        assert found is None
        assert b._chain_pass == (7, 0.0)

    def test_the_walk_stamps_nothing_when_not_asked(self):
        """Callers that only ask 'who is next' must not mutate the script."""
        b = _cue("B", enabled=False)
        a = _cue("A", target=b)
        ch = _ch()
        ch._next_local_fire(a, 0.0)
        assert not hasattr(b, "_chain_pass")

    def test_an_all_disabled_local_segment_is_still_stamped(self):
        """No local cue fires, so go() is never called and nothing would mint
        an epoch — but those cues must stay rejoin-able."""
        b = _cue("B", enabled=False)
        ch = _ch()
        epoch = ch.stamp_pass([b], 4000.0)
        assert b._chain_pass == (epoch, 4000.0)


class TestRejoin:
    def _stamped(self, ch, prewait, arrival=0.0, epoch=None):
        cue = _cue("B", enabled=True, prewait=prewait)
        if epoch is None:
            ch._chain_epoch = 5
            epoch = 5
        cue._chain_pass = (epoch, arrival)
        return cue

    def test_a_cue_enabled_before_its_slot_fires_at_that_slot(self):
        ch = _ch()
        cue = self._stamped(ch, prewait=60)
        with patch.object(CueHandler, "go_threaded"):
            # 20s into a pass that started at 0: the slot is still at 60s
            assert ch.rejoin_chain(cue, _mtc(20000)) is True
        assert cue._playing is True

    def test_the_rejoin_is_anchored_at_the_original_trigger(self):
        ch = _ch()
        cue = self._stamped(ch, prewait=60, arrival=3000.0)
        with patch.object(CueHandler, "go") as go:
            go.return_value = object()
            ch.rejoin_chain(cue, _mtc(20000))
        assert go.call_args.args[2] == 3000.0
        assert go.call_args.kwargs["unroll"] is False

    def test_a_slot_already_gone_by_does_not_fire(self):
        ch = _ch()
        cue = self._stamped(ch, prewait=60)
        with (
            patch.object(CueHandler, "go") as go,
            patch("cuemsengine.cues.CueHandler.Logger") as log,
        ):
            assert ch.rejoin_chain(cue, _mtc(70000)) is False
        go.assert_not_called()
        assert log.info.called or log.warning.called

    def test_a_stop_since_that_pass_invalidates_it(self):
        ch = _ch()
        cue = self._stamped(ch, prewait=60, epoch=5)
        ch._last_stop_chain_epoch = 6
        with patch.object(CueHandler, "go") as go:
            assert ch.rejoin_chain(cue, _mtc(20000)) is False
        go.assert_not_called()

    def test_a_cue_claimed_by_a_stop_action_cannot_rejoin(self):
        """Decision 2 beats decision 4: a stop took this cue's ancestor down,
        so it stays dead for this pass."""
        ch = _ch()
        cue = self._stamped(ch, prewait=60, epoch=5)
        cue._go_epoch = 6  # the cancel walk claimed it
        with patch.object(CueHandler, "go") as go:
            assert ch.rejoin_chain(cue, _mtc(20000)) is False
        go.assert_not_called()

    def test_an_unstamped_cue_does_not_rejoin(self):
        ch = _ch()
        cue = _cue("B", prewait=10)
        with patch.object(CueHandler, "go") as go:
            assert ch.rejoin_chain(cue, _mtc(0)) is False
        go.assert_not_called()

    def test_rejoining_twice_only_fires_once(self):
        """The stamp survives the rejoin; the epoch mark left by the dispatch
        is what makes the second attempt a no-op."""
        ch = _ch()
        cue = self._stamped(ch, prewait=60)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.rejoin_chain(cue, _mtc(20000)) is True
            assert ch.rejoin_chain(cue, _mtc(21000)) is False

    def test_a_stop_landing_during_the_rejoin_wins(self):
        """rejoin_chain drops the lock between validating the barrier and
        dispatching. A STOP in that window must not be overridden by the fresh
        epoch the dispatch mints — the cue would play after the operator
        stopped the show."""
        ch = _ch()
        cue = self._stamped(ch, prewait=60)
        real_go = CueHandler.go

        def stop_then_go(self_, c, mtc, frozen=None, **kw):
            # the STOP lands after the barrier check, before the dispatch
            if not getattr(self_, "_stopped_once", False):
                self_._stopped_once = True
                self_._chain_epoch += 1
                self_._last_stop_chain_epoch = self_._chain_epoch
            return real_go(self_, c, mtc, frozen, **kw)

        with (
            patch.object(CueHandler, "go", stop_then_go),
            patch.object(CueHandler, "go_threaded"),
        ):
            assert ch.rejoin_chain(cue, _mtc(20000)) is False

    def test_a_stamp_without_an_anchor_is_not_rejoined(self):
        """A manual-GO/go_at_end pass has no seed; its arrival is derived from
        live MTC by the thread, so there is nothing to pin a rejoin to."""
        ch = _ch()
        cue = _cue("B", prewait=10)
        cue._chain_pass = (5, None)
        ch._chain_epoch = 5
        with patch.object(CueHandler, "go") as go:
            assert ch.rejoin_chain(cue, _mtc(0)) is False
        go.assert_not_called()

    def test_a_disabled_cue_is_not_rejoined(self):
        ch = _ch()
        cue = self._stamped(ch, prewait=60)
        cue.enabled = False
        with patch.object(CueHandler, "go") as go:
            assert ch.rejoin_chain(cue, _mtc(20000)) is False
        go.assert_not_called()


class TestDisableThenReEnable:
    """The most ordinary operator sequence: disable a scheduled cue, change
    your mind, enable it again before its slot. It must still fire."""

    def test_a_cancelled_parked_cue_is_restamped_and_can_rejoin(self):
        ch = _ch()
        cue = _cue("B", prewait=60)
        cue._dispatch_arrival_ms = 0.0
        cue._playing = True  # dispatched and parked
        ch._chain_epoch = 4

        assert ch.cancel_parked(cue) is True
        assert cue._stop_requested is True
        assert cue._chain_pass[1] == 0.0, "must remember its anchor"
        ch.communications_thread.remove_cue.assert_called_once()

        cue.enabled = True
        with patch.object(CueHandler, "go_threaded"):
            assert ch.rejoin_chain(cue, _mtc(20000)) is True

    def test_a_playing_cue_is_never_cancelled(self):
        ch = _ch()
        cue = _cue("B")
        cue._revealed = True
        cue._playing = True
        assert ch.cancel_parked(cue) is False
        assert cue._stop_requested is False

    def test_an_idle_cue_is_not_touched(self):
        ch = _ch()
        cue = _cue("B")
        cue._playing = False
        assert ch.cancel_parked(cue) is False
