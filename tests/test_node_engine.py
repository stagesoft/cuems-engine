# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Tests for NodeEngine.start() late-bind protocol (T023a)."""

import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", MagicMock())


def test_node_engine_start_late_binds_deploy_manager_loop():
    """
    T023a: NodeEngine.start() must bind
    CUE_HANDLER.communications_thread.event_loop
    to self.deploy_manager.loop after set_nng_comms() starts the comms thread.
    """
    sentinel_loop = object()

    from cuemsengine.NodeEngine import NodeEngine

    node = object.__new__(NodeEngine)
    node.nng_hub_address = "tcp://10.0.0.1:9999"
    node.deploy_manager = MagicMock()
    node.deploy_manager.loop = None
    node.mtc_listener = MagicMock()
    node.stop_requested = False
    node.cm = MagicMock()
    node.cm.node_uuid = "test-node-uuid"

    with (
        patch("cuemsengine.NodeEngine.CUE_HANDLER") as mock_cue_handler,
        patch.object(node, "set_oscquery_comms"),
        patch.object(node, "set_players"),
        patch.object(node, "_setup_nng_command_callback"),
        patch("cuemsengine.core.BaseEngine.BaseEngine.start"),
    ):

        mock_cue_handler.communications_thread.event_loop = sentinel_loop
        node.start()

    assert node.deploy_manager.loop is sentinel_loop, (
        "NodeEngine.start() must late-bind"
        "CUE_HANDLER.communications_thread.event_loop "
        "to deploy_manager.loop"
    )


# ---------------------------------------------------------------------------
# arm-on-enable / disarm-on-disable side effects (ClickUp 869e25wzb)
#
# NodeEngine keeps no handle on the ReArm:<id> daemon thread it spawns, so
# these tests synchronize by polling the patched CUE_HANDLER mock (and, where
# useful, joining the thread found via threading.enumerate()).
# ---------------------------------------------------------------------------

import threading
import time
from unittest.mock import MagicMock as _MM


class _FakeCue:
    """Minimal cue double for the enabled side-effects paths."""

    def __init__(
        self, cue_id="cue-1", enabled=True, local=True, playing=False, next_cue=None
    ):
        self.id = cue_id
        self.enabled = enabled
        self._local = local
        self._playing = playing
        self._next = next_cue

    def get_next_cue(self):
        return self._next


def _make_node(script_cue="unset", next_cue_pointer=None):
    from cuemsengine.NodeEngine import NodeEngine

    node = object.__new__(NodeEngine)
    node._project_generation = 1
    node.next_cue_pointer = next_cue_pointer
    if script_cue is None:
        node.script = None
    else:
        node.script = MagicMock()
        node.script.find.return_value = None if script_cue == "unset" else script_cue
    node._notify_cue_enabled = _MM()
    node._broadcast_nextcue = _MM()
    return node


