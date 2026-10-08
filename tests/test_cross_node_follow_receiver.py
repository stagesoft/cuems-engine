# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Cross-node Auto follow, receiving side (ClickUp 869fc8ytz).

A node that does NOT own an Auto follow's source learns the follow instant from
the owner's announcement, relayed by the controller. It keeps one entry per
source cue, pre-arms what it would start, waits for the instant on MTC and
dispatches then, through `go_from`, with a commit gate that `go()` evaluates
inside its own commit section. The owner's cancel is applied by the state of
the entry:

  waiting / dispatching -> cancelled (the waiter ends, or the gate refuses)
  dispatched            -> handed to CueHandler.stop_dispatched_follow, which
                           applies the 2 s rule under its own lock

Messages are applied in bus order, in the receive hook; nothing here waits.

Design: cuems-RELATIONS Plans/2026-10-05-engine-cross-node-auto-follow.md §3.5.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.core.BaseEngine import BaseEngine  # noqa: E402
from cuemsengine.cues.FollowRelay import FollowRelay  # noqa: E402

ME, OWNER, OTHER = "node-me", "node-owner", "node-other"


class _Mtc:
    def __init__(self, ms=0.0):
        self.main_tc = SimpleNamespace(milliseconds_exact=float(ms))

    def set(self, ms):
        self.main_tc.milliseconds_exact = float(ms)


def _cue(id, local=False, post_go="pause", target=None, postwait=0, **kw):
    c = SimpleNamespace(
        id=id,
        _local=local,
        enabled=True,
        loaded=False,
        post_go=post_go,
        postwait=CTimecode(start_seconds=postwait),
        _target_object=target,
        _go_generation=0,
    )
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class _Script:
    def __init__(self, *cues):
        self.cues = {str(c.id): c for c in cues}

    def find(self, id):
        return self.cues.get(str(id))


class _Rig:
    """A FollowRelay wired to fakes. Threads are not started: `spawned`
    records them and the test runs them by hand."""

    def __init__(self, script, ms=0.0, run_seq=7):
        self.mtc = _Mtc(ms)
        self.ch = MagicMock()
        self.ch._disarm_epoch = 3
        self.ch._last_stop_chain_epoch = 2
        self.ch.arm_epoch.side_effect = lambda: self.ch._disarm_epoch
        self.ch.go_from.return_value = None
        self.ch.stop_dispatched_follow.return_value = ("stopped", None)
        self.sent = []
        self.spawned = []
        self.gen = [1]
        self.script = script
        self.relay = FollowRelay(
            self.ch,
            node_id=ME,
            send=self.sent.append,
            get_script=lambda: self.script,
            get_mtc=lambda: self.mtc,
            get_project_gen=lambda: self.gen[0],
            first_local=BaseEngine._first_local_enabled_in_go_chain,
            spawn=lambda name, fn, *a: self.spawned.append((name, fn, a)),
            sleep=lambda s: self.mtc.set(self.mtc.main_tc.milliseconds_exact + 20),
        )
        if run_seq is not None:
            self.relay.begin_run({"run_seq": run_seq})

    def announce(self, source="S", target="T", seed=1000.0, origin=OWNER, run_seq=7):
        self.relay.on_message(
            {
                "op": "announce",
                "origin": origin,
                "run_seq": run_seq,
                "source": source,
                "target": target,
                "seed_ms": seed,
            }
        )

    def cancel(self, source="S", target="T", seed=1000.0, origin=OWNER, reason="stop"):
        self.relay.on_message(
            {
                "op": "cancel",
                "origin": origin,
                "run_seq": 7,
                "source": source,
                "target": target,
                "seed_ms": seed,
                "reason": reason,
            }
        )

    def run(self, prefix):
        """Run the spawned threads whose name starts with prefix."""
        for name, fn, a in list(self.spawned):
            if name.startswith(prefix):
                fn(*a)

    def entry(self, source="S"):
        return self.relay._table.get(source)


