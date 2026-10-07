# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""CueHandler.arm(): publish or abandon (869f9wqpn).

A background thread used to decide an arm was stale AFTER arm() had published
the cue, and then disarm it -- by which time the operator's next GO could
already be playing it. The decision now lives inside arm(), before the cue
becomes visible as armed:

- one arm in flight per cue ID (not per object): players, JACK client names
  and video layers are keyed by id, and Cue.__eq__/__hash__ are by id, so two
  objects of the same cue (the old and the new load of one project) must
  exclude each other;
- a thread that waited on someone else's arm and finds the cue still unarmed
  arms it itself, within one total wait budget.

Design: cuems-RELATIONS Plans/2026-09-30-engine-prearm-publish-or-abandon.md.
"""

from __future__ import annotations

import sys
import time
from threading import Event, Lock, Thread
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import ActionCue  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402

ARM_CUE = "cuemsengine.cues.CueHandler.arm_cue"


def _handler() -> CueHandler:
    """A real CueHandler with only the state arm()/disarm()/go() touch."""
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    return ch


def _cue(cue_id=None, post_go="pause", target=None):
    """ActionCue: arm_cue() is a no-op for it, so no players are involved."""
    cue = ActionCue()
    if cue_id is not None:
        cue.id = cue_id
    cue.enabled = True
    cue.loaded = False
    cue._local = True
    cue.action_type = "enable"
    cue._action_target_object = None
    cue._target_object = target
    cue.post_go = post_go
    return cue


def _until(predicate, timeout=2.0):
    """Poll `predicate` until it is true; fail the test if it never is."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached in time")


def _claim(ch, cue):
    # The registry is created lazily, by the first arm().
    return getattr(ch, "_arming", {}).get(cue.id)


def _waiters(ch, cue):
    claim = _claim(ch, cue)
    return claim.waiters if claim is not None else 0


def _spawn(fn, *args, **kwargs):
    """Run fn in a thread; the result lands in the returned dict."""
    out = {}

    def run():
        out["result"] = fn(*args, **kwargs)

    thread = Thread(target=run, daemon=True)
    thread.start()
    out["thread"] = thread
    return out


class TestOneArmPerCueId:
    def test_a_claim_is_held_while_arming_and_freed_after(self):
        ch = _handler()
        cue = _cue()
        seen = []

        def arming(c):
            seen.append(_claim(ch, c) is not None)

        with patch(ARM_CUE, side_effect=arming):
            assert ch.arm(cue, init=True) is True

        assert seen == [True]
        assert _claim(ch, cue) is None, "claim leaked -- the next arm would hang"

    def test_a_failed_arm_frees_the_claim(self):
        ch = _handler()
        cue = _cue()
        with patch(ARM_CUE, side_effect=ValueError("boom")):
            assert ch.arm(cue, init=True) is False
        assert _claim(ch, cue) is None

    def test_two_objects_of_the_same_cue_id_exclude_each_other(self):
        """The old and the new load of one project hold different objects of
        the same cue. Their players / JACK names / layers are keyed by id, so
        their arms must never overlap."""
        ch = _handler()
        old = _cue()
        new = _cue(cue_id=old.id)
        assert old is not new and old == new
        gate = Event()
        events = []

        def arming(c):
            which = "old" if c is old else "new"
            events.append(f"{which}-in")
            if c is old:
                gate.wait(2.0)
            events.append(f"{which}-out")

        with patch(ARM_CUE, side_effect=arming):
            a = _spawn(ch.arm, old, init=True)
            _until(lambda: events == ["old-in"])
            b = _spawn(ch.arm, new, init=True)
            _until(lambda: _waiters(ch, old) == 1)
            assert events == ["old-in"], "the second object armed concurrently"
            gate.set()
            a["thread"].join(2.0)
            b["thread"].join(2.0)

        assert events[:2] == ["old-in", "old-out"]
        assert _claim(ch, old) is None

    def test_a_go_chain_cycle_does_not_deadlock_on_its_own_claim(self):
        """A -> B -> A: the claim is released before arm() recurses."""
        ch = _handler()
        a = _cue(post_go="go")
        b = _cue(post_go="go", target=a)
        a._target_object = b

        with patch(ARM_CUE):
            out = _spawn(ch.arm, a, init=True)
            out["thread"].join(2.0)

        assert not out["thread"].is_alive(), "arm() deadlocked on a cycle"
        assert out["result"] is True
        assert a.loaded is True and b.loaded is True


