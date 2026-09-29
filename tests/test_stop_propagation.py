# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Phase 2 increment 3 — a stop takes its scheduled descendants with it.

Auto continue now dispatches the whole chain from the trigger, so by the time
an ActionCue stops cue k, the cues after k are already dispatched and parked on
their own anchors. They must not fire: a chained cue only exists because its
predecessor ran. Previously this fell out of the dispatch order for free — the
`_stop_requested` guard sat right before the fire — and that guard has now
moved to chain entry, so the cancellation has to be explicit.

What must NOT be cancelled: anything that has already produced output. A cue
that is playing keeps playing (never auto-stop a running cue), and the walk
continues past it to the cues behind it — those still depend on the cue that
was stopped.

Each node runs this on its own object graph: ActionCues are local everywhere,
so every engine cancels its own local segment and the union covers the cluster.

Design: Plans/prewait-dispatch-reorder-phase2.md §5 (cuems-RELATIONS).
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.tools.Uuid import Uuid  # noqa: E402

from cuemsengine.cues import ActionHandler as AH  # noqa: E402
from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _cue(id, post_go="go", local=True, enabled=True, revealed=False, target=None):
    return SimpleNamespace(
        id=id,
        post_go=post_go,
        _local=local,
        enabled=enabled,
        _revealed=revealed,
        _target_object=target,
        _stop_requested=False,
        _go_generation=1,
        _playing=True,
    )


def _chain(*cues):
    """Link cues front to back and return the head."""
    for a, b in zip(cues, cues[1:]):
        a._target_object = b
    return cues[0]


def _ch():
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    return ch


class TestCancelWalk:
    def test_cancels_every_parked_descendant_transitively(self):
        a, b, c = _cue("A"), _cue("B"), _cue("C")
        _chain(a, b, c)
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 2
        assert b._stop_requested is True and c._stop_requested is True
        assert b._playing is False and c._playing is False
        assert a._stop_requested is False, "the walk starts BELOW the target"

    def test_stops_at_a_chain_break(self):
        a, b = _cue("A"), _cue("B", post_go="pause")
        d = _cue("D")  # behind the break: a separate hand-off, not a descendant
        _chain(a, b, d)
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 1
        assert b._stop_requested is True
        assert d._stop_requested is False

    def test_a_playing_cue_survives_and_the_walk_continues_past_it(self):
        """B is already on stage: it keeps playing. C is still parked, and it
        only got dispatched because A ran — so C dies."""
        a, b, c = _cue("A"), _cue("B", revealed=True), _cue("C")
        _chain(a, b, c)
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 1
        assert b._stop_requested is False and b._playing is True
        assert c._stop_requested is True

    def test_non_local_cues_are_skipped_but_not_a_wall(self):
        """Another node owns B and cancels it there; C is ours."""
        a, b, c = _cue("A"), _cue("B", local=False), _cue("C")
        _chain(a, b, c)
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 1
        assert c._stop_requested is True

    def test_no_walk_when_the_target_is_not_auto_continue(self):
        a, b = _cue("A", post_go="pause"), _cue("B")
        _chain(a, b)
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 0
        assert b._stop_requested is False

    def test_a_cycle_cancels_each_cue_exactly_once(self):
        """Circular projects are a supported shape (an ActionCue 'play' loops
        back). Without a visited set the walk re-marks the same cues on every
        revolution: ~1000 'cancelled' cues in the operator's log and one
        remove_cue send each."""
        a, b, c = _cue("A"), _cue("B"), _cue("C")
        _chain(a, b, c)
        c._target_object = a  # loop back to the head
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 2
        assert ch.communications_thread.remove_cue.call_count == 2

    def test_a_cue_owned_by_a_newer_pass_is_left_alone(self):
        """A loop-back can re-schedule a cue against a fresh trigger while an
        older pass is still running. Stopping the old pass must not kill the
        new one's cue."""
        a, b = _cue("A"), _cue("B")
        _chain(a, b)
        a._go_epoch = 4  # the pass being stopped
        b._go_epoch = 6  # already re-dispatched by a newer pass
        ch = _ch()
        ch._chain_epoch = 6
        assert ch.cancel_pending_descendants(a) == 0
        assert b._stop_requested is False

    def test_end_of_chain_terminates(self):
        a = _cue("A")
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 0

    def test_works_with_real_cue_ids(self):
        """A cue's id is a Uuid, not a str. Caught on the test rig: the
        summary log line joined the ids and raised inside the very call that
        was supposed to report the cancellation."""
        a, b = _cue(Uuid()), _cue(Uuid())
        _chain(a, b)
        ch = _ch()
        assert ch.cancel_pending_descendants(a) == 1
        assert b._stop_requested is True


