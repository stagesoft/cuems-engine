# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Cross-node Auto follow, owning side and CueHandler hooks (ClickUp 869fc8ytz).

The node where an AudioCue or VideoCue with Auto follow is local announces the
follow instant when the cue starts (or at the start of its last loop), so the
other nodes can start their part of the target on time. The instant comes
from the same helper the cue's own fire uses. Leaving without firing sends a
cancel, except when every node already knows (a STOP, a load, the yield) or
when go() already sent it (the cue was started again). Only the current pass
announces, and the outstanding record is compare-and-cleared, so exactly one
cancel can follow one announcement.

Also here: go()'s commit gate, the restart cancel's place in the commit
section, go_from passing the dispatch guards through, the guarded stop of a
follow target and its guarded disarm.

Design: cuems-RELATIONS Plans/2026-10-05-engine-cross-node-auto-follow.md
§3.2, §3.5.
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import DmxCue, VideoCue  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


class _FakeMtc:
    def __init__(self, ms=0.0):
        self.main_tc = SimpleNamespace(
            milliseconds_exact=float(ms),
            milliseconds_rounded=int(ms),
            framerate=25.0,
            frames=0,
        )

    def advance(self, seconds):
        self.main_tc.milliseconds_exact += float(seconds) * 1000.0
        self.main_tc.milliseconds_rounded = int(self.main_tc.milliseconds_exact)


def _tc(ms):
    return CTimecode(start_seconds=ms / 1000.0)


def _video(post_go="go_at_end", target="default", loop=1, postwait=0, cls=VideoCue):
    cue = cls.__new__(cls)
    cue.id = str(uuid4())
    cue.enabled = True
    cue.post_go = post_go
    cue.prewait = CTimecode(start_seconds=0)
    cue.postwait = CTimecode(start_seconds=postwait)
    cue.loop = loop
    cue._local = True
    cue.loaded = True
    cue._stop_requested = False
    cue._go_generation = 1
    cue._revealed = False
    cue._start_mtc = None
    cue._end_mtc = None
    if target == "default":
        target = SimpleNamespace(id=str(uuid4()), _go_generation=0)
    cue._target_object = target
    return cue


def _relay(run_seq=7):
    relay = MagicMock()
    relay.run_seq = run_seq
    relay.stop_pending = False
    return relay


def _ch(relay=None):
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    ch.disarm = MagicMock()
    ch.arm = MagicMock()
    ch._arm_ahead = MagicMock()
    ch.go = MagicMock(return_value=None)
    ch.go_from = MagicMock(return_value=None)
    ch._next_local_fire = MagicMock(return_value=(None, 0.0))
    ch._follow = relay
    return ch


def _run(
    ch,
    cue,
    mtc,
    body_ms=2000,
    loop_effect=None,
    order=None,
    reveal_effect=None,
    blank_effect=None,
    **kw,
):
    """Drive go_threaded with the players patched out. run_cue sets the
    cue's start and end as the real one does (start = arrival + prewait)."""
    calls = order if order is not None else []

    def run_cue(c, m, start_ms):
        calls.append("run_cue")
        c._start_mtc = _tc(start_ms)
        c._end_mtc = _tc(start_ms + body_ms)

    def loop_cue(c, m, on_last_loop=None):
        calls.append("loop")
        if loop_effect:
            loop_effect(c, m, on_last_loop)
        m.main_tc.milliseconds_exact = c._end_mtc.milliseconds_exact

    kw.setdefault("go_gen", cue._go_generation)
    kw.setdefault("arm_epoch", ch._disarm_epoch)
    ch._arm_ahead.side_effect = lambda *a, **k: calls.append("arm_ahead")
    ch._follow and setattr(
        ch._follow.announce, "side_effect", lambda *a: calls.append("announce")
    )
    with (
        patch("cuemsengine.cues.CueHandler.run_cue", side_effect=run_cue),
        patch(
            "cuemsengine.cues.CueHandler.reveal_cue",
            side_effect=lambda *a: (
                calls.append("reveal"),
                reveal_effect and reveal_effect(),
            ),
        ),
        patch("cuemsengine.cues.CueHandler.loop_cue", side_effect=loop_cue),
        patch(
            "cuemsengine.cues.CueHandler.blank_cue",
            side_effect=lambda *a: blank_effect and blank_effect(),
        ),
        patch(
            "cuemsengine.cues.CueHandler.sleep", side_effect=lambda s: mtc.advance(s)
        ),
    ):
        ch.go_threaded(cue, mtc, 1000.0, **kw)
    return calls