class TestWaiter:
    def test_a_waiter_gets_the_cue_the_holder_armed(self):
        ch = _handler()
        cue = _cue()
        gate = Event()

        with patch(ARM_CUE, side_effect=lambda c: gate.wait(2.0)) as arm_cue:
            a = _spawn(ch.arm, cue, init=True)
            _until(lambda: _claim(ch, cue) is not None)
            b = _spawn(ch.arm, cue, init=True)
            _until(lambda: _waiters(ch, cue) == 1)
            gate.set()
            a["thread"].join(2.0)
            b["thread"].join(2.0)

        assert a["result"] is True and b["result"] is True
        assert arm_cue.call_count == 1, "the waiter armed a cue that was armed"

    def test_a_waiter_arms_the_cue_itself_when_the_holder_failed(self):
        """go()'s fallback used to give up ("cannot GO") when the arm it
        waited on did not load the cue. It must retry -- that is what lets a
        GO play a cue whose in-flight arm was dropped."""
        ch = _handler()
        cue = _cue()
        gate = Event()
        calls = []

        def arming(c):
            calls.append(len(calls))
            if len(calls) == 1:
                gate.wait(2.0)
                raise ValueError("first arm fails")

        with patch(ARM_CUE, side_effect=arming):
            a = _spawn(ch.arm, cue, init=True)
            _until(lambda: _claim(ch, cue) is not None)
            b = _spawn(ch.arm, cue, init=True)
            _until(lambda: _waiters(ch, cue) == 1)
            gate.set()
            a["thread"].join(2.0)
            b["thread"].join(2.0)

        assert a["result"] is False
        assert b["result"] is True
        assert cue.loaded is True
        assert len(calls) == 2
        assert _claim(ch, cue) is None

    def test_the_wait_is_bounded_and_a_spent_waiter_does_not_arm(self):
        ch = _handler()
        cue = _cue()
        gate = Event()

        with (
            patch.object(CueHandler, "_ARM_WAIT_TIMEOUT_S", 0.15),
            patch(ARM_CUE, side_effect=lambda c: gate.wait(3.0)) as arm_cue,
        ):
            a = _spawn(ch.arm, cue, init=True)
            _until(lambda: _claim(ch, cue) is not None)
            started = time.monotonic()
            result = ch.arm(cue, init=True)
            waited = time.monotonic() - started
            gate.set()
            a["thread"].join(3.0)

        assert result is False
        assert 0.1 <= waited < 1.0
        assert arm_cue.call_count == 1

    def test_a_non_init_arm_does_not_wait(self):
        ch = _handler()
        cue = _cue()
        gate = Event()

        with patch(ARM_CUE, side_effect=lambda c: gate.wait(2.0)):
            a = _spawn(ch.arm, cue, init=True)
            _until(lambda: _claim(ch, cue) is not None)
            assert ch.arm(cue, init=False) is False
            gate.set()
            a["thread"].join(2.0)


# ---------------------------------------------------------------------------
# The epoch: an arm belongs to the STOP/load epoch in which it was requested
# ---------------------------------------------------------------------------

PLAYERS = "cuemsengine.cues.CueHandler.PLAYER_HANDLER"


def _mtc(ms=0.0):
    mtc = MagicMock()
    mtc.main_tc.milliseconds_exact = float(ms)
    mtc.main_tc.milliseconds_rounded = int(ms)
    return mtc


def _stop(ch):
    """What a STOP does to the handler, in its real order: stop_all_cues()
    first, the teardown in between, disarm_all() last."""
    ch.stop_all_cues()
    ch.disarm_all()


