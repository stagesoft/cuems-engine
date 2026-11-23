# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Toggles in a running pass (1amfwm7jnqf, D26, D31 c + d, D33).

Plan: cuems-RELATIONS `Plans/2026-11-18-autocontinue-cumulative-waits.md`, rev 9.1,
AC3 ("Toggles", "Send time", "Decision", "Arming", "Order", "Loop guard",
"CueList", "Kept"), Design §2–§5. A toggle sets the flag on a node when it
reaches that node, and nothing else: no time, no layout, no pointer.

- the controller puts `sent_ms` (its MTC at the send) beside the unchanged
  `cue_enabled` string when its MTC listener is receiving, and nothing when not;
- a node applies a UI toggle in its receive hook, in bus order, with that send
  time (`chain_pass.ui_toggle`), even with no follow relay; the command thread
  no longer writes the flag, so two toggles whose command threads run in the
  reverse of their arrival leave the later one's value;
- a toggle with no send time, or one more than W from the node's MTC, counts
  from its arrival with its WARNING; so does one whose hook raised; a message
  as a 0.1.0rc6-8 controller sends it is applied;
- `retake` keeps the cue's arrival and pass; a cue in no pass (a CueList's
  child) is not retaken;
- an `enable` / `disable` ActionCue calls `chain_pass.action_toggle` before its
  "already enabled / disabled" guard;
- the loop guard refuses a second automatic entry into a cue at one instant;
- a silent thread lights nothing and ends at an operator STOP; a silent
  Auto-follow audio / video cue announces `start + postwait` at its dispatch.

