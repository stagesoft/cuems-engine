# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
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