class TestEpoch:
    def test_stop_all_cues_moves_the_epoch(self):
        """The epoch must move when the STOP BEGINS: between stop_all_cues()
        and disarm_all() the engine resets DMX and video and kills every
        audio player, which can take seconds."""
        ch = _handler()
        before = ch._disarm_epoch
        ch.stop_all_cues()
        assert ch._disarm_epoch == before + 1

    def test_disarm_all_moves_the_epoch(self):
        ch = _handler()
        before = ch._disarm_epoch
        ch.disarm_all()
        assert ch._disarm_epoch > before

    def test_an_arm_requested_in_an_older_epoch_is_refused_at_entry(self):
        ch = _handler()
        cue = _cue()
        stale = ch._disarm_epoch
        ch.stop_all_cues()
        with patch(ARM_CUE) as arm_cue:
            assert ch.arm(cue, init=True, epoch=stale) is False
        arm_cue.assert_not_called()
        assert cue.loaded is False
        assert _claim(ch, cue) is None

    def test_a_stale_request_does_not_adopt_a_cue_the_new_epoch_armed(self):
        ch = _handler()
        cue = _cue()
        stale = ch._disarm_epoch
        ch.stop_all_cues()
        with patch(ARM_CUE):
            assert ch.arm(cue, init=True) is True  # the new epoch's own arm
            assert ch.arm(cue, init=True, epoch=stale) is False

    def test_a_walk_carries_its_epoch(self):
        from cuemsengine.cues.CueHandler import _ArmWalk

        ch = _handler()
        cue = _cue()
        walk = _ArmWalk(epoch=ch._disarm_epoch)
        ch.stop_all_cues()
        with patch(ARM_CUE) as arm_cue:
            assert ch.arm(cue, init=True, walk=walk) is False
        arm_cue.assert_not_called()
        assert walk.armed == []

    def test_the_post_go_recursion_inherits_the_epoch(self):
        """A STOP landing between the parent's publish and its recursion
        must stop the chain arm there."""
        from cuemsengine.cues.CueHandler import _ArmWalk

        ch = _handler()
        child = _cue()
        parent = _cue(post_go="go", target=child)

        class _StopOnAppend(list):
            def append(self, item):
                super().append(item)
                ch.stop_all_cues()

        walk = _ArmWalk(epoch=ch._disarm_epoch)
        walk.armed = _StopOnAppend()
        with patch(ARM_CUE) as arm_cue:
            ch.arm(parent, init=True, walk=walk)

        assert [c.args[0] for c in arm_cue.call_args_list] == [parent]
        assert child.loaded is False

    def test_arm_ahead_hands_its_epoch_to_the_walk(self):
        ch = _handler()
        nxt = _cue()
        start = _cue(target=nxt)
        stale = ch._disarm_epoch
        ch.stop_all_cues()
        with patch(ARM_CUE) as arm_cue:
            assert ch._arm_ahead(start, arm_epoch=stale) == []
        arm_cue.assert_not_called()
        assert nxt.loaded is False