@pytest.fixture
def basic():
    """S (video, on the owner) --Auto follow--> T (local here)."""
    t = _cue("T", local=True)
    s = _cue("S", local=False, post_go="go_at_end", target=t)
    return _Rig(_Script(s, t))


class TestAnnounce:
    def test_creates_an_entry_and_starts_prearm_and_waiter(self, basic):
        basic.announce()
        e = basic.entry()
        assert e.state == "waiting" and e.instant == 1000.0 and e.origins == {OWNER}
        assert e.arm_epoch == 3 and e.stop_epoch == 2
        names = sorted(n.split(":")[0] for n, _, _ in basic.spawned)
        assert names == ["FollowPreArm", "FollowWait"]

    def test_ignores_its_own_announcement(self, basic):
        basic.announce(origin=ME)
        assert basic.entry() is None and basic.spawned == []

    def test_ignores_a_source_local_here(self):
        t = _cue("T", local=True)
        s = _cue("S", local=True, post_go="go_at_end", target=t)
        rig = _Rig(_Script(s, t))
        rig.announce()
        assert rig.entry() is None and rig.spawned == []

    @pytest.mark.parametrize(
        "why", ["no_script", "no_mtc", "unknown_cue", "stale_run", "no_run"]
    )
    def test_refuses_with_a_warning(self, basic, why):
        kw = {}
        if why == "no_script":
            basic.script = None
        elif why == "no_mtc":
            basic.mtc = None
        elif why == "unknown_cue":
            kw["target"] = "nope"
        elif why == "stale_run":
            kw["run_seq"] = 6
        elif why == "no_run":
            basic.relay.end_run("stop")
        with patch("cuemsengine.cues.FollowRelay.Logger") as log:
            basic.announce(**kw)
        assert basic.entry() is None and basic.spawned == []
        assert log.warning.called

    def test_tolerates_a_message_that_is_not_a_dict(self, basic):
        with patch("cuemsengine.cues.FollowRelay.Logger") as log:
            basic.relay.on_message("garbage")
            basic.relay.on_message(None)
        assert log.warning.call_count == 2

    def test_same_instant_from_another_owner_joins_the_entry(self, basic):
        basic.announce()
        basic.announce(origin=OTHER, seed=1000.4)
        assert basic.entry().origins == {OWNER, OTHER}
        assert len(basic.spawned) == 2

    def test_a_new_instant_replaces_the_entry(self, basic):
        basic.announce()
        old = basic.entry()
        basic.announce(seed=5000.0)
        assert basic.entry() is not old and basic.entry().instant == 5000.0
        assert not basic.relay._is_current(old)
        assert len(basic.spawned) == 4

    def test_a_late_announcement_is_logged(self, basic):
        basic.mtc.set(1500.0)
        with patch("cuemsengine.cues.FollowRelay.Logger") as log:
            basic.announce()
        assert log.warning.called and not log.error.called
        assert basic.entry().state == "waiting"

    def test_a_very_late_announcement_is_an_error_but_still_kept(self, basic):
        basic.mtc.set(1000.0 + 10_001.0)
        with patch("cuemsengine.cues.FollowRelay.Logger") as log:
            basic.announce()
        assert log.error.called
        assert basic.entry().state == "waiting"