The node-wide outcomes (who plays, when, on every node) are the scenarios of
`test_chain_scenarios.py`. Red until Step 2.
"""

import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

W = 500.0
CUE_ID = "8d6c1f0e-0000-4000-8000-00000000000b"


class _Tc:
    def __init__(self, ms):
        self.milliseconds_exact = float(ms)


class _Mtc:
    """MTC that moves by the duration of each sleep (the engine's waits poll
    it), and can be set by hand."""

    def __init__(self, ms=0.0):
        self.main_tc = SimpleNamespace(
            milliseconds_exact=float(ms),
            milliseconds_rounded=int(ms),
            framerate=25.0,
            frames=int(ms / 40),
        )

    def set(self, ms):
        self.main_tc.milliseconds_exact = float(ms)
        self.main_tc.milliseconds_rounded = int(ms)

    def advance(self, seconds):
        self.set(self.main_tc.milliseconds_exact + float(seconds) * 1000.0)

    def interpolated_ms(self):
        return self.main_tc.milliseconds_exact


def _plain_cue(id=CUE_ID, enabled=True, pre=0.0, post=0.0, post_go="pause"):
    return SimpleNamespace(
        id=id,
        enabled=enabled,
        _local=True,
        loaded=True,
        prewait=_Tc(pre),
        postwait=_Tc(post),
        post_go=post_go,
        _target_object=None,
        _stop_requested=False,
        _go_generation=0,
        _revealed=False,
        _playing=False,
    )


def _infos(log, level="info"):
    return [str(c.args[0]) for c in getattr(log, level).call_args_list if c.args]


# ---------------------------------------------------------------------------
# the controller: the send time beside the string (Contract rows, D31 d)
# ---------------------------------------------------------------------------


def _controller(receiving=True, mtc_ms=123_456.0):
    from cuemsengine.ControllerEngine import ControllerEngine

    ctrl = object.__new__(ControllerEngine)
    ctrl.cue_enabled_status = {CUE_ID: True}
    ctrl._broadcast_cue_enabled = MagicMock()
    ctrl._forward_command_to_nodes = MagicMock()
    ctrl.mtc_listener = MagicMock()
    ctrl.mtc_listener.is_receiving.return_value = receiving
    ctrl.mtc_listener.interpolated_ms.return_value = mtc_ms
    ctrl.mtc_listener.main_tc.milliseconds_exact = mtc_ms
    return ctrl


class TestControllerSendTime:
    def test_the_send_time_rides_beside_the_string(self):
        ctrl = _controller(receiving=True, mtc_ms=123_456.0)
        ctrl._cue_enabled_handler(f"{CUE_ID} 0")
        ctrl._forward_command_to_nodes.assert_called_once_with(
            "/engine/command/cue_enabled",
            f"{CUE_ID} 0",
            extra={"sent_ms": 123_456.0},
        )

    def test_no_send_time_when_the_listener_is_not_receiving(self):
        ctrl = _controller(receiving=False)
        ctrl._cue_enabled_handler(f"{CUE_ID} 1")
        call = ctrl._forward_command_to_nodes.call_args
        assert call.args[:2] == ("/engine/command/cue_enabled", f"{CUE_ID} 1")
        assert not (call.kwargs.get("extra") or {}).get("sent_ms")
        assert len(call.args) == 2

    def _forwarded_data(self, extra):
        from cuemsengine.ControllerEngine import ControllerEngine

        ctrl = object.__new__(ControllerEngine)
        ctrl.communications_thread = MagicMock()
        ctrl.cm = None
        with (
            patch("cuemsengine.ControllerEngine.NodeOperation") as op,
            patch("cuemsengine.ControllerEngine.asyncio.run_coroutine_threadsafe"),
        ):
            if extra is None:
                ctrl._forward_command_to_nodes(
                    "/engine/command/cue_enabled", f"{CUE_ID} 0"
                )
            else:
                ctrl._forward_command_to_nodes(
                    "/engine/command/cue_enabled", f"{CUE_ID} 0", extra=extra
                )
        return op.call_args.kwargs["data"]

    def test_the_bus_value_keeps_its_two_keys_and_gains_one(self):
        """An engine up to 0.1.0rc6-8 reads `data` by `value` and `address`: the
        string is unchanged, the send time is a third key."""
        data = self._forwarded_data({"sent_ms": 123_456.0})
        assert data == {
            "value": f"{CUE_ID} 0",
            "address": "/engine/command/cue_enabled",
            "sent_ms": 123_456.0,
        }

    def test_without_extra_the_value_is_todays(self):
        data = self._forwarded_data(None)
        assert data == {
            "value": f"{CUE_ID} 0",
            "address": "/engine/command/cue_enabled",
        }


# ---------------------------------------------------------------------------
# the node: the toggle in the receive hook, in bus order
# ---------------------------------------------------------------------------


def _node(cue, mtc_ms=10_000.0, relay=None, running=False):
    from cuemsengine.NodeEngine import NodeEngine

    node = object.__new__(NodeEngine)
    node._project_generation = 1
    node.next_cue_pointer = None
    node.script = MagicMock()
    node.script.find.side_effect = lambda i: cue if i == cue.id else None
    node.mtc_listener = _Mtc(mtc_ms)
    node.with_mtc = True
    node._follow_relay = relay
    node._ui_seq = 0
    # "a pass runs" (the WARNINGs below are said only then): a GO owns a cue.
    node.ongoing_cue = cue if running else None
    node._notify_cue_enabled = MagicMock()
    node._broadcast_nextcue = MagicMock()
    node._cancel_stop_project_watchdog = MagicMock()
    return node


class TestToggleInTheHook:
    def test_the_hook_sets_the_flag_and_records_the_send_time(self):
        from cuemsengine.cues import chain_pass

        cue = _plain_cue(enabled=True)
        node = _node(cue, mtc_ms=10_003.0)
        with patch("cuemsengine.NodeEngine.Logger") as log:
            consumed = node._on_command_received(
                "cue_enabled", f"{CUE_ID} 0", sent_ms=10_000.0
            )
        assert consumed is False  # the command thread still runs
        assert cue.enabled is False
        assert node._ui_seq == 1
        assert chain_pass.common_enabled(cue, 10_000.0 + W, 0) is True
        assert chain_pass.common_enabled(cue, 10_000.0 + W + 1, 0) is False
        log.warning.assert_not_called()

    def test_without_a_relay_the_toggle_is_still_applied(self):
        """The `relay is None` early return moves below the toggle (Design §3)."""
        cue = _plain_cue(enabled=True)
        node = _node(cue, relay=None)
        node._on_command_received("cue_enabled", f"{CUE_ID} 0", sent_ms=9_998.0)
        assert cue.enabled is False

    def test_with_a_relay_the_toggle_is_applied_and_not_consumed(self):
        cue = _plain_cue(enabled=True)
        relay = MagicMock()
        node = _node(cue, relay=relay)
        assert (
            node._on_command_received("cue_enabled", f"{CUE_ID} 0", sent_ms=9_998.0)
            is False
        )
        assert cue.enabled is False
        relay.on_message.assert_not_called()

    def test_command_threads_in_reverse_order_leave_the_later_value(self):
        """AC3: two toggles of one cue whose command threads run in the reverse
        of their arrival leave the later one's value: the hook writes the flag
        in bus order and the command thread does not write it."""
        cue = _plain_cue(enabled=True)
        node = _node(cue, mtc_ms=10_010.0)
        node._apply_cue_enabled_side_effects = MagicMock()
        node._on_command_received("cue_enabled", f"{CUE_ID} 0", sent_ms=10_000.0)
        node._on_command_received("cue_enabled", f"{CUE_ID} 1", sent_ms=10_005.0)
        assert cue.enabled is True
        node._handle_cue_enabled(f"{CUE_ID} 1")
        node._handle_cue_enabled(f"{CUE_ID} 0")  # the earlier one's thread, last
        assert cue.enabled is True
        # The side effects run for the flag as it is by then, both times.
        assert [c.args[1] for c in node._apply_cue_enabled_side_effects.mock_calls] == [
            True,
            True,
        ]
        assert node._notify_cue_enabled.call_args.args == (CUE_ID, True)

    def test_the_go_records_the_toggles_that_came_before_it(self):
        """D31 (d) addition 3: a toggle that came before a GO counts for
        everything that GO starts; the hook takes the node's toggle count."""
        cue = _plain_cue(enabled=True)
        node = _node(cue, relay=None)
        node._on_command_received("cue_enabled", f"{CUE_ID} 0", sent_ms=9_990.0)
        node._on_command_received("cue_enabled", f"{CUE_ID} 1", sent_ms=9_995.0)
        node._on_command_received("go", {"go_mtc_ms": 10_080.0, "run_seq": 1})
        assert node._go_root_seq == 2

    def test_a_message_as_an_older_controller_sends_it_is_applied(self):
        """A 0.1.0rc6-8 controller sends no `sent_ms`: applied at once, counting
        from its arrival; with no pass running, no WARNING."""
        from cuemsengine.cues import chain_pass

        cue = _plain_cue(enabled=True)
        node = _node(cue, mtc_ms=20_000.0, running=False)
        with patch("cuemsengine.NodeEngine.Logger") as log:
            node._on_command_received("cue_enabled", f"{CUE_ID} 0", sent_ms=None)
        assert cue.enabled is False
        assert chain_pass.common_enabled(cue, 19_999.0, 0) is True
        assert chain_pass.common_enabled(cue, 20_001.0, 0) is False
        assert not any("send time" in x for x in _infos(log, "warning"))

    def test_no_send_time_while_a_pass_runs_warns_once_per_load(self):
        cue = _plain_cue(enabled=True)
        node = _node(cue, mtc_ms=20_000.0, running=True)
        with patch("cuemsengine.NodeEngine.Logger") as log:
            node._on_command_received("cue_enabled", f"{CUE_ID} 0", sent_ms=None)
            node._on_command_received("cue_enabled", f"{CUE_ID} 1", sent_ms=None)
        warns = [
            x
            for x in _infos(log, "warning")
            if "cue_enabled without a send time while a pass runs: applied at once" in x
        ]
        assert len(warns) == 1
        assert cue.enabled is True

    @pytest.mark.parametrize("late", [700.0, -700.0])
    def test_a_send_time_more_than_w_away_counts_from_its_arrival(self, late):
        from cuemsengine.cues import chain_pass

        cue = _plain_cue(enabled=True)
        node = _node(cue, mtc_ms=20_000.0, running=True)
        with patch("cuemsengine.NodeEngine.Logger") as log:
            node._on_command_received(
                "cue_enabled", f"{CUE_ID} 0", sent_ms=20_000.0 - late
            )
        assert cue.enabled is False
        assert chain_pass.common_enabled(cue, 19_999.0, 0) is True
        assert chain_pass.common_enabled(cue, 20_001.0, 0) is False
        assert any(
            f"cue_enabled for {CUE_ID} arrived {late:.0f} ms after it was sent "
            "(limit 500 ms): applied at once" in x
            for x in _infos(log, "warning")
        ), _infos(log, "warning")

    def test_a_hook_that_raises_still_applies_the_toggle(self):
        """If the toggle raises in the hook, its own `except` does the same as
        an unplaced toggle: the value, a record at the arrival, the WARNING."""
        cue = _plain_cue(enabled=True)
        node = _node(cue, mtc_ms=20_000.0, running=True)
        with (
            patch(
                "cuemsengine.cues.chain_pass.ui_toggle",
                side_effect=RuntimeError("boom"),
            ),
            patch("cuemsengine.NodeEngine.Logger") as log,
        ):
            consumed = node._on_command_received(
                "cue_enabled", f"{CUE_ID} 0", sent_ms=19_998.0
            )
        assert consumed is False
        assert cue.enabled is False
        assert log.warning.called or log.error.called

    def test_a_malformed_value_changes_nothing(self):
        cue = _plain_cue(enabled=True)
        node = _node(cue)
        assert node._on_command_received("cue_enabled", "garbage", sent_ms=1.0) is False
        assert cue.enabled is True
        assert node._ui_seq == 0


