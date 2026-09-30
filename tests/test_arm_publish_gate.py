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
    return ch._arming.get(cue.id)


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