class TestPublishOrAbandon:
    def test_an_arm_straddling_a_stop_is_never_published(self):
        ch = _handler()
        cue = _cue()
        gate = Event()
        with (
            patch(ARM_CUE, side_effect=lambda c: gate.wait(2.0)),
            patch(PLAYERS) as players,
        ):
            a = _spawn(ch.arm, cue, init=True)
            _until(lambda: _claim(ch, cue) is not None)
            _stop(ch)
            gate.set()
            a["thread"].join(2.0)

        assert a["result"] is False
        assert cue.loaded is False
        assert cue.id not in ch._armed_cues_set and cue not in ch._armed_cues
        players.remove_cue_player.assert_called_once_with(cue)
        assert _claim(ch, cue) is None

    def test_an_arm_finishing_inside_the_teardown_is_abandoned(self):
        """After stop_all_cues() but before disarm_all(): the players are
        being killed right now. Publishing here would let the caller reveal
        the cue in the middle of the STOP."""
        ch = _handler()
        cue = _cue()
        gate = Event()
        with (
            patch(ARM_CUE, side_effect=lambda c: gate.wait(2.0)),
            patch(PLAYERS) as players,
        ):
            a = _spawn(ch.arm, cue, init=True)
            _until(lambda: _claim(ch, cue) is not None)
            ch.stop_all_cues()
            gate.set()
            a["thread"].join(2.0)
            assert a["result"] is False
            assert cue.loaded is False
            players.remove_cue_player.assert_called_once_with(cue)
            ch.disarm_all()

        players.remove_cue_player.assert_called_once_with(cue)

    def test_an_arm_published_before_the_stop_is_disarmed_by_it(self):
        ch = _handler()
        cue = _cue()
        with patch(ARM_CUE), patch(PLAYERS):
            assert ch.arm(cue, init=True) is True
            _stop(ch)
        assert cue.loaded is False
        assert cue.id not in ch._armed_cues_set

    def test_a_cue_armed_while_disarm_all_disarms_its_snapshot_survives(self):
        """disarm_all used to clear the armed list AFTER its loop, wiping any
        cue published meanwhile: loaded but not in the list, so arm() said
        'already armed', find_armed_cue said no, and it was unplayable until
        a reload."""
        ch = _handler()
        old = _cue()
        fresh = _cue()
        real_disarm = ch.disarm

        def disarm_and_arm_another(cue):
            result = real_disarm(cue)
            ch.arm(fresh, init=True)  # a current-epoch arm, mid-loop
            return result

        with patch(ARM_CUE), patch(PLAYERS):
            ch.arm(old, init=True)
            with patch.object(ch, "disarm", side_effect=disarm_and_arm_another):
                ch.disarm_all()

        assert fresh.loaded is True
        assert fresh.id in ch._armed_cues_set and fresh in ch._armed_cues
        assert ch.find_armed_cue(fresh)

    def test_a_cue_disabled_while_arming_is_abandoned(self):
        ch = _handler()
        cue = _cue()

        def disabled_meanwhile(c):
            c.enabled = False

        with patch(ARM_CUE, side_effect=disabled_meanwhile), patch(PLAYERS) as players:
            assert ch.arm(cue, init=True) is False
        assert cue.loaded is False
        assert cue.id not in ch._armed_cues_set
        players.remove_cue_player.assert_called_once_with(cue)

    def test_a_failed_arm_releases_what_it_built(self):
        ch = _handler()
        cue = _cue()
        with patch(ARM_CUE, side_effect=ValueError("boom")), patch(PLAYERS) as players:
            assert ch.arm(cue, init=True) is False
        players.remove_cue_player.assert_called_once_with(cue)

    def test_a_release_that_raises_still_frees_the_claim(self):
        ch = _handler()
        abandoned = _cue()
        failed = _cue()

        with patch(PLAYERS) as players:
            players.remove_cue_player.side_effect = RuntimeError("release failed")
            with patch(ARM_CUE, side_effect=lambda c: ch.stop_all_cues()):
                assert ch.arm(abandoned, init=True) is False
            with patch(ARM_CUE, side_effect=ValueError("boom")):
                assert ch.arm(failed, init=True) is False

        assert _claim(ch, abandoned) is None
        assert _claim(ch, failed) is None

    def test_the_next_runs_go_arms_fresh_and_nothing_disarms_it(self):
        """The PR #22 build 3 blocker. GO 1 starts a background arm; STOP
        lands mid-arm; the restarted run's GO finds the cue unarmed and waits
        on that arm. It must end up with a cue it armed itself, playing, and
        no thread may disarm it afterwards."""
        ch = _handler()
        cue = _cue()
        gate = Event()
        events = []

        def arming(c):
            events.append("arm")
            if events.count("arm") == 1:
                gate.wait(2.0)

        with (
            patch(ARM_CUE, side_effect=arming),
            patch(PLAYERS) as players,
            patch.object(CueHandler, "go_threaded"),
        ):
            players.remove_cue_player.side_effect = lambda c: events.append("release")
            stale = _spawn(ch.arm, cue, init=True)  # GO 1's PreArm thread
            _until(lambda: _claim(ch, cue) is not None)
            _stop(ch)
            new_run = _spawn(ch.arm, cue, init=True)  # GO 2' on the command thread
            _until(lambda: _waiters(ch, cue) == 1)  # ...really parked on the claim
            gate.set()
            stale["thread"].join(2.0)
            new_run["thread"].join(2.0)

            assert stale["result"] is False
            assert new_run["result"] is True
            assert events == ["arm", "release", "arm"]

            with patch.object(ch, "disarm", wraps=ch.disarm) as disarm:
                thread = ch.go(cue, _mtc())
                assert thread is not None
                time.sleep(0.05)  # room for a stray background disarm
                disarm.assert_not_called()

        assert cue.loaded is True
        assert cue._playing is True
        assert ch.find_armed_cue(cue)

    def test_a_stale_arm_of_the_old_object_never_touches_the_new_objects_player(self):
        """Same project loaded again: old and new object share the cue id,
        and the player registry is keyed by it."""
        ch = _handler()
        old = _cue()
        new = _cue(cue_id=old.id)
        gate = Event()
        events = []

        def arming(c):
            events.append("arm-old" if c is old else "arm-new")
            if c is old:
                gate.wait(2.0)

        with patch(ARM_CUE, side_effect=arming), patch(PLAYERS) as players:
            players.remove_cue_player.side_effect = lambda c: events.append(
                "release-old" if c is old else "release-new"
            )
            a = _spawn(ch.arm, old, init=True)
            _until(lambda: _claim(ch, old) is not None)
            _stop(ch)
            b = _spawn(ch.arm, new, init=True)
            _until(lambda: _waiters(ch, new) == 1)
            gate.set()
            a["thread"].join(2.0)
            b["thread"].join(2.0)

        assert events == ["arm-old", "release-old", "arm-new"]
        assert old.loaded is False
        assert new.loaded is True