# ---------------------------------------------------------------------------
# retake: no toggle re-times anything
# ---------------------------------------------------------------------------


def _handler():
    from cuemsengine.cues.CueHandler import CueHandler

    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch._disarm_epoch = 1
    ch._last_stop_chain_epoch = 0
    ch._chain_epoch = 0
    ch.communications_thread = MagicMock()
    ch.disarm = MagicMock()
    ch.arm = MagicMock()
    ch._arm_ahead = MagicMock()
    ch._follow = None
    return ch


def _pass(epoch, anchor, layout):
    from cuemsengine.cues import chain_pass

    return chain_pass.Pass(epoch=epoch, anchor_ms=anchor, layout=list(layout))


class TestRetakeKeepsThePlace:
    def test_a_retake_keeps_the_arrival_and_the_pass(self):
        """AC3: no toggle changes an arrival or a start. A retake calls go()
        again for that cue alone: same arrival, same pass, no unroll."""
        ch = _handler()
        ch.go = MagicMock(return_value="thread")
        cue = _plain_cue(enabled=True, pre=12_000.0, post=10_000.0, post_go="go")
        p = _pass(4, 100_000.0, [(cue, 100_000.0)])
        cue._pass = p
        cue._dispatch_arrival_ms = 100_000.0
        cue._go_generation = 3
        cue._follow_committed = False
        mtc = _Mtc(103_000.0)
        assert ch.retake(cue, mtc) == "thread"
        ch.go.assert_called_once()
        call = ch.go.call_args
        assert call.args[:3] == (cue, mtc, 100_000.0)
        assert call.kwargs["pass_"] is p
        assert call.kwargs["unroll"] is False
        assert call.kwargs["retake"] is True
        assert cue._pass is p
        assert cue._dispatch_arrival_ms == 100_000.0

    def test_a_cue_in_no_pass_is_not_retaken(self):
        """A CueList's child is in no layout: cancelled before its commit it
        stays silent in that pass, even if it is enabled again (S89)."""
        ch = _handler()
        ch.go = MagicMock(return_value="thread")
        child = _plain_cue(enabled=True)
        child._pass = None
        assert ch.retake(child, _Mtc(1000.0)) is None
        ch.go.assert_not_called()