def _wait_until(cond, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _join_rearm(cue_id, timeout=2.0):
    for t in threading.enumerate():
        if t.name == f"ReArm:{cue_id}":
            t.join(timeout)


def _join_prearm(cue_id, timeout=2.0):
    for t in threading.enumerate():
        if t.name == f"PreArm:{cue_id}":
            t.join(timeout)


class TestApplyCueEnabledSideEffects:

    def test_enable_local_unarmed_arms_async(self):
        cue = _FakeCue()
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            node._apply_cue_enabled_side_effects(cue, True)
            assert _wait_until(lambda: ch.arm.called), "async ReArm never armed the cue"
            _join_rearm(cue.id)
            ch.arm.assert_called_once_with(cue, init=True)

    def test_enable_non_local_does_not_arm(self):
        cue = _FakeCue(local=False)
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            node._apply_cue_enabled_side_effects(cue, True)
            _join_rearm(cue.id)
            ch.arm.assert_not_called()

    def test_enable_already_armed_does_not_rearm(self):
        cue = _FakeCue()
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = True
            node._apply_cue_enabled_side_effects(cue, True)
            _join_rearm(cue.id)
            ch.arm.assert_not_called()

    def test_disable_idle_armed_disarms(self):
        cue = _FakeCue(playing=False)
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = True
            node._apply_cue_enabled_side_effects(cue, False)
            ch.disarm.assert_called_once_with(cue)

    def test_disable_playing_does_not_disarm(self):
        cue = _FakeCue(playing=True)
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = True
            node._apply_cue_enabled_side_effects(cue, False)
            ch.disarm.assert_not_called()

    def test_toggle_after_playback_finished_disarms(self):
        # Regression for the _go_generation false-positive: a cue that played
        # once and was re-armed while idle has _playing=False (cleared by
        # disarm()/stop_all_cues()) and MUST be disarmable on disable.
        cue = _FakeCue(playing=False)
        cue._go_generation = (
            3  # played before — the old heuristic read this as "playing"
        )
        cue.loaded = True
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = True
            node._apply_cue_enabled_side_effects(cue, False)
            ch.disarm.assert_called_once_with(cue)

    def test_disable_next_cue_advances_pointer_and_broadcasts(self):
        follow = _FakeCue(cue_id="cue-2")
        cue = _FakeCue(next_cue=follow)
        node = _make_node(next_cue_pointer=cue)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            node._apply_cue_enabled_side_effects(cue, False)
        assert node.next_cue_pointer is follow
        node._broadcast_nextcue.assert_called_once()

    def test_cuelist_target_reacts_on_first_enabled_child(self):
        from cuemsutils.cues import CueList

        child_disabled = _FakeCue(cue_id="child-0", enabled=False)
        child_enabled = _FakeCue(cue_id="child-1", enabled=True)
        cl = CueList.__new__(CueList)
        cl.contents = [child_disabled, child_enabled]
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            node._apply_cue_enabled_side_effects(cl, True)
            assert _wait_until(lambda: ch.arm.called), "CueList child never armed"
            _join_rearm(child_enabled.id)
            ch.arm.assert_called_once_with(child_enabled, init=True)


class TestArmWithEnabledGuard:

    def test_disabled_during_arm_disarms(self):
        cue = _FakeCue()
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:

            def slow_arm(c, init=False):
                c.enabled = False  # disable lands while media is loading

            ch.arm.side_effect = slow_arm
            ch.find_armed_cue.return_value = True
            node._arm_with_enabled_guard(cue, project_gen=1)
            ch.disarm.assert_called_once_with(cue)

    def test_generation_change_mid_arm_disarms(self):
        cue = _FakeCue()
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:

            def gen_bump_arm(c, init=False):
                node._project_generation = 2  # STOP/reload during the arm

            ch.arm.side_effect = gen_bump_arm
            ch.find_armed_cue.return_value = True
            node._arm_with_enabled_guard(cue, project_gen=1)
            ch.disarm.assert_called_once_with(cue)

    def test_generation_change_before_arm_aborts(self):
        cue = _FakeCue()
        node = _make_node()
        node._project_generation = 2
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            node._arm_with_enabled_guard(cue, project_gen=1)
            ch.arm.assert_not_called()

    def test_arm_raises_is_logged_not_propagated(self):
        cue = _FakeCue()
        node = _make_node()
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.arm.side_effect = RuntimeError("media missing")
            node._arm_with_enabled_guard(cue, project_gen=1)  # must not raise
            ch.disarm.assert_not_called()


class TestActionResultSinkEnableDisable:

    def _sink(self, node, outcome):
        with patch("cuemsengine.cues.ActionHandler.ACTION_HANDLER") as ah:
            node._action_result_sink(outcome)
        return ah

    def test_enable_applied_notifies_and_arms(self):
        cue = _FakeCue()
        node = _make_node(script_cue=cue)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            self._sink(
                node,
                {"action_type": "enable", "status": "applied", "target_id": cue.id},
            )
            node._notify_cue_enabled.assert_called_once_with(cue.id, True)
            assert _wait_until(lambda: ch.arm.called)
            _join_rearm(cue.id)
            ch.arm.assert_called_once_with(cue, init=True)

    def test_applied_no_change_is_a_no_op(self):
        cue = _FakeCue()
        node = _make_node(script_cue=cue)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            self._sink(
                node,
                {
                    "action_type": "enable",
                    "status": "applied_no_change",
                    "target_id": cue.id,
                },
            )
            node._notify_cue_enabled.assert_not_called()
            _join_rearm(cue.id)
            ch.arm.assert_not_called()

    def test_script_none_still_notifies(self):
        node = _make_node(script_cue=None)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER"):
            self._sink(
                node,
                {"action_type": "enable", "status": "applied", "target_id": "cue-x"},
            )
            node._notify_cue_enabled.assert_called_once_with("cue-x", True)

    def test_cue_not_found_still_notifies(self):
        node = _make_node()  # script.find -> None
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            self._sink(
                node,
                {"action_type": "disable", "status": "applied", "target_id": "cue-x"},
            )
            node._notify_cue_enabled.assert_called_once_with("cue-x", False)
            ch.disarm.assert_not_called()

    def test_side_effect_failure_does_not_starve_notify(self):
        cue = _FakeCue()
        node = _make_node(script_cue=cue)
        node._apply_cue_enabled_side_effects = _MM(side_effect=RuntimeError("boom"))
        # Must not raise (a raise would be swallowed by _emit_outcome and
        # previously starved the notify)
        self._sink(
            node, {"action_type": "enable", "status": "applied", "target_id": cue.id}
        )
        node._notify_cue_enabled.assert_called_once_with(cue.id, True)


class TestHandleCueEnabledDelegates:

    def test_parse_set_flag_delegate_notify(self):
        cue = _FakeCue(enabled=True)
        node = _make_node(script_cue=cue)
        node._apply_cue_enabled_side_effects = _MM()
        node._handle_cue_enabled(f"{cue.id} 0")
        assert cue.enabled is False
        node._apply_cue_enabled_side_effects.assert_called_once_with(cue, False)
        node._notify_cue_enabled.assert_called_once_with(cue.id, False)


# ---------------------------------------------------------------------------
# GO anchor -- the controller's own MTC instant, not each node's live read
# (Badajoz 2026-09-25: setnextcue's synchronous _arm_ahead held
# _command_lock for ~500ms; by the time go_script ran, this node's own MTC
# read ~520ms later than the other two boxes', anchoring its whole
# Auto-continue chain late. MTC-following cannot correct a wrong anchor.)
# ---------------------------------------------------------------------------


class TestResolveGoAnchor:
    """_resolve_go_anchor prefers the controller's GO instant over this
    node's own live MTC read, with a bounded, explained fallback."""

    def _node(self, local_ms):
        from cuemsengine.NodeEngine import NodeEngine

        node = object.__new__(NodeEngine)
        node.mtc_listener = _MM()
        node.mtc_listener.main_tc.milliseconds_exact = local_ms
        return node

    def test_uses_controller_instant_within_tolerance(self):
        node = self._node(local_ms=79760.0)
        assert node._resolve_go_anchor({"go_mtc_ms": 79240.0}) == 79240.0

    def test_accepts_controller_instant_slightly_ahead(self):
        # go_script on the controller runs microseconds before this node
        # reads its own MTC to compute lag -- allow a small future slack.
        node = self._node(local_ms=1000.0)
        assert node._resolve_go_anchor({"go_mtc_ms": 1150.0}) == 1150.0

    def test_falls_back_to_local_when_value_is_none(self):
        node = self._node(local_ms=79760.0)
        assert node._resolve_go_anchor(None) == 79760.0

    def test_falls_back_to_local_when_value_is_a_bare_string(self):
        # the editor's go_script path still sends an arbitrary string
        node = self._node(local_ms=79760.0)
        assert node._resolve_go_anchor("complex_test") == 79760.0

    def test_falls_back_to_local_when_dict_lacks_the_key(self):
        node = self._node(local_ms=79760.0)
        assert node._resolve_go_anchor({}) == 79760.0

    def test_falls_back_to_local_when_controller_instant_is_far_in_the_future(self):
        node = self._node(local_ms=1000.0)
        # 201ms ahead of local -- past the 200ms future-slack tolerance, so
        # this reads as a stale or misrouted message, not a fast controller
        assert node._resolve_go_anchor({"go_mtc_ms": 1201.0}) == 1000.0

    def test_falls_back_to_local_when_lag_looks_like_a_24h_wrap_asymmetry(self):
        # the controller resets its 24h wrap accumulator on load AND stop;
        # a node resets it only on load -- an implausibly stale controller
        # value must not be trusted over the node's own MTC.
        node = self._node(local_ms=90_000_000.0)
        assert node._resolve_go_anchor({"go_mtc_ms": 0.0}) == 90_000_000.0


class TestGoScriptUsesResolvedAnchor:
    """go_script must seed the chain from _resolve_go_anchor's result, not a
    raw live MTC read. The anchor-selection logic itself is covered by
    TestResolveGoAnchor above; this only pins the wiring."""

    def _node_ready_to_go(self):
        node = _make_node()
        node.with_mtc = True
        node.mtc_listener = _MM()
        node.ongoing_cue = None
        cue = _FakeCue(cue_id="cue-1", enabled=True, local=True)
        node.next_cue_pointer = cue
        node.set_status = _MM()
        return node, cue

    def test_anchors_from_resolve_go_anchor_result(self):
        node, cue = self._node_ready_to_go()
        with (
            patch("cuemsengine.NodeEngine.CUE_HANDLER") as mock_ch,
            patch.object(
                node, "_resolve_go_anchor", return_value=79240.0
            ) as mock_resolve,
        ):
            mock_ch.find_armed_cue.return_value = True
            mock_ch.go.return_value = _MM()
            node.go_script({"go_mtc_ms": 79240.0})

        mock_resolve.assert_called_once_with({"go_mtc_ms": 79240.0})
        mock_ch.go.assert_called_once()
        call_args = mock_ch.go.call_args.args
        assert call_args[0] is cue
        assert call_args[2] == 79240.0  # GO_mtc + Σ(0, chain breaks at cue itself)
        assert node.go_offset == 79240.0


# ---------------------------------------------------------------------------
# setnextcue's lookahead moves off _command_lock (Badajoz 2026-09-25,
# 869f79ecc). The incident's ~500ms delay lived entirely in _arm_ahead's
# walk from the selected cue, not in arming the selected cue itself -- that
# stays synchronous (a GO right after setnextcue needs it immediately).
# ---------------------------------------------------------------------------


class TestSetNextCuePreArm:

    def _node(self, cue):
        node = _make_node(script_cue=cue)
        node._project_generation = 1
        node._selection_epoch = 0
        return node

    def test_arms_selected_cue_synchronously_before_returning(self):
        cue = _FakeCue(cue_id="cue-1")
        node = self._node(cue)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = []
            node.set_next_cue("cue-1")
            ch.arm.assert_called_once_with(cue, init=True)
        _join_prearm(cue.id)

    def test_lookahead_runs_off_the_calling_thread(self):
        cue = _FakeCue(cue_id="cue-1")
        node = self._node(cue)
        release = threading.Event()
        entered = threading.Event()

        def blocking_arm_ahead(*args, **kwargs):
            entered.set()
            release.wait(timeout=2.0)
            return []

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.side_effect = blocking_arm_ahead
            t0 = time.time()
            node.set_next_cue("cue-1")
            elapsed = time.time() - t0
        assert elapsed < 0.2, "set_next_cue must not block on _arm_ahead"
        assert _wait_until(entered.is_set), "PreArm thread never started"
        release.set()
        _join_prearm(cue.id)

    def test_prearm_passes_should_continue_and_arms_audio_too(self):
        """869f79ecc, decided 2026-09-26 on measured data: audio is NOT
        excluded from the PreArm walk any more. JACK port waits measured
        0-0.6 s per audioplayer (Badajoz, taller, test2 node01) and at most
        one extra concurrent arm results from PreArm, far from arm()'s 5 s
        waiter timeout; excluding it cost ~320 ms of late audio on every
        run where audio follows local cues."""
        cue = _FakeCue(cue_id="cue-1")
        node = self._node(cue)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = []
            node.set_next_cue("cue-1")
            _join_prearm(cue.id)

        assert ch._arm_ahead.called
        call = ch._arm_ahead.call_args
        assert call.args[0] is cue
        assert callable(call.kwargs["should_continue"])
        assert not call.kwargs.get("skip_arming_types"), "audio must not be excluded"

    def test_repeated_selection_bumps_selection_epoch(self):
        cue_a = _FakeCue(cue_id="cue-a")
        cue_b = _FakeCue(cue_id="cue-b")
        node = _make_node()
        node.script.find.side_effect = [cue_a, cue_b]
        node._project_generation = 1
        node._selection_epoch = 0
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = True  # already armed -- skip sync arm
            ch._arm_ahead.return_value = []
            node.set_next_cue("cue-a")
            assert node._selection_epoch == 1
            node.set_next_cue("cue-b")
            assert node._selection_epoch == 2
        _join_prearm(cue_a.id)
        _join_prearm(cue_b.id)

    def test_should_continue_reflects_the_epoch_at_spawn_time(self):
        """869f79ecc blocker #3: a stale PreArm thread's should_continue
        must go False as soon as a LATER selection lands, even though it
        captured its own epoch before that happened."""
        cue = _FakeCue(cue_id="cue-1")
        node = self._node(cue)
        captured = {}

        def capture_and_return(target, should_continue=None, skip_arming_types=()):
            captured["should_continue"] = should_continue
            return []

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.side_effect = capture_and_return
            node.set_next_cue("cue-1")
            _join_prearm(cue.id)

        assert captured["should_continue"]() is True
        node._selection_epoch += 1  # a later selection landed
        assert captured["should_continue"]() is False

    def test_project_generation_bump_also_stops_the_walk(self):
        cue = _FakeCue(cue_id="cue-1")
        node = self._node(cue)
        captured = {}

        def capture_and_return(target, should_continue=None, skip_arming_types=()):
            captured["should_continue"] = should_continue
            return []

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.side_effect = capture_and_return
            node.set_next_cue("cue-1")
            _join_prearm(cue.id)

        assert captured["should_continue"]() is True
        node._project_generation += 1  # a STOP/load bumped it
        assert captured["should_continue"]() is False

    def test_disarms_newly_armed_cues_when_project_changed_underneath(self):
        cue = _FakeCue(cue_id="cue-1")
        node = self._node(cue)
        armed_by_walk = _FakeCue(cue_id="armed-by-walk")

        def swap_script_and_return(target, should_continue=None, skip_arming_types=()):
            node.script = MagicMock()  # a different project loaded meanwhile
            return [armed_by_walk]

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.side_effect = swap_script_and_return
            node.set_next_cue("cue-1")
            _join_prearm(cue.id)
            ch.disarm.assert_called_once_with(armed_by_walk)

    def test_does_not_disarm_anything_when_same_script(self):
        cue = _FakeCue(cue_id="cue-1")
        node = self._node(cue)
        armed_by_walk = _FakeCue(cue_id="armed-by-walk")

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = [armed_by_walk]
            node.set_next_cue("cue-1")
            _join_prearm(cue.id)
            ch.disarm.assert_not_called()


# ---------------------------------------------------------------------------
# A node pre-arms its next local segment when a GO advances its pointer with
# nothing local to play (Medina sala1, 2026-09-30). Shape: ctrl go -> ctrl
# PAUSE -> node go -> node pause. The load-time walk stops at the ctrl pause,
# so the node armed nothing; GO 1 only advanced the pointer; GO 2 found the
# node's first cue unarmed and fired it late (240 ms at sala1, 120 ms on
# test2 with the full 869f79ecc build). Fix: on that advance, arm what the
# NEXT GO will dispatch on this node -- the same go-chain walk go_script uses
# -- synchronously, plus the PreArm lookahead thread, like set_next_cue.
# ---------------------------------------------------------------------------


class _ChainCue(_FakeCue):
    """_FakeCue plus the chain fields go_script / the pre-arm walk read."""

    def __init__(self, cue_id, local, post_go, enabled=True):
        super().__init__(cue_id=cue_id, enabled=enabled, local=local)
        self.post_go = post_go
        self._target_object = None


def _chain(*cues):
    """Link cues in order: _target_object = next sibling, and get_next_cue()
    = the cue after the chain's hand-off (first cue after a non-'go' one),
    which is what Cue.get_next_cue returns for a flat list."""
    for a, b in zip(cues, cues[1:]):
        a._target_object = b
    for i, c in enumerate(cues):
        nxt = None
        j = i
        while j < len(cues):
            if cues[j].post_go != "go":
                nxt = cues[j + 1] if j + 1 < len(cues) else None
                break
            j += 1
        c._next = nxt
    return cues


def _go_node(pointer, ongoing=None):
    node = _make_node()
    node.with_mtc = True
    node.mtc_listener = _MM()
    node.ongoing_cue = ongoing
    node.next_cue_pointer = pointer
    node.set_status = _MM()
    node._selection_epoch = 0
    node._resolve_go_anchor = _MM(return_value=1000.0)
    return node


class TestFirstLocalEnabledInGoChain:

    def test_returns_start_when_it_is_local_and_enabled(self):
        (n1,) = _chain(_ChainCue("n1", True, "pause"))
        from cuemsengine.core.BaseEngine import BaseEngine

        assert BaseEngine._first_local_enabled_in_go_chain(n1) is n1

    def test_walks_other_nodes_go_cues_to_the_local_one(self):
        c1, n1 = _chain(_ChainCue("c1", False, "go"), _ChainCue("n1", True, "pause"))
        from cuemsengine.core.BaseEngine import BaseEngine

        assert BaseEngine._first_local_enabled_in_go_chain(c1) is n1

    def test_stops_at_another_nodes_hand_off(self):
        c1, c2, n1 = _chain(
            _ChainCue("c1", False, "go"),
            _ChainCue("c2", False, "pause"),
            _ChainCue("n1", True, "go"),
        )
        from cuemsengine.core.BaseEngine import BaseEngine

        assert BaseEngine._first_local_enabled_in_go_chain(c1) is None

    def test_skips_a_local_disabled_cue_in_the_chain(self):
        """The load walk used to stop at a local-but-DISABLED cue (non-None,
        so no fallback) and arm() then refused it: nothing pre-armed. Same
        predicate as go_script now: _local AND enabled."""
        d1, n1 = _chain(
            _ChainCue("d1", True, "go", enabled=False), _ChainCue("n1", True, "pause")
        )
        from cuemsengine.core.BaseEngine import BaseEngine

        assert BaseEngine._first_local_enabled_in_go_chain(d1) is n1

    def test_none_start_is_none(self):
        from cuemsengine.core.BaseEngine import BaseEngine

        assert BaseEngine._first_local_enabled_in_go_chain(None) is None


class TestAdvanceWithNoLocalCuePreArms:

    def test_sala1_shape_first_go_arms_the_nodes_first_segment(self):
        c1, c2, n1, n2 = _chain(
            _ChainCue("c1", False, "go"),
            _ChainCue("c2", False, "pause"),
            _ChainCue("n1", True, "go"),
            _ChainCue("n2", True, "pause"),
        )
        node = _go_node(pointer=c1)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = []
            node.go_script({"go_mtc_ms": 1000.0})
            _join_prearm(n1.id)

        assert node.next_cue_pointer is n1
        ch.go.assert_not_called()
        ch.arm.assert_called_once_with(n1, init=True)
        assert ch._arm_ahead.call_args.args[0] is n1
        assert callable(ch._arm_ahead.call_args.kwargs["should_continue"])

    def test_later_segment_behind_another_nodes_pause(self):
        """After the node already played (ongoing_cue set), a GO whose chain
        is all other-node cues still arms the node's NEXT segment."""
        played, c3, n3 = _chain(
            _ChainCue("played", True, "pause"),
            _ChainCue("c3", False, "pause"),
            _ChainCue("n3", True, "pause"),
        )
        node = _go_node(pointer=c3, ongoing=played)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = []
            node.go_script({"go_mtc_ms": 1000.0})
            _join_prearm(n3.id)

        assert node.next_cue_pointer is n3
        ch.arm.assert_called_once_with(n3, init=True)

    def test_nothing_armed_when_the_next_go_is_another_nodes_too(self):
        c1, c2, c3, n1 = _chain(
            _ChainCue("c1", False, "pause"),
            _ChainCue("c2", False, "pause"),
            _ChainCue("c3", False, "go"),
            _ChainCue("n1", True, "pause"),
        )
        node = _go_node(pointer=c1)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            node.go_script({"go_mtc_ms": 1000.0})

        # Pointer is c2 (another node's hand-off): nothing for us next GO,
        # so nothing is armed yet -- no whole-show preload.
        assert node.next_cue_pointer is c2
        ch.arm.assert_not_called()
        ch._arm_ahead.assert_not_called()

    def test_already_armed_target_is_not_re_armed_but_lookahead_runs(self):
        c1, n1 = _chain(_ChainCue("c1", False, "pause"), _ChainCue("n1", True, "pause"))
        node = _go_node(pointer=c1)
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = True
            ch._arm_ahead.return_value = []
            node.go_script({"go_mtc_ms": 1000.0})
            _join_prearm(n1.id)

        ch.arm.assert_not_called()
        assert ch._arm_ahead.call_args.args[0] is n1

    def test_advance_prearm_is_abandoned_by_a_stop_or_new_selection(self):
        c1, n1 = _chain(_ChainCue("c1", False, "pause"), _ChainCue("n1", True, "pause"))
        node = _go_node(pointer=c1)
        captured = {}

        def capture(target, should_continue=None, skip_arming_types=()):
            captured["should_continue"] = should_continue
            return []

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.side_effect = capture
            node.go_script({"go_mtc_ms": 1000.0})
            _join_prearm(n1.id)

        assert captured["should_continue"]() is True
        node._project_generation += 1  # STOP / load
        assert captured["should_continue"]() is False


class TestAdvancePreArmRunsOffTheCommandLock:
    """The advance pre-arm must not arm inside run_command's _command_lock:
    an operator STOP (or the next GO) arriving while an audio cue spawns and
    waits for its JACK ports would wait for the whole arm -- the same
    arm-inside-the-lock shape 869f79ecc removed from set_next_cue's
    lookahead. A GO that lands mid-arm is still safe: arm() makes it wait on
    the in-progress arm's _loading event instead of arming twice."""

    def test_target_is_armed_on_the_prearm_thread_not_the_callers(self):
        c1, n1 = _chain(_ChainCue("c1", False, "pause"), _ChainCue("n1", True, "pause"))
        node = _go_node(pointer=c1)
        node._command_lock = threading.Lock()
        node.commands_dict = {"go": node.go_script}
        arming_threads = []

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = []
            ch.arm.side_effect = lambda *a, **k: arming_threads.append(
                threading.current_thread().name
            )
            node.run_command("go", {"go_mtc_ms": 1000.0})
            _join_prearm(n1.id)

        assert arming_threads == [f"PreArm:{n1.id}"]

    def test_a_stop_before_the_thread_runs_skips_the_arm(self):
        c1, n1 = _chain(_ChainCue("c1", False, "pause"), _ChainCue("n1", True, "pause"))
        node = _go_node(pointer=c1)
        node._project_generation = 7
        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = []
            node._prearm_segment(n1, 6, node._selection_epoch, node.script)

        ch.arm.assert_not_called()

    def test_a_project_change_during_the_arm_undoes_it(self):
        c1, n1 = _chain(_ChainCue("c1", False, "pause"), _ChainCue("n1", True, "pause"))
        node = _go_node(pointer=c1)
        old_script = node.script

        def arm_while_a_new_project_loads(cue, init=False):
            node.script = _MM()
            cue.loaded = True
            return True

        with patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch:
            ch.find_armed_cue.return_value = False
            ch._arm_ahead.return_value = []
            ch.arm.side_effect = arm_while_a_new_project_loads
            node._prearm_segment(
                n1, node._project_generation, node._selection_epoch, old_script
            )

        ch.disarm.assert_called_once_with(n1)