class TestWaiter:
    def test_dispatches_at_the_instant_with_the_stored_epochs_and_a_gate(self, basic):
        basic.announce()
        basic.mtc.set(1000.0)
        basic.run("FollowWait")
        args, kw = basic.ch.go_from.call_args
        assert args[0].id == "T" and args[1] is basic.mtc and args[2] == 1000.0
        assert kw["arm_epoch"] == 3 and kw["require_stop_epoch"] == 2
        assert callable(kw["commit_gate"])

    def test_the_gate_records_the_dispatch(self, basic):
        def go_from(target, mtc, seed, **kw):
            cue = basic.script.find("T")
            cue._armed_at = 42.0
            assert kw["commit_gate"](cue, 9) is True
            return "thread"

        basic.ch.go_from.side_effect = go_from
        basic.announce()
        basic.mtc.set(1000.0)
        basic.run("FollowWait")
        e = basic.entry()
        assert e.state == "dispatched" and e.cue.id == "T" and e.gen == 9
        assert e.disarm_epoch == 3 and e.armed_at == 42.0

    def test_waits_for_the_instant(self, basic):
        basic.announce()
        basic.mtc.set(900.0)
        basic.run("FollowWait")  # the fake sleep advances 20 ms per poll
        assert basic.mtc.main_tc.milliseconds_exact >= 1000.0
        basic.ch.go_from.assert_called_once()

    def test_a_cancel_while_waiting_ends_the_waiter(self, basic):
        basic.announce()
        basic.cancel()
        basic.mtc.set(1000.0)
        basic.run("FollowWait")
        basic.ch.go_from.assert_not_called()

    def test_a_stop_while_waiting_ends_the_waiter(self, basic):
        basic.announce()
        basic.relay.end_run("stop")
        basic.mtc.set(1000.0)
        basic.run("FollowWait")
        basic.ch.go_from.assert_not_called()

    def test_nothing_local_to_start_marks_it_done(self, basic):
        basic.announce()
        basic.mtc.set(1000.0)
        basic.run("FollowWait")
        assert basic.entry().state == "done"

    def test_an_exception_in_the_dispatch_is_logged_and_done(self, basic):
        basic.ch.go_from.side_effect = RuntimeError("re-arm failed")
        basic.announce()
        basic.mtc.set(1000.0)
        with patch("cuemsengine.cues.FollowRelay.Logger") as log:
            basic.run("FollowWait")
        assert log.error.called and basic.entry().state == "done"

    def test_yields_to_a_manual_go_during_the_postwait(self):
        t = _cue("T", local=True)
        s = _cue("S", post_go="go_at_end", target=t, postwait=0.5)
        rig = _Rig(_Script(s, t))
        rig.announce(seed=1000.0)

        def sleep(_):
            ms = rig.mtc.main_tc.milliseconds_exact + 20
            rig.mtc.set(ms)
            if ms >= 700:
                t._go_generation = 5  # the operator started T at ~700 ms

        rig.relay._sleep = sleep
        rig.mtc.set(400.0)
        rig.run("FollowWait")
        rig.ch.go_from.assert_not_called()
        assert rig.entry().state == "done"

    def test_does_not_yield_without_a_manual_go(self):
        t = _cue("T", local=True)
        s = _cue("S", post_go="go_at_end", target=t, postwait=0.5)
        rig = _Rig(_Script(s, t))
        rig.announce(seed=1000.0)
        rig.mtc.set(400.0)
        rig.run("FollowWait")
        rig.ch.go_from.assert_called_once()


class TestGate:
    def _gate(self, rig):
        captured = {}

        def go_from(target, mtc, seed, **kw):
            captured["gate"] = kw["commit_gate"]

        rig.ch.go_from.side_effect = go_from
        rig.announce()
        rig.mtc.set(1000.0)
        rig.run("FollowWait")
        rig.entry().state = "dispatching"  # as during go()
        return captured["gate"]

    def test_refuses_a_cancelled_entry(self, basic):
        gate = self._gate(basic)
        basic.cancel()
        assert gate(basic.script.find("T"), 1) is False

    def test_refuses_a_replaced_entry(self, basic):
        gate = self._gate(basic)
        basic.announce(seed=9000.0)
        assert gate(basic.script.find("T"), 1) is False

    def test_refuses_after_a_stop_emptied_the_table(self, basic):
        gate = self._gate(basic)
        basic.relay.end_run("stop")
        assert gate(basic.script.find("T"), 1) is False

    def test_refuses_after_a_new_run(self, basic):
        gate = self._gate(basic)
        basic.relay.begin_run({"run_seq": 8})
        assert gate(basic.script.find("T"), 1) is False