class TestCueListToggle:
    def test_the_marked_child_disabled_before_its_commit_is_cancelled(self):
        cue = _plain_cue(enabled=False)
        node = _node(cue)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.cancel_child.return_value = True
            ch.retake.return_value = None
            ch.find_armed_cue.return_value = cue
            node._apply_cue_enabled_side_effects(cue, False)
        ch.cancel_child.assert_called_with(cue)
        ch.disarm.assert_not_called()

    def test_a_cuelist_a_pass_holds_is_neither_retaken_nor_disarmed(self):
        """A cue more than one node runs decides at its own instants (Design
        §3): its setup reads the flag as every node sees it."""
        from cuemsutils.cues import CueList

        cl = CueList.__new__(CueList)
        cl.id = CUE_ID
        cl.enabled = False
        cl._local = True
        cl._playing = True
        cl.contents = []
        cl._pass = object()
        node = _node(cl)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = cl
            node._apply_cue_enabled_side_effects(cl, False)
        ch.retake.assert_not_called()
        ch.disarm.assert_not_called()


# ---------------------------------------------------------------------------
# enable / disable ActionCues: the record comes first (D31 d, S72)
# ---------------------------------------------------------------------------


class TestActionToggle:
    @pytest.mark.parametrize(
        "handler, value, before",
        [
            ("_handle_enable", True, True),
            ("_handle_enable", True, False),
            ("_handle_disable", False, False),
            ("_handle_disable", False, True),
        ],
    )
    def test_action_toggle_runs_before_the_already_guard(self, handler, value, before):
        from cuemsengine.cues import ActionHandler as AH

        target = _plain_cue(enabled=before)
        target._pass = None
        action_cue = _plain_cue(id="action")
        with patch("cuemsengine.cues.ActionHandler.chain_pass") as cp:
            cp.action_toggle.side_effect = (
                lambda t, v, *a, **k: setattr(t, "enabled", v) or v
            )
            getattr(AH, handler)(MagicMock(), action_cue, target, _Mtc(5000.0), None)
        cp.action_toggle.assert_called_once()
        assert cp.action_toggle.call_args.args[:2] == (target, value)