class TestNoPlayAfterStop:
    """A cue dispatched before a STOP must not be armed -- and so not played
    -- after it, whoever ends up doing the arming.

    rc5 line: a chain continuation is dispatched by the PREVIOUS cue's thread
    calling go(), whose fallback arm runs right there, and this line has no
    other STOP barrier in go() (the chain epoch is rc_1 only). go() used to
    reset _stop_requested unconditionally after that arm and start the cue.
    """

    def test_a_go_waiting_on_another_arm_gives_up_at_the_stop(self):
        ch = _handler()
        cue = _cue()
        gate = Event()
        with (
            patch(ARM_CUE, side_effect=lambda c: gate.wait(2.0)) as arm_cue,
            patch(PLAYERS),
            patch.object(CueHandler, "go_threaded") as go_threaded,
        ):
            prearm = _spawn(ch.arm, cue, init=True)
            _until(lambda: _claim(ch, cue) is not None)
            go = _spawn(ch.go, cue, _mtc())
            _until(lambda: _waiters(ch, cue) == 1)
            _stop(ch)
            gate.set()
            prearm["thread"].join(2.0)
            go["thread"].join(2.0)

            assert go.get("result", "raised") is None
            assert arm_cue.call_count == 1, "the stale go() re-armed the cue"
            go_threaded.assert_not_called()
        assert cue.loaded is False

    def test_a_go_arming_its_own_cue_abandons_it_at_the_stop(self):
        ch = _handler()
        cue = _cue()
        gate = Event()
        with (
            patch(ARM_CUE, side_effect=lambda c: gate.wait(2.0)),
            patch(PLAYERS) as players,
            patch.object(CueHandler, "go_threaded") as go_threaded,
        ):
            go = _spawn(ch.go, cue, _mtc())
            _until(lambda: _claim(ch, cue) is not None)
            ch.stop_all_cues()  # mid-teardown: disarm_all has not run yet
            gate.set()
            go["thread"].join(2.0)

            assert go.get("result", "raised") is None
            go_threaded.assert_not_called()
            players.remove_cue_player.assert_called_once_with(cue)
        assert cue.loaded is False

    def test_a_stop_between_the_arm_and_the_commit_is_not_wiped(self):
        """The fallback arm publishes the cue; the STOP flags it; go() then
        used to reset _stop_requested and start it anyway."""
        ch = _handler()
        cue = _cue()
        cue._stop_requested = False
        real_arm = ch.arm

        def arm_then_the_stop_lands(
            c, init=False, walk=None, epoch=None, wait_report=None
        ):
            result = real_arm(c, init=init, walk=walk, epoch=epoch)
            ch.stop_all_cues()
            return result

        ch.arm = arm_then_the_stop_lands
        with (
            patch(ARM_CUE),
            patch(PLAYERS),
            patch.object(CueHandler, "go_threaded") as go_threaded,
        ):
            assert ch.go(cue, _mtc()) is None

        go_threaded.assert_not_called()
        assert cue._stop_requested is True, "the STOP must survive go()"

    def test_a_go_does_not_start_a_cue_the_stops_own_rearm_loaded(self):
        from cuemsengine.cues.CueHandler import _ArmClaim

        ch = _handler()
        cue = _cue()
        claim = _ArmClaim(holder="PreArm")
        ch._arming = {cue.id: claim}
        with patch.object(CueHandler, "go_threaded") as go_threaded:
            go = _spawn(ch.go, cue, _mtc())
            _until(lambda: claim.waiters == 1)
            ch.stop_all_cues()
            cue.loaded = True  # the STOP's own re-arm, for the NEXT run
            ch._armed_cues.append(cue)
            ch._armed_cues_set.add(cue.id)
            del ch._arming[cue.id]
            claim.event.set()
            go["thread"].join(2.0)

            assert go.get("result", "raised") is None
            go_threaded.assert_not_called()

    def test_a_stale_waiter_does_not_adopt_the_new_epochs_arm(self):
        """The STOP's own re-arm may publish the cue before the stale waiter
        wakes. 'Loaded' is then true -- for the new run, not for the waiter."""
        from cuemsengine.cues.CueHandler import _ArmClaim

        ch = _handler()
        cue = _cue()
        claim = _ArmClaim(holder="PreArm")
        ch._arming = {cue.id: claim}
        waiter = _spawn(ch.arm, cue, init=True)  # requested before the STOP
        _until(lambda: claim.waiters == 1)

        ch.stop_all_cues()
        cue.loaded = True  # the new epoch armed it...
        ch._armed_cues.append(cue)
        ch._armed_cues_set.add(cue.id)
        del ch._arming[cue.id]
        claim.event.set()  # ...before the waiter got to look
        waiter["thread"].join(2.0)

        assert waiter["result"] is False

    def test_a_stale_waiter_timing_out_does_not_adopt_it_either(self):
        from cuemsengine.cues.CueHandler import _ArmClaim

        ch = _handler()
        cue = _cue()
        claim = _ArmClaim(holder="PreArm")
        ch._arming = {cue.id: claim}

        def stop_lands_and_the_new_epoch_arms(timeout=None):
            ch.stop_all_cues()
            cue.loaded = True
            return False  # timed out

        with patch.object(
            claim.event, "wait", side_effect=stop_lands_and_the_new_epoch_arms
        ):
            assert ch.arm(cue, init=True) is False