# ── announce ──────────────────────────────────────────────────────────────


class TestAnnounce:
    def test_announces_the_fire_instant_after_the_reveal_before_the_arm_ahead(self):
        relay = _relay()
        ch, cue = _ch(relay), _video(postwait=0.5)
        order = _run(ch, cue, _FakeMtc(1000), body_ms=2000)
        relay.announce.assert_called_once_with(cue, 3500.0, 7)
        assert order.index("reveal") < order.index("announce")
        assert order.index("announce") < order.index("arm_ahead")

    def test_the_cue_fires_at_the_announced_instant(self):
        relay = _relay()
        ch, cue = _ch(relay), _video(postwait=0.5)
        _run(ch, cue, _FakeMtc(1000), body_ms=2000)
        args = ch.go_from.call_args.args
        assert args[0] is cue._target_object and args[2] == 3500.0
        relay.cancel.assert_not_called()
        assert getattr(cue, "_follow_out", None) is None

    @pytest.mark.parametrize(
        "why", ["pause", "no_target", "infinite_loop", "dmx", "no_relay", "no_run"]
    )
    def test_does_not_announce(self, why):
        relay = _relay(run_seq=None if why == "no_run" else 7)
        kw = {}
        if why == "pause":
            kw["post_go"] = "pause"
        elif why == "no_target":
            kw["target"] = None
        elif why == "infinite_loop":
            kw["loop"] = 0
        elif why == "dmx":
            kw["cls"] = DmxCue
        ch = _ch(None if why == "no_relay" else relay)
        cue = _video(**kw)
        _run(ch, cue, _FakeMtc(1000))
        relay.announce.assert_not_called()

    def test_a_cue_that_never_reveals_does_not_announce(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()

        with patch.object(ch, "_reveal_wait", return_value="stopped"):
            _run(ch, cue, _FakeMtc(1000), order=[])
        relay.announce.assert_not_called()

    def test_a_replaced_pass_does_not_announce(self):
        """A newer go() took the cue between the reveal and the announce."""
        relay = _relay()
        ch, cue = _ch(relay), _video()
        _run(
            ch,
            cue,
            _FakeMtc(1000),
            reveal_effect=lambda: setattr(cue, "_go_generation", 2),
        )
        relay.announce.assert_not_called()

    def test_a_looping_cue_announces_once_at_its_last_loop(self):
        relay = _relay()
        ch, cue = _ch(relay), _video(loop=3)

        def loops(c, m, on_last_loop):
            assert on_last_loop is not None
            relay.announce.assert_not_called()  # not at the reveal
            c._end_mtc = _tc(7000)  # the last loop's end, rebased
            on_last_loop()

        _run(ch, cue, _FakeMtc(1000), body_ms=2000, loop_effect=loops)
        relay.announce.assert_called_once_with(cue, 7000.0, 7)

    def test_a_looping_cue_without_follow_gets_no_callback(self):
        ch, cue = _ch(_relay()), _video(loop=3, post_go="pause")
        seen = []
        _run(ch, cue, _FakeMtc(1000), loop_effect=lambda c, m, cb: seen.append(cb))
        assert seen == [None]

    def test_an_instant_that_moved_is_an_error(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()

        def stretch(c, m, cb):
            c._end_mtc = _tc(c._end_mtc.milliseconds_exact + 500)

        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            _run(ch, cue, _FakeMtc(1000), loop_effect=stretch)
        assert any("announced" in str(c) for c in log.error.call_args_list)


# ── leaving without firing ────────────────────────────────────────────────


class TestLeave:
    def test_a_stop_action_cancels_with_reason_stop(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()

        def stop_action(c, m, cb):
            c._stop_requested = True
            c._go_generation += 1

        _run(ch, cue, _FakeMtc(1000), body_ms=2000, loop_effect=stop_action)
        relay.cancel.assert_called_once_with(cue, 3000.0, 7, "stop")
        ch.go_from.assert_not_called()

    def test_a_pause_cancels_with_reason_stop(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()
        _run(
            ch,
            cue,
            _FakeMtc(1000),
            loop_effect=lambda c, m, cb: setattr(c, "_stop_requested", True),
        )
        relay.cancel.assert_called_once_with(cue, 3000.0, 7, "stop")

    def test_a_stop_or_load_sends_nothing(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()

        def stop(c, m, cb):
            ch._disarm_epoch += 1
            c._stop_requested = True
            c._go_generation += 1

        _run(ch, cue, _FakeMtc(1000), loop_effect=stop)
        relay.cancel.assert_not_called()
        assert getattr(cue, "_follow_out", None) is None

    def test_a_restart_lets_go_send_the_cancel(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()

        def restart(c, m, cb):
            with ch._lock:
                ch._take_follow_on_restart_locked(c)  # what go() does
            c._go_generation += 1

        _run(ch, cue, _FakeMtc(1000), loop_effect=restart)
        relay.cancel.assert_called_once_with(cue, 3000.0, 7, "restart")

    def test_an_exception_cancels_with_reason_error_and_still_raises(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()

        def boom(c, m, cb):
            raise RuntimeError("player died")

        with pytest.raises(RuntimeError):
            _run(ch, cue, _FakeMtc(1000), loop_effect=boom)
        relay.cancel.assert_called_once_with(cue, 3000.0, 7, "error")

    def test_the_yield_sends_nothing(self):
        relay = _relay()
        ch, cue = _ch(relay), _video(postwait=0.5)

        def manual_go_of_target():  # during the postwait tail
            cue._target_object._go_generation += 1

        _run(ch, cue, _FakeMtc(1000), blank_effect=manual_go_of_target)
        ch.go_from.assert_not_called()
        relay.cancel.assert_not_called()

    def test_an_error_in_the_own_fire_does_not_cancel(self):
        relay = _relay()
        ch, cue = _ch(relay), _video()
        ch.go_from.side_effect = RuntimeError("fire failed")
        with pytest.raises(RuntimeError):
            _run(ch, cue, _FakeMtc(1000))
        relay.cancel.assert_not_called()


# ── go(): commit gate and restart cancel ─────────────────────────────────


def _plain(id="c", **kw):
    c = SimpleNamespace(id=id, loaded=True, enabled=True, _local=True)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class TestGoCommit:
    def _go(self, ch, cue, **kw):
        with patch.object(CueHandler, "go_threaded"):
            return ch.go(cue, _FakeMtc(), 0.0, **kw)

    def test_restart_sends_a_cancel_for_the_outstanding_announcement(self):
        relay = _relay()
        ch = _ch(relay)
        del ch.go
        cue = _plain(_follow_out=(5000.0, 7), _target_object=None)
        assert self._go(ch, cue) is not None
        relay.cancel.assert_called_once_with(cue, 5000.0, 7, "restart")
        assert cue._follow_out is None

    def test_an_outstanding_announcement_of_an_old_run_is_dropped_silently(self):
        relay = _relay()
        ch = _ch(relay)
        del ch.go
        cue = _plain(_follow_out=(5000.0, 6))
        self._go(ch, cue)
        relay.cancel.assert_not_called()
        assert cue._follow_out is None

    def test_a_refused_dispatch_sends_nothing_and_keeps_the_record(self):
        relay = _relay()
        ch = _ch(relay)
        del ch.go
        ch._last_stop_chain_epoch = 1
        cue = _plain(_follow_out=(5000.0, 7))
        assert self._go(ch, cue, require_stop_epoch=0) is None
        relay.cancel.assert_not_called()
        assert cue._follow_out == (5000.0, 7)

    def test_the_gate_sees_the_generation_about_to_be_assigned(self):
        ch = _ch()
        del ch.go
        cue = _plain(_go_generation=4)
        gate = MagicMock(return_value=True)
        self._go(ch, cue, commit_gate=gate)
        gate.assert_called_once_with(cue, 5)
        assert cue._go_generation == 5

    def test_a_refusing_gate_commits_nothing(self):
        relay = _relay()
        ch = _ch(relay)
        del ch.go
        cue = _plain(_go_generation=4, _follow_out=(5000.0, 7), _playing=False)
        assert self._go(ch, cue, commit_gate=MagicMock(return_value=False)) is None
        assert cue._go_generation == 4 and cue._playing is False
        relay.cancel.assert_not_called()

    def test_a_gate_that_raises_refuses(self):
        ch = _ch()
        del ch.go
        cue = _plain(_go_generation=4)
        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            out = self._go(ch, cue, commit_gate=MagicMock(side_effect=ValueError()))
        assert out is None and log.error.called

    def test_go_clears_the_start_stamp(self):
        ch = _ch()
        del ch.go
        cue = _plain(_revealed_at=123.0)
        self._go(ch, cue)
        assert cue._revealed_at is None


class TestGoFrom:
    def test_passes_the_guards_only_when_set(self):
        ch = _ch()
        del ch.go_from
        cue = _plain(post_go="pause")
        ch.go_from(cue, _FakeMtc(), 10.0)
        ch.go.assert_called_once_with(cue, ch.go.call_args.args[1], 10.0)

    def test_passes_the_guards_through(self):
        ch = _ch()
        del ch.go_from
        cue = _plain(post_go="pause")
        gate = MagicMock()
        ch.go_from(
            cue, _FakeMtc(), 10.0, arm_epoch=3, require_stop_epoch=2, commit_gate=gate
        )
        assert ch.go.call_args.kwargs == {
            "arm_epoch": 3,
            "require_stop_epoch": 2,
            "commit_gate": gate,
        }


# ── the guarded stop and disarm of a follow target ───────────────────────


class TestStopDispatchedFollow:
    def _target(self, revealed_ago=None, gen=9):
        from time import monotonic

        cue = _plain(
            _go_generation=gen,
            _stop_requested=False,
            _playing=True,
            _revealed_at=None if revealed_ago is None else monotonic() - revealed_ago,
            _armed_at=42.0,
        )
        return cue

    def _ch(self):
        ch = _ch()
        ch._disarm_epoch = 3
        ch.cancel_pending_descendants = MagicMock()
        ch._end_illumination = MagicMock()
        ch.disarm_if_unchanged = MagicMock(return_value=True)
        return ch

    def _stop(self, ch, cue, may_cut=True):
        with patch("cuemsengine.cues.CueHandler.sleep"):
            return ch.stop_dispatched_follow(
                cue, 9, 3, 42.0, may_cut=may_cut, grace_s=2.0
            )

    def test_a_newer_go_owns_it(self):
        ch, cue = self._ch(), self._target(gen=10)
        assert self._stop(ch, cue)[0] == "owned"
        assert cue._stop_requested is False

    def test_a_stop_owns_it(self):
        ch, cue = self._ch(), self._target()
        ch._disarm_epoch = 4
        assert self._stop(ch, cue)[0] == "owned"

    def test_not_started_is_stopped(self):
        ch, cue = self._ch(), self._target()
        assert self._stop(ch, cue)[0] == "stopped"
        assert cue._stop_requested and cue._go_generation == 10 and not cue._playing
        ch.cancel_pending_descendants.assert_called_once_with(cue)
        ch.disarm_if_unchanged.assert_called_once_with(
            cue, 10, 3, 42.0, reason="follow_cancelled"
        )

    def test_started_inside_the_grace_is_stopped_when_it_may_cut(self):
        ch, cue = self._ch(), self._target(revealed_ago=0.5)
        outcome, age = self._stop(ch, cue)
        assert outcome == "stopped" and 0.4 < age < 1.0

    def test_started_inside_the_grace_is_left_for_an_error(self):
        ch, cue = self._ch(), self._target(revealed_ago=0.5)
        assert self._stop(ch, cue, may_cut=False)[0] == "left"
        assert cue._stop_requested is False

    def test_started_after_the_grace_is_left(self):
        ch, cue = self._ch(), self._target(revealed_ago=3.0)
        assert self._stop(ch, cue)[0] == "left"
        ch.disarm_if_unchanged.assert_not_called()


class TestDisarmIfUnchanged:
    def _setup(self):
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        ch._disarm_epoch = 3
        ch.communications_thread = MagicMock()
        cue = _plain(_go_generation=10, _armed_at=42.0, _playing=False)
        ch._armed_cues = [cue]
        ch._armed_cues_set = {cue.id}
        return ch, cue

    def test_unpublishes_and_releases(self):
        ch, cue = self._setup()
        seen = []

        def release(c, reason, what="Disarmed"):
            seen.append(ch._arming_registry().get(c.id) is not None)

        with patch.object(ch, "_release_cue_resources", side_effect=release):
            assert ch.disarm_if_unchanged(cue, 10, 3, 42.0, reason="x") is True
        assert cue.loaded is False and ch._armed_cues == []
        assert seen == [True]  # released while holding the cue's claim
        assert ch._arming_registry() == {}

    @pytest.mark.parametrize("change", ["gen", "epoch", "rearmed", "unloaded"])
    def test_refuses_when_anything_moved(self, change):
        ch, cue = self._setup()
        if change == "gen":
            cue._go_generation = 11
        elif change == "epoch":
            ch._disarm_epoch = 4
        elif change == "rearmed":
            cue._armed_at = 43.0
        else:
            cue.loaded = False
        with patch.object(ch, "_release_cue_resources") as rel:
            assert ch.disarm_if_unchanged(cue, 10, 3, 42.0, reason="x") is False
        rel.assert_not_called()

    def test_refuses_while_an_arm_is_in_flight(self):
        ch, cue = self._setup()
        ch._arming_registry()[cue.id] = object()
        with patch.object(ch, "_release_cue_resources") as rel:
            assert ch.disarm_if_unchanged(cue, 10, 3, 42.0, reason="x") is False
        rel.assert_not_called()

    def test_the_claim_is_released_even_if_the_release_fails(self):
        ch, cue = self._setup()
        with patch.object(ch, "_release_cue_resources", side_effect=RuntimeError()):
            with pytest.raises(RuntimeError):
                ch.disarm_if_unchanged(cue, 10, 3, 42.0, reason="x")
        assert ch._arming_registry() == {}


# ── code review of the implementation (2026-10-06) ───────────────────────


class TestReviewFixes:
    def test_the_start_stamp_is_set_with_the_reveal_decision(self):
        """MINOR-1: a cancel taking the lock right after the reveal decision
        must already see the cue as started."""
        relay = _relay()
        ch, cue = _ch(relay), _video()
        seen = []
        _run(
            ch,
            cue,
            _FakeMtc(1000),
            reveal_effect=lambda: seen.append(getattr(cue, "_revealed_at", None)),
        )
        assert seen and seen[0] is not None

    def test_a_restart_just_before_the_fire_skips_the_fire(self):
        """MINOR-2: go() took the announcement (restart) between the tail and
        the fire; the replaced pass must not fire its follow."""
        relay = _relay()
        ch, cue = _ch(relay), _video()

        def restart(*a, **k):
            with ch._lock:
                ch._take_follow_on_restart_locked(cue)
                cue._go_generation += 1

        ch.communications_thread.remove_cue.side_effect = restart
        _run(ch, cue, _FakeMtc(1000))
        ch.go_from.assert_not_called()
        relay.cancel.assert_called_once_with(cue, 3000.0, 7, "restart")

    def test_without_an_announcement_the_fire_is_unchanged(self):
        """The generation re-check only applies to an announced follow; a
        same-node or unannounced follow fires as before."""
        ch, cue = _ch(None), _video()

        def bump(*a, **k):
            cue._go_generation += 1

        ch.communications_thread.remove_cue.side_effect = bump
        _run(ch, cue, _FakeMtc(1000))
        ch.go_from.assert_called_once()

    def test_no_announcement_while_a_stop_is_pending(self):
        """MINOR-4: a STOP was received but not applied yet; this pass is
        about to be stopped and must not announce into the next run."""
        relay = _relay()
        relay.stop_pending = True
        ch, cue = _ch(relay), _video()
        _run(ch, cue, _FakeMtc(1000))
        relay.announce.assert_not_called()


class TestStopDispatchedFollowReview:
    def _ch(self):
        ch = _ch()
        ch._disarm_epoch = 3
        ch.cancel_pending_descendants = MagicMock()
        ch._end_illumination = MagicMock()
        ch.disarm_if_unchanged = MagicMock(return_value=True)
        return ch

    def test_revealed_without_a_stamp_counts_as_started(self):
        ch = self._ch()
        cue = _plain(_go_generation=9, _revealed=True, _revealed_at=None)
        with patch("cuemsengine.cues.CueHandler.sleep"):
            out = ch.stop_dispatched_follow(cue, 9, 3, 42.0, may_cut=False, grace_s=2.0)
        assert out[0] == "left"

    def test_a_cue_already_on_stage_before_the_follow_counts_as_started(self):
        """MINOR-3: the follow restarted a cue that was playing; its new pass
        has not revealed yet, but its output has been on stage for minutes."""
        from time import monotonic

        ch = self._ch()
        cue = _plain(_go_generation=9, _revealed=False, _revealed_at=None)
        with patch("cuemsengine.cues.CueHandler.sleep"):
            out = ch.stop_dispatched_follow(
                cue,
                9,
                3,
                42.0,
                may_cut=True,
                grace_s=2.0,
                started_before=monotonic() - 120.0,
            )
        assert out[0] == "left" and out[1] > 100
        ch.disarm_if_unchanged.assert_not_called()
