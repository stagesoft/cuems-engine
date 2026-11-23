# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Phase 2 increment 3 — a stop takes its scheduled descendants with it, up
to itself (1amfwm7jnqf, D9, X1).

Auto continue dispatches the whole chain from the trigger, so by the time an
ActionCue stops cue k, the cues after k are already dispatched and parked on
their own anchors. They must not fire: a chained cue only exists because its
predecessor ran.

Since 1amfwm7jnqf the walk is the TARGET'S PASS'S LAYOUT behind the target,
up to the stop action itself (`until`, D9: "A, Stop A, Z": Z plays), over the
cues due AFTER the stop action's own start (S41). A cue belongs to that pass
while its `_pass` is the target's (in place of `_go_epoch <= target_epoch`):
so a remote target is no longer a blind spot (X1, S45; on rc_1 S46), and a
disabled target is treated like any other (S48).

What must NOT be cancelled: anything that has already produced output. A cue
that is playing keeps playing (never auto-stop a running cue), and the walk
continues past it to the cues behind it.

Each node runs this on its own object graph: ActionCues are local everywhere,
so every engine cancels its own local segment and the union covers the cluster.

Design: Plans/prewait-dispatch-reorder-phase2.md §5; Plans/2026-11-18-
autocontinue-cumulative-waits.md Design §5 (cuems-RELATIONS).
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402
from cuemsutils.tools.Uuid import Uuid  # noqa: E402

from cuemsengine.cues import ActionHandler as AH  # noqa: E402
from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _cue(
    id,
    post_go="go",
    local=True,
    enabled=True,
    revealed=False,
    target=None,
    prewait_s=0.0,
):
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
        prewait=CTimecode(start_seconds=prewait_s),
        postwait=CTimecode(start_seconds=0),
    )


def _pass(epoch, anchor_ms, layout):
    """A chain_pass.Pass; before Step 2 the engine has none, and the walk
    tests that do not depend on it need only its attributes."""
    try:
        from cuemsengine.cues.chain_pass import Pass
    except ImportError:
        layout = list(layout)
        return SimpleNamespace(
            epoch=epoch,
            anchor_ms=anchor_ms,
            layout=layout,
            root_seq=0,
            mode="sequential",
            arrival_of=lambda c: next((a for x, a in layout if x is c), None),
        )
    return Pass(epoch=epoch, anchor_ms=anchor_ms, layout=list(layout))


def _chain(*cues, anchor_ms=0.0, epoch=1, arrivals=None):
    """Link cues front to back, lay them out as one pass (every cue at the
    anchor unless `arrivals` says otherwise) and return the head."""
    for a, b in zip(cues, cues[1:]):
        a._target_object = b
    arrivals = arrivals or [anchor_ms] * len(cues)
    p = _pass(epoch, anchor_ms, list(zip(cues, arrivals)))
    for c in cues:
        c._pass = p
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
        new one's cue: B's `_pass` is no longer the target's."""
        a, b = _cue("A"), _cue("B")
        _chain(a, b, epoch=4)
        b._pass = _pass(6, 9000.0, [(b, 9000.0)])  # re-dispatched by pass 6
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


class TestActionHandlers:
    """The three handlers that end a cue must all take its chain with them,
    up to themselves: the walk gets the action cue as `until` (D9)."""

    def _target(self):
        t, nxt = _cue("T"), _cue("N")
        _chain(t, nxt)
        return t, nxt

    def _action(self):
        return SimpleNamespace(id="S", post_go="go", _target_object=None)

    def test_stop_cancels_descendants(self):
        t, nxt = self._target()
        ch, s = MagicMock(), self._action()
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            AH._handle_stop(ch, s, t, MagicMock())
        ch.cancel_pending_descendants.assert_called_once_with(t, until=s)

    def test_fade_out_cancels_descendants(self):
        t, nxt = self._target()
        ch, s = MagicMock(), self._action()
        AH._handle_fade_out(ch, s, t, MagicMock())
        ch.cancel_pending_descendants.assert_called_once_with(t, until=s)

    def test_pause_cancels_descendants_but_leaves_its_target_alone(self):
        """pause deliberately does not bump the target's generation — the
        postwait tail depends on that — but its chain still must not run."""
        t, nxt = self._target()
        gen_before = t._go_generation
        ch, s = MagicMock(), self._action()
        AH._handle_pause(ch, s, t, MagicMock())
        ch.cancel_pending_descendants.assert_called_once_with(t, until=s)
        assert t._stop_requested is True
        assert t._go_generation == gen_before

    def test_an_already_stopped_target_does_not_re_walk(self):
        t, nxt = self._target()
        t._stop_requested = True
        ch = MagicMock()
        AH._handle_stop(ch, self._action(), t, MagicMock())
        ch.cancel_pending_descendants.assert_not_called()

    def test_a_disabled_target_is_stopped_like_any_other(self):
        """S48: a stop aimed at a disabled cue acts as on any other."""
        t, nxt = self._target()
        t.enabled = False
        ch, s = MagicMock(), self._action()
        with patch("cuemsengine.cues.ActionHandler.time.sleep"):
            res = AH._handle_stop(ch, s, t, MagicMock())
        assert res["status"] == "applied"
        assert t._stop_requested is True
        ch.cancel_pending_descendants.assert_called_once_with(t, until=s)