class TestCancel:
    def _dispatched(self, rig, gen=9):
        def go_from(target, mtc, seed, **kw):
            cue = rig.script.find("T")
            kw["commit_gate"](cue, gen)
            return "thread"

        rig.ch.go_from.side_effect = go_from
        rig.announce()
        rig.mtc.set(1000.0)
        rig.run("FollowWait")
        assert rig.entry().state == "dispatched"

    def test_without_an_entry_does_nothing(self, basic):
        basic.cancel()
        assert basic.spawned == []

    def test_for_another_instant_does_nothing(self, basic):
        basic.announce()
        basic.cancel(seed=2000.0)
        assert basic.entry().state == "waiting"

    def test_an_error_from_one_of_two_owners_only_removes_that_owner(self, basic):
        basic.announce()
        basic.announce(origin=OTHER)
        basic.cancel(origin=OTHER, reason="error")
        assert basic.entry().state == "waiting" and basic.entry().origins == {OWNER}

    def test_while_waiting_cancels_the_entry(self, basic):
        basic.announce()
        basic.cancel()
        assert basic.entry().state == "cancelled"

    def test_a_dispatched_cue_goes_to_the_guarded_stop(self, basic):
        self._dispatched(basic)
        basic.cancel(reason="restart")
        basic.run("FollowStop")
        args, kw = basic.ch.stop_dispatched_follow.call_args
        assert args[0].id == "T" and args[1:] == (9, 3, None)
        assert kw["may_cut"] is True and kw["grace_s"] == 2.0
        assert basic.entry().state == "cancelled"

    def test_an_error_cancel_may_not_cut_a_started_cue(self, basic):
        self._dispatched(basic)
        basic.cancel(reason="error")
        basic.run("FollowStop")
        assert basic.ch.stop_dispatched_follow.call_args.kwargs["may_cut"] is False

    def test_a_second_cancel_is_a_no_op(self, basic):
        self._dispatched(basic)
        basic.cancel()
        basic.cancel()
        stops = [n for n, _, _ in basic.spawned if n.startswith("FollowStop")]
        assert len(stops) == 1

    def test_arrival_order_is_applied_order(self, basic):
        """Announce then cancel, as the bus delivers them: never dispatched."""
        basic.announce()
        basic.cancel()
        basic.mtc.set(1000.0)
        basic.run("FollowWait")
        basic.ch.go_from.assert_not_called()


class TestRun:
    def test_the_same_run_keeps_its_entries(self, basic):
        basic.announce()
        basic.relay.begin_run({"run_seq": 7, "go_mtc_ms": 5.0})
        assert basic.entry() is not None

    def test_a_new_run_empties_the_table(self, basic):
        basic.announce()
        basic.relay.begin_run({"run_seq": 8})
        assert basic.entry() is None and basic.relay.run_seq == 8

    @pytest.mark.parametrize("value", [None, "complex_test", {"run_seq": True}, {}])
    def test_a_go_without_a_run_counter_means_no_relay(self, basic, value):
        basic.relay.begin_run(value)
        assert basic.relay.run_seq is None

    def test_end_run_empties_everything(self, basic):
        basic.announce()
        basic.relay.end_run("stop")
        assert basic.relay.run_seq is None and basic.relay._table == {}