class TestGoCarriesTheEpoch:
    def test_go_hands_its_epoch_to_the_fallback_arm_and_the_lookahead(self):
        ch = _handler()
        cue = _cue()
        ch._arm_ahead = MagicMock()
        epoch = ch._disarm_epoch

        def arm(c, init=False, walk=None, epoch=None, wait_report=None):
            c.loaded = True

        ch.arm = MagicMock(side_effect=arm)
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc()) is not None

        assert ch.arm.call_args.kwargs["epoch"] == epoch
        ch._arm_ahead.assert_called_once_with(cue, arm_epoch=epoch)

    def test_a_stop_during_the_fallback_arm_returns_none_instead_of_raising(self):
        """The arm is refused because a STOP moved the epoch: that is the
        operator's STOP winning, not an arm failure to raise about."""
        ch = _handler()
        cue = _cue()
        cue._stop_requested = True

        def arm(c, init=False, walk=None, epoch=None, wait_report=None):
            ch.stop_all_cues()  # and the arm, stale now, loads nothing

        ch.arm = MagicMock(side_effect=arm)
        with patch.object(CueHandler, "go_threaded") as go_threaded:
            assert ch.go(cue, _mtc()) is None

        go_threaded.assert_not_called()
        assert cue._stop_requested is True

    def test_a_genuine_arm_failure_still_raises(self):
        import pytest

        ch = _handler()
        cue = _cue()
        ch.arm = MagicMock(return_value=False)
        with patch.object(CueHandler, "go_threaded"), pytest.raises(Exception):
            ch.go(cue, _mtc())

    def test_a_dispatch_whose_epoch_moved_is_refused_even_if_the_cue_is_loaded(self):
        ch = _handler()
        cue = _cue()
        cue.loaded = True
        stale = ch._disarm_epoch
        ch.stop_all_cues()
        with patch.object(CueHandler, "go_threaded") as go_threaded:
            assert ch.go(cue, _mtc(), arm_epoch=stale) is None
        go_threaded.assert_not_called()


def test_describe_arm_in_flight_names_the_holder():
    from cuemsengine.cues.CueHandler import _ArmClaim

    ch = _handler()
    cue = _cue()
    assert ch.describe_arm_in_flight(cue) is None
    ch._arming = {cue.id: _ArmClaim(holder="PreArm:x", started=time.monotonic() - 2)}
    text = ch.describe_arm_in_flight(cue)
    assert text.startswith("held by PreArm:x for 2.")