class TestScopeUntilTheStop:
    """D9 and X1 (Design §5): the walk is the target's pass's layout behind
    the target, up to the stop action, over the cues due after the stop
    action's own start, owned by `_pass`. Arrivals in ms, sequential."""

    def test_a_stop_takes_nothing_behind_itself(self):
        """S42, "A, Stop A, Z": A 0/0 → S (stop A) 5/0 → Z 2/0: Z plays."""
        a = _cue("A")
        s = _cue("S", prewait_s=5.0)
        z = _cue("Z", post_go="pause", prewait_s=2.0)
        _chain(a, s, z, arrivals=[0.0, 0.0, 5000.0])
        ch = _ch()
        assert ch.cancel_pending_descendants(a, until=s) == 0
        assert z._stop_requested is False and z._playing is True

    def test_a_cue_due_at_the_stop_s_instant_is_not_cut(self):
        """S41: A → Q 5/0 → S (stop A) → Z, the last three due at +5. Q's
        thread is late (not revealed yet) but it is due at the stop's own
        instant, not after: it plays; so does Z, behind the stop."""
        a = _cue("A")
        q = _cue("Q", prewait_s=5.0)
        s = _cue("S")
        z = _cue("Z", post_go="pause")
        _chain(a, q, s, z, arrivals=[0.0, 0.0, 5000.0, 5000.0])
        ch = _ch()
        assert ch.cancel_pending_descendants(a, until=s) == 0
        assert q._stop_requested is False and z._stop_requested is False

    def test_a_stop_from_another_pass_cuts_what_is_due_after_it(self):
        """The stop K is in a pass of its own (anchor +5); every pending cue
        of A's pass due after +5 is cut, to the end of A's chain."""
        a = _cue("A")
        b = _cue("B", prewait_s=30.0)
        c = _cue("C", post_go="pause")
        _chain(a, b, c, arrivals=[0.0, 0.0, 30000.0])
        k = _cue("K", post_go="pause")
        k._pass = _pass(2, 5000.0, [(k, 5000.0)])
        ch = _ch()
        assert ch.cancel_pending_descendants(a, until=k) == 2
        assert b._stop_requested is True and c._stop_requested is True

    def test_a_pending_cue_due_before_the_stop_is_left_alone(self):
        """A stop from another pass at +30 over a chain whose B is due at +30
        (its thread late, not revealed) and C at +60: only C is cut."""
        a = _cue("A")
        b = _cue("B", prewait_s=30.0)
        c = _cue("C", post_go="pause", prewait_s=30.0)
        _chain(a, b, c, arrivals=[0.0, 0.0, 30000.0])
        k = _cue("K", post_go="pause")
        k._pass = _pass(2, 30000.0, [(k, 30000.0)])
        ch = _ch()
        assert ch.cancel_pending_descendants(a, until=k) == 1
        assert b._stop_requested is False and c._stop_requested is True

    def test_a_remote_target_still_cuts_this_node_s_cues(self):
        """S45 (X1): A is another node's and was never dispatched here, so
        its `_go_epoch` is 0, while B and C, ours, were (pass 1). On rc_1
        `node._go_epoch <= target_epoch` left them playing (S46); they carry
        A's pass, so they are cut."""
        a = _cue("A", local=False)
        b = _cue("B", prewait_s=30.0)
        c = _cue("C", post_go="pause")
        _chain(a, b, c, arrivals=[0.0, 0.0, 30000.0])
        a._go_epoch, b._go_epoch, c._go_epoch = 0, 1, 1
        k = _cue("K", post_go="pause")
        k._pass = _pass(2, 5000.0, [(k, 5000.0)])
        ch = _ch()
        ch._chain_epoch = 2
        assert ch.cancel_pending_descendants(a, until=k) == 2
        assert b._stop_requested is True and c._stop_requested is True

    def test_a_disabled_target_takes_its_chain_too(self):
        """S48: Q (5/0, disabled) is stopped before its start, and B behind
        it is cut with it."""
        q = _cue("Q", enabled=False, prewait_s=5.0)
        b = _cue("B", post_go="pause", prewait_s=30.0)
        _chain(q, b, arrivals=[0.0, 5000.0])
        k = _cue("K", post_go="pause")
        k._pass = _pass(2, 3000.0, [(k, 3000.0)])
        ch = _ch()
        assert ch.cancel_pending_descendants(q, until=k) == 1
        assert b._stop_requested is True

    def test_a_disabled_cue_behind_the_target_is_cut_too(self):
        """Its silent thread is cancelled like any other (Design §5), so a
        later enable finds nothing to retake (S49)."""
        a = _cue("A")
        x = _cue("X", enabled=False, prewait_s=30.0)
        z = _cue("Z", post_go="pause", prewait_s=40.0)
        _chain(a, x, z, arrivals=[0.0, 0.0, 30000.0])
        k = _cue("K", post_go="pause")
        k._pass = _pass(2, 5000.0, [(k, 5000.0)])
        ch = _ch()
        assert ch.cancel_pending_descendants(a, until=k) == 2
        assert x._stop_requested is True and x._playing is False