# ---------------------------------------------------------------------------
# loop guard (S62, S96)
# ---------------------------------------------------------------------------


class TestLoopGuard:
    def _ch(self):
        ch = _handler()
        ch.go = MagicMock(side_effect=lambda *a, **k: object())
        return ch

    @pytest.mark.parametrize("why", ["play", "fade_in", "follow"])
    def test_a_second_automatic_entry_at_one_instant_is_refused(self, why):
        ch = self._ch()
        cue = _plain_cue(id="cue-A")
        mtc = _Mtc(5000.0)
        assert ch.go_from(cue, mtc, 5000.0, why=why) is not None
        with patch("cuemsengine.cues.CueHandler.Logger") as log:
            assert ch.go_from(cue, mtc, 5000.0, why=why) is None
        assert ch.go.call_count == 1
        assert any(
            f"zero-length loop: {why} into cue-A at" in x for x in _infos(log, "error")
        ), _infos(log, "error")

    def test_another_instant_is_not_refused(self):
        ch = self._ch()
        cue = _plain_cue(id="cue-A")
        mtc = _Mtc(5000.0)
        assert ch.go_from(cue, mtc, 5000.0, why="play") is not None
        assert ch.go_from(cue, mtc, 22_000.0, why="play") is not None
        assert ch.go.call_count == 2

    def test_an_operator_go_is_never_refused(self):
        ch = self._ch()
        cue = _plain_cue(id="cue-A")
        mtc = _Mtc(5000.0)
        assert ch.go_from(cue, mtc, 5000.0, why="go") is not None
        assert ch.go_from(cue, mtc, 5000.0, why="go") is not None
        assert ch.go.call_count == 2