class TestPreArm:
    def test_arms_the_first_local_cue_with_the_entry_epoch(self, basic):
        basic.announce()
        basic.ch.arm.side_effect = lambda c, init, walk: setattr(c, "loaded", True)
        basic.run("FollowPreArm")
        args, kw = basic.ch.arm.call_args
        assert args[0].id == "T" and kw["walk"].epoch == 3
        basic.ch._arm_ahead.assert_called_once()

    def test_runs_until_the_instant_and_rearms_what_became_unloaded(self, basic):
        basic.announce(seed=100.0)
        t = basic.script.find("T")
        t.loaded = True  # still playing an earlier pass
        basic.ch.arm.side_effect = lambda c, init, walk: setattr(c, "loaded", True)
        rounds = []

        def sleep(_):
            rounds.append(1)
            basic.mtc.set(basic.mtc.main_tc.milliseconds_exact + 50)
            if len(rounds) == 1:
                t.loaded = False  # the earlier pass ended and disarmed

        basic.relay._prearm_sleep = sleep
        basic.run("FollowPreArm")
        assert [c.args[0].id for c in basic.ch.arm.call_args_list] == ["T"]

    def test_arms_an_enabled_play_target(self):
        from uuid import uuid4

        from cuemsutils.cues import ActionCue

        x = _cue("X", local=True)
        p = ActionCue.__new__(ActionCue)
        p.id = str(uuid4())
        p.enabled = True
        p.post_go = "pause"
        p.action_type = "play"
        p._local = True
        p.loaded = True
        p._target_object = None
        p._go_generation = 0
        p._action_target_object = x
        s = _cue("S", post_go="go_at_end", target=p)
        rig = _Rig(_Script(s, p, x))
        rig.announce(target=str(p.id))
        rig.run("FollowPreArm")
        assert "X" in [c.args[0].id for c in rig.ch.arm.call_args_list]

    def test_skips_a_disabled_play_target(self):
        from uuid import uuid4

        from cuemsutils.cues import ActionCue

        x = _cue("X", local=True, enabled=False)
        p = ActionCue.__new__(ActionCue)
        p.id = str(uuid4())
        p.enabled = True
        p.post_go = "pause"
        p.action_type = "play"
        p._local = True
        p.loaded = True
        p._target_object = None
        p._go_generation = 0
        p._action_target_object = x
        s = _cue("S", post_go="go_at_end", target=p)
        rig = _Rig(_Script(s, p, x))
        rig.announce(target=str(p.id))
        rig.run("FollowPreArm")
        assert "X" not in [c.args[0].id for c in rig.ch.arm.call_args_list]

    def test_stops_when_the_entry_is_cancelled(self, basic):
        basic.announce(seed=10_000.0)
        basic.cancel(seed=10_000.0)
        basic.run("FollowPreArm")
        basic.ch.arm.assert_not_called()


class TestOwnerSend:
    def test_announce_sends_the_message(self, basic):
        t = basic.script.find("T")
        s = _cue("S2", local=True, post_go="go_at_end", target=t)
        basic.relay.announce(s, 1234.5, 7)
        assert basic.sent == [
            {
                "op": "announce",
                "origin": ME,
                "run_seq": 7,
                "source": "S2",
                "target": "T",
                "seed_ms": 1234.5,
            }
        ]

    def test_cancel_carries_its_reason(self, basic):
        t = basic.script.find("T")
        s = _cue("S2", local=True, post_go="go_at_end", target=t)
        basic.relay.cancel(s, 1234.5, 7, "stop")
        assert basic.sent[0]["op"] == "cancel" and basic.sent[0]["reason"] == "stop"

    def test_a_failed_send_is_an_error_not_an_exception(self, basic):
        basic.relay._send = MagicMock(side_effect=RuntimeError("no loop"))
        t = basic.script.find("T")
        s = _cue("S2", local=True, post_go="go_at_end", target=t)
        with patch("cuemsengine.cues.FollowRelay.Logger") as log:
            basic.relay.announce(s, 1.0, 7)
        assert log.error.called