class TestIllumination:
    def test_every_cancelled_cue_loses_its_highlight(self):
        """The chain lit up at the trigger and a cancelled cue's thread exits
        through the generation guard, which is upstream of the usual
        remove_cue — so without this the UI shows dead cues as running."""
        a, b, c = _cue("A"), _cue("B"), _cue("C")
        _chain(a, b, c)
        ch = _ch()
        ch.cancel_pending_descendants(a)
        cleared = {
            call.args[0] for call in ch.communications_thread.remove_cue.call_args_list
        }
        assert cleared == {"B", "C"}

    def test_a_playing_cue_keeps_its_highlight(self):
        a, b = _cue("A"), _cue("B", revealed=True)
        _chain(a, b)
        ch = _ch()
        ch.cancel_pending_descendants(a)
        ch.communications_thread.remove_cue.assert_not_called()


class TestEpochMarking:
    def test_a_cancelled_descendant_refuses_an_in_flight_dispatch(self):
        """Its go() may be mid-arm right now; the epoch mark makes that
        dispatch decline when it finally reaches the commit."""
        a, b = _cue("A"), _cue("B")
        _chain(a, b)
        ch = _ch()
        ch._chain_epoch = 4
        ch.cancel_pending_descendants(a)
        assert b._go_epoch == 5

    def test_a_disabled_descendant_is_marked_so_it_cannot_rejoin(self):
        """Enabling it later must not resurrect a stopped cue's descendant.

        The stamp was written when the chain was dispatched (pass 2); the stop
        comes after, so its mark is necessarily newer and outranks it.
        """
        a, b = _cue("A"), _cue("B", enabled=False)
        _chain(a, b)
        b._chain_pass = (2, 0.0)
        ch = _ch()
        ch._chain_epoch = 2
        ch.cancel_pending_descendants(a)
        assert b._go_epoch == 3
        assert b._go_epoch > b._chain_pass[0], "the stamp must be outranked"


class TestActionHandlers:
    """The handlers that end a cue must all take its chain with them.

    (A version-1 fade_out reaches the engine as a stop — the library converts
    it on read — so the stop case covers it.)
    """

    def _target(self):
        t, nxt = _cue("T"), _cue("N")
        _chain(t, nxt)
        return t, nxt

    def test_stop_cancels_descendants(self):
        t, nxt = self._target()
        ch = MagicMock()
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            AH._handle_stop(ch, None, t, MagicMock())
        ch.cancel_pending_descendants.assert_called_once_with(t)

    def test_pause_cancels_descendants_but_leaves_its_target_alone(self):
        """pause deliberately does not bump the target's generation — the
        postwait tail depends on that — but its chain still must not run."""
        t, nxt = self._target()
        gen_before = t._go_generation
        ch = MagicMock()
        AH._handle_pause(ch, None, t, MagicMock())
        ch.cancel_pending_descendants.assert_called_once_with(t)
        assert t._stop_requested is True
        assert t._go_generation == gen_before

    def test_an_already_stopped_target_does_not_re_walk(self):
        t, nxt = self._target()
        t._stop_requested = True
        ch = MagicMock()
        AH._handle_stop(ch, None, t, MagicMock())
        ch.cancel_pending_descendants.assert_not_called()