# ---------------------------------------------------------------------------
# silent threads (Design §2)
# ---------------------------------------------------------------------------


def _video(enabled=False, pre_s=5, post_s=3, post_go="go_at_end", target=None):
    """A real VideoCue (isinstance decides who announces), built without its
    constructor so no player is involved."""
    from cuemsutils.cues import VideoCue

    cue = VideoCue.__new__(VideoCue)
    cue.id = "8d6c1f0e-0000-4000-8000-00000000000a"
    cue._local = True
    cue.enabled = enabled
    cue.loaded = False
    cue.post_go = post_go
    cue.prewait = CTimecode(start_seconds=pre_s)
    cue.postwait = CTimecode(start_seconds=post_s)
    cue._target_object = target
    cue._stop_requested = False
    cue._go_generation = 1
    cue._revealed = False
    cue._start_mtc = None
    cue._end_mtc = None
    cue._dispatch_arrival_ms = None
    return cue


class TestSilentThread:
    def test_it_lights_nothing_and_ends_at_an_operator_stop(self):
        ch = _handler()
        ch.go = MagicMock(return_value=None)
        ch._next_local_fire = MagicMock(return_value=(None, 0.0))
        cue = _video(enabled=False, post_go="pause")
        p = _pass(1, 0.0, [(cue, 0.0)])
        cue._pass = p
        mtc = _Mtc(0.0)

        def sleep(s):
            mtc.advance(s)
            if mtc.main_tc.milliseconds_exact >= 2000.0:
                cue._stop_requested = True  # the operator's STOP at +2 s

        with (
            patch("cuemsengine.cues.CueHandler.run_cue") as run_cue,
            patch("cuemsengine.cues.CueHandler.reveal_cue") as reveal_cue,
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=sleep),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=0.0, go_gen=1, pass_=p)
        run_cue.assert_not_called()
        reveal_cue.assert_not_called()
        ch.arm.assert_not_called()
        ch.communications_thread.add_cue.assert_not_called()
        assert mtc.main_tc.milliseconds_exact < 5000.0, "it ended at the STOP"
        assert not any("passed silent" in x for x in _infos(log))

    def test_a_silent_auto_follow_cue_announces_at_its_dispatch(self):
        """S64 (D31 i): X (video, Auto follow, 5/3, disabled) hands over at
        start + postwait = +8 s and says so at its dispatch, not after a
        reveal it never has."""
        ch = _handler()
        ch.go = MagicMock(return_value=None)
        ch._next_local_fire = MagicMock(return_value=(None, 0.0))
        nxt = _plain_cue(id="audio-T")
        cue = _video(enabled=False, target=nxt)
        p = _pass(1, 0.0, [(cue, 0.0)])
        cue._pass = p
        relay = MagicMock()
        relay.stop_pending = False
        relay.run_seq = 7
        ch._follow = relay
        mtc = _Mtc(0.0)
        announced_at = []
        relay.announce.side_effect = lambda *a, **k: announced_at.append(
            mtc.main_tc.milliseconds_exact
        )
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(cue, mtc, frozen_mtc_ms=0.0, go_gen=1, pass_=p)
        relay.announce.assert_called_once()
        instant = relay.announce.call_args.args[1]
        assert instant == pytest.approx(8000.0, abs=2.0)
        assert announced_at[0] < 5000.0 - 120.0, "at its dispatch, before F"