class TestReviewFixes:
    def test_a_cancelled_entry_does_not_swallow_a_new_announcement(self, basic):
        """MINOR-5: cancel(restart, I) then announce(I) for the same instant:
        the new pass must still play here."""
        basic.announce()
        basic.cancel(reason="restart")
        basic.announce()
        assert basic.entry().state == "waiting"
        assert len([n for n, _, _ in basic.spawned if n.startswith("FollowWait")]) == 2

    def test_a_cancel_of_another_run_is_ignored(self, basic):
        """MINOR-7."""
        basic.announce()
        basic.relay.on_message(
            {
                "op": "cancel",
                "origin": OWNER,
                "run_seq": 6,
                "source": "S",
                "target": "T",
                "seed_ms": 1000.0,
                "reason": "stop",
            }
        )
        assert basic.entry().state == "waiting"

    def test_the_gate_records_a_cue_already_on_stage(self, basic):
        """MINOR-3: the follow restarts a cue still playing an earlier pass."""
        from time import monotonic

        t = basic.script.find("T")
        t._playing, t._revealed, t._revealed_at = True, True, monotonic() - 30

        def go_from(target, mtc, seed, **kw):
            kw["commit_gate"](t, 9)

        basic.ch.go_from.side_effect = go_from
        basic.announce()
        basic.mtc.set(1000.0)
        basic.run("FollowWait")
        assert basic.entry().started_before == t._revealed_at
        basic.cancel(reason="error")
        basic.run("FollowStop")
        kw = basic.ch.stop_dispatched_follow.call_args.kwargs
        assert kw["started_before"] == t._revealed_at

    def test_stop_pending_defers_the_epochs_and_the_dispatch(self, basic):
        """MINOR-4: a STOP was received but has not run yet on this node: the
        epochs are read only once it has, and nothing is dispatched before."""
        basic.relay.end_run("stop")  # received
        basic.relay.begin_run({"run_seq": 7})  # the next GO, received
        assert basic.relay.stop_pending
        basic.announce()
        e = basic.entry()
        assert e.arm_epoch is None
        basic.mtc.set(1000.0)
        polls = []

        def sleep(_):
            polls.append(1)
            if len(polls) == 3:
                basic.ch._disarm_epoch = 4  # the STOP runs ...
                basic.ch._last_stop_chain_epoch = 5
                basic.relay.stop_applied()  # ... and is applied

        basic.relay._sleep = sleep
        basic.run("FollowWait")
        kw = basic.ch.go_from.call_args.kwargs
        assert kw["arm_epoch"] == 4 and kw["require_stop_epoch"] == 5

    def test_stop_pending_blocks_the_prearm(self, basic):
        basic.relay.end_run("stop")
        basic.relay.begin_run({"run_seq": 7})
        basic.announce(seed=60.0)
        basic.run("FollowPreArm")
        basic.ch.arm.assert_not_called()


class TestRealGoAndGate:
    """MINOR-8: the real go() evaluating the real gate, both locks nested."""

    def _ch(self):
        from threading import Lock

        from cuemsengine.cues.CueHandler import CueHandler

        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        ch._armed_cues = []
        ch._armed_cues_set = set()
        ch._arm_ahead = MagicMock()
        ch.arm = MagicMock()
        return ch

    def _rig(self, ch):
        t = _cue("T", local=True, loaded=True)
        s = _cue("S", post_go="go_at_end", target=t)
        rig = _Rig(_Script(s, t))
        rig.relay._ch = ch
        return rig, t

    def test_dispatches_through_the_gate(self):
        from cuemsengine.cues.CueHandler import CueHandler

        ch = self._ch()
        rig, t = self._rig(ch)
        rig.announce()
        rig.mtc.set(1000.0)
        with patch.object(CueHandler, "go_threaded"):
            rig.run("FollowWait")
        e = rig.entry()
        assert e.state == "dispatched" and e.cue is t and e.gen == t._go_generation

    def test_a_cancel_while_inside_go_refuses_the_commit(self):
        """The cancel lands while go() is in its fallback arm: the gate, run
        later inside go()'s commit section, refuses."""
        from cuemsengine.cues.CueHandler import CueHandler

        ch = self._ch()
        rig, t = self._rig(ch)
        t.loaded = False

        def arm_and_cancel(c, init=False, epoch=None, **kw):
            rig.cancel()  # arrives on the bus during the arm
            c.loaded = True
            return True

        ch.arm.side_effect = arm_and_cancel
        rig.announce()
        rig.mtc.set(1000.0)
        with patch.object(CueHandler, "go_threaded") as gt:
            rig.run("FollowWait")
        gt.assert_not_called()
        assert rig.entry().state == "cancelled" and t._go_generation == 0
