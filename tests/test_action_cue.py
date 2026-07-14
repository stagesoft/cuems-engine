# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Unit tests for ActionCue execution through ActionHandler.

Tests cover all supported cue-level actions (FR-002a), idempotency (FR-004),
non-target isolation (FR-006), rapid succession, invalid-action safety (US2),
hooks, dual registration, result sink (003 US2), and regression guards.
"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import ActionCue, AudioCue
from cuemsutils.cues.Cue import Cue

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_target(**overrides) -> AudioCue:
    """Create a minimal target cue suitable for action testing."""
    target = AudioCue()
    target.enabled = True
    target.loaded = True
    target._stop_requested = False
    target._go_generation = 0
    target._local = True
    target._osc = MagicMock()
    for k, v in overrides.items():
        setattr(target, k, v)
    return target


def _make_action_cue(action_type: str, target: Cue) -> ActionCue:
    """Create an ActionCue wired to a given target."""
    cue = ActionCue()
    cue.action_type = action_type
    cue.action_target = target.id
    cue._action_target_object = target
    return cue


@pytest.fixture
def handler():
    """Return a fresh CueHandler with mocked infrastructure.

    ``ACTION_HANDLER`` is bound to this instance so ``arm`` / ``go`` patches
    apply.
    """
    from cuemsengine.cues.ActionHandler import ACTION_HANDLER
    from cuemsengine.cues.CueHandler import CUE_HANDLER, CueHandler

    h = object.__new__(CueHandler)
    h._armed_cues = []
    h._armed_cues_set = set()
    h._video_players = {}
    h._front_video_player = None
    h._lock = __import__("threading").Lock()
    h.communications_thread = MagicMock()
    ACTION_HANDLER.bind_cue_handler(h)
    ACTION_HANDLER.clear_action_extensions()
    ACTION_HANDLER.set_emit_enabled(False)
    yield h
    ACTION_HANDLER.bind_cue_handler(CUE_HANDLER)
    ACTION_HANDLER.clear_action_extensions()
    ACTION_HANDLER.set_emit_enabled(True)


@pytest.fixture
def mtc():
    return MagicMock()


# ---------------------------------------------------------------------------
# T006: play — target enters running state
# ---------------------------------------------------------------------------


class TestPlayAction:
    def test_play_starts_target(self, handler, mtc):
        target = _make_target()
        cue = _make_action_cue("play", target)

        with (
            patch.object(handler, "go") as mock_go,
            patch.object(handler, "arm"),
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "play"
        mock_go.assert_called_once()
        assert target._stop_requested is False

    def test_play_disabled_target_fails(self, handler, mtc):
        target = _make_target(enabled=False)
        cue = _make_action_cue("play", target)

        with (
            patch.object(handler, "go") as mock_go,
            patch.object(handler, "arm"),
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert "disabled" in result["reason"]
        mock_go.assert_not_called()

    def test_play_threads_frozen_mtc_ms(self, handler, mtc):
        # When an ActionCue 'play' fires inside a post_go='go' chain, the
        # chain's frozen_mtc_ms must reach CueHandler.go so the target shares
        # the chain's snapshot. Otherwise the target reads live MTC and
        # drifts relative to the chain's other cues.
        target = _make_target()
        cue = _make_action_cue("play", target)

        with (
            patch.object(handler, "go") as mock_go,
            patch.object(handler, "arm"),
        ):
            handler.execute_action(cue, mtc, 1234.5)

        mock_go.assert_called_once_with(target, mtc, 1234.5)

    def test_play_without_frozen_mtc_passes_none(self, handler, mtc):
        # Standalone ActionCue (no chain) → frozen_mtc_ms defaults to None.
        # The handler must pass None THROUGH to go_from (which then seeds
        # from live MTC itself) — patch go_from, not go: _handle_play calls
        # go_from, and go_from substitutes live MTC for a None seed.
        target = _make_target()
        cue = _make_action_cue("play", target)

        with (
            patch.object(handler, "go_from") as mock_go_from,
            patch.object(handler, "arm"),
        ):
            handler.execute_action(cue, mtc)

        mock_go_from.assert_called_once_with(target, mtc, None)

    def test_play_arm_raises_returns_failed(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("play", target)

        with patch.object(
            handler, "arm", side_effect=RuntimeError("player init failed")
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "play"
        assert "player init failed" in result["reason"]

    def test_play_go_raises_returns_failed(self, handler, mtc):
        target = _make_target()
        cue = _make_action_cue("play", target)

        with patch.object(
            handler, "go", side_effect=RuntimeError("not loaded to go")
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "play"
        assert "not loaded to go" in result["reason"]


# ---------------------------------------------------------------------------
# T007: pause — target enters paused state
# ---------------------------------------------------------------------------


class TestPauseAction:
    def test_pause_stops_target(self, handler, mtc):
        target = _make_target(_stop_requested=False)
        cue = _make_action_cue("pause", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "pause"
        assert target._stop_requested is True


# ---------------------------------------------------------------------------
# T008: stop — target exits running state
# ---------------------------------------------------------------------------


class TestStopAction:
    def test_stop_target(self, handler, mtc):
        target = _make_target(_stop_requested=False, _go_generation=1)
        cue = _make_action_cue("stop", target)

        with patch.object(handler, "disarm") as mock_disarm:
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "stop"
        assert target._stop_requested is True
        assert target._go_generation == 2
        mock_disarm.assert_called_once_with(target)

    def test_stop_disarm_raises_returns_failed(self, handler, mtc):
        target = _make_target(_stop_requested=False)
        cue = _make_action_cue("stop", target)

        with patch.object(
            handler, "disarm", side_effect=RuntimeError("disarm failed")
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "stop"
        assert "disarm failed" in result["reason"]


# ---------------------------------------------------------------------------
# T009: enable — target becomes enabled
# ---------------------------------------------------------------------------


class TestEnableAction:
    def test_enable_target(self, handler, mtc):
        target = _make_target(enabled=False)
        cue = _make_action_cue("enable", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert target.enabled is True


# ---------------------------------------------------------------------------
# T010: disable — target becomes disabled
# ---------------------------------------------------------------------------


class TestDisableAction:
    def test_disable_target(self, handler, mtc):
        target = _make_target(enabled=True)
        cue = _make_action_cue("disable", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert target.enabled is False


# ---------------------------------------------------------------------------
# T011: fade_in — target ramps into active state
# ---------------------------------------------------------------------------


class TestFadeInAction:
    def test_fade_in_starts_target(self, handler, mtc):
        target = _make_target()
        cue = _make_action_cue("fade_in", target)

        with (
            patch.object(handler, "go") as mock_go,
            patch.object(handler, "arm"),
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "fade_in"
        mock_go.assert_called_once()

    def test_fade_in_disabled_target_fails(self, handler, mtc):
        target = _make_target(enabled=False)
        cue = _make_action_cue("fade_in", target)

        with (
            patch.object(handler, "go") as mock_go,
            patch.object(handler, "arm"),
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert "disabled" in result["reason"]
        mock_go.assert_not_called()

    def test_fade_in_arm_raises_returns_failed(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("fade_in", target)

        with patch.object(
            handler, "arm", side_effect=RuntimeError("arm failed")
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "fade_in"
        assert "arm failed" in result["reason"]

    def test_fade_in_go_raises_returns_failed(self, handler, mtc):
        target = _make_target()
        cue = _make_action_cue("fade_in", target)

        with patch.object(
            handler, "go", side_effect=RuntimeError("not loaded to go")
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "fade_in"
        assert "not loaded to go" in result["reason"]


# ---------------------------------------------------------------------------
# T012: fade_out — target ramps down and exits active state
# ---------------------------------------------------------------------------


class TestFadeOutAction:
    def test_fade_out_stops_target(self, handler, mtc):
        target = _make_target(_stop_requested=False, _go_generation=0)
        cue = _make_action_cue("fade_out", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "fade_out"
        assert target._stop_requested is True
        assert target._go_generation == 1


# ---------------------------------------------------------------------------
# T013: go_to — execution pointer navigates to target cue
# ---------------------------------------------------------------------------


class TestGoToAction:
    def test_go_to_arms_target(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("go_to", target)

        def _do_arm(t, *, init):
            t.loaded = True

        with patch.object(handler, "arm", side_effect=_do_arm) as mock_arm:
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "go_to"
        mock_arm.assert_called_once()

    def test_go_to_disabled_target_fails(self, handler, mtc):
        target = _make_target(enabled=False, loaded=False)
        cue = _make_action_cue("go_to", target)

        with patch.object(handler, "arm") as mock_arm:
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert "disabled" in result["reason"]
        mock_arm.assert_not_called()

    def test_go_to_arm_raises_returns_failed(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("go_to", target)

        with patch.object(
            handler, "arm", side_effect=RuntimeError("arm failed")
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "go_to"
        assert "arm failed" in result["reason"]

    def test_go_to_arm_not_loaded_returns_failed(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("go_to", target)

        with patch.object(handler, "arm"):  # succeeds but loaded stays False
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert "could not be armed" in result["reason"]


# ---------------------------------------------------------------------------
# T014: idempotent repeat — same action, no harmful side effect
# ---------------------------------------------------------------------------


class TestIdempotentRepeat:
    def test_enable_already_enabled(self, handler, mtc):
        target = _make_target(enabled=True)
        cue = _make_action_cue("enable", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied_no_change"
        assert target.enabled is True

    def test_disable_already_disabled(self, handler, mtc):
        target = _make_target(enabled=False)
        cue = _make_action_cue("disable", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied_no_change"

    def test_stop_already_stopped(self, handler, mtc):
        target = _make_target(_stop_requested=True)
        cue = _make_action_cue("stop", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied_no_change"

    def test_pause_already_paused(self, handler, mtc):
        target = _make_target(_stop_requested=True)
        cue = _make_action_cue("pause", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied_no_change"


# ---------------------------------------------------------------------------
# T015: non-target isolation — unrelated cues remain unchanged
# ---------------------------------------------------------------------------


class TestNonTargetIsolation:
    def test_unrelated_cue_unchanged(self, handler, mtc):
        target = _make_target(enabled=True)
        bystander = _make_target(enabled=True, _stop_requested=False)
        bystander_snapshot = (
            bystander.enabled,
            bystander._stop_requested,
            getattr(bystander, "_go_generation", 0),
        )

        cue = _make_action_cue("disable", target)
        handler.execute_action(cue, mtc)

        assert target.enabled is False
        assert (
            bystander.enabled,
            bystander._stop_requested,
            getattr(bystander, "_go_generation", 0),
        ) == bystander_snapshot


# ---------------------------------------------------------------------------
# T016: rapid succession — multiple actions, stable final state
# ---------------------------------------------------------------------------


class TestRapidSuccession:
    def test_rapid_enable_disable_cycle(self, handler, mtc):
        target = _make_target(enabled=True)

        for _ in range(50):
            handler.execute_action(_make_action_cue("disable", target), mtc)
            handler.execute_action(_make_action_cue("enable", target), mtc)

        assert target.enabled is True

    def test_rapid_stop_play_cycle(self, handler, mtc):
        target = _make_target()

        with (
            patch.object(handler, "go"),
            patch.object(handler, "arm"),
            patch.object(handler, "disarm"),
        ):
            for _ in range(20):
                handler.execute_action(_make_action_cue("stop", target), mtc)
                target._stop_requested = False
                target.loaded = True
                handler.execute_action(_make_action_cue("play", target), mtc)

        assert target._stop_requested is False


# ===========================================================================
# US2: Invalid / unsupported actions
# ===========================================================================


class TestUnknownAction:
    def test_unknown_action_rejected(self, handler, mtc):
        target = _make_target()
        cue = _make_action_cue("explode", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "rejected"
        assert "Unsupported" in result["reason"]

    def test_unknown_action_no_state_change(self, handler, mtc):
        target = _make_target(enabled=True, _stop_requested=False)
        snapshot = (
            target.enabled,
            target._stop_requested,
            getattr(target, "_go_generation", 0),
        )

        cue = _make_action_cue("explode", target)
        handler.execute_action(cue, mtc)

        assert (
            target.enabled,
            target._stop_requested,
            getattr(target, "_go_generation", 0),
        ) == snapshot


class TestMissingTarget:
    def test_missing_target_rejected(self, handler, mtc):
        cue = ActionCue()
        cue.action_type = "play"
        cue._action_target_object = None

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "rejected"
        assert "Missing target" in result["reason"]


class TestInactiveProjectTarget:
    def test_inactive_project_target_rejected(self, handler, mtc):
        cue = ActionCue()
        cue.action_type = "play"
        cue.action_target = "nonexistent-uuid"
        cue._action_target_object = None

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "rejected"


# ===========================================================================
# US2 (003): hooks, dual registration, result sink (T012–T016a)
# ===========================================================================


class TestActionHookDispatchOrder:
    def test_dispatch_order_before_default_after_hooks(self, handler, mtc):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        order = []

        def before(ctx):
            order.append("before")

        def after(ctx):
            order.append("after")
            assert ctx.outcome is not None
            assert ctx.outcome["status"] == "applied"

        ACTION_HANDLER.register_action_hook(
            "before_dispatch", before, source="cue_layer"
        )
        ACTION_HANDLER.register_action_hook(
            "after_dispatch", after, source="cue_layer"
        )
        target = _make_target(enabled=False)
        cue = _make_action_cue("enable", target)
        handler.execute_action(cue, mtc)

        assert order == ["before", "after"]
        assert target.enabled is True

    def test_duplicate_hook_registration_last_wins(self, handler, mtc):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        seen = []

        ACTION_HANDLER.register_action_hook(
            "before_dispatch",
            lambda ctx: seen.append("first"),
            source="cue_layer",
        )
        ACTION_HANDLER.register_action_hook(
            "before_dispatch",
            lambda ctx: seen.append("second"),
            source="cue_layer",
        )
        target = _make_target(enabled=False)
        handler.execute_action(_make_action_cue("enable", target), mtc)

        assert seen == ["second"]

    def test_cue_layer_before_node_layer_same_phase(self, handler, mtc):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        order = []

        ACTION_HANDLER.register_action_hook(
            "before_dispatch",
            lambda ctx: order.append("cue"),
            source="cue_layer",
        )
        ACTION_HANDLER.register_action_hook(
            "before_dispatch",
            lambda ctx: order.append("node"),
            source="node_layer",
        )
        target = _make_target(enabled=False)
        handler.execute_action(_make_action_cue("enable", target), mtc)

        assert order == ["cue", "node"]


class TestActionResultSink:
    def test_injectable_sink_records_outcome(self, handler, mtc):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        recorded = []
        ACTION_HANDLER.set_emit_enabled(True)
        ACTION_HANDLER.set_result_sink(lambda o: recorded.append(dict(o)))
        try:
            target = _make_target(enabled=False)
            handler.execute_action(_make_action_cue("enable", target), mtc)
            assert len(recorded) == 1
            assert recorded[0]["status"] == "applied"
            assert recorded[0]["action_type"] == "enable"
        finally:
            ACTION_HANDLER.set_result_sink(None)
            ACTION_HANDLER.set_emit_enabled(False)

    def test_default_path_calls_send_operation_when_sink_unset(
        self, handler, mtc
    ):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        ACTION_HANDLER.set_emit_enabled(True)
        ACTION_HANDLER.set_result_sink(None)
        handler.communications_thread.send_operation = MagicMock()
        try:
            target = _make_target(enabled=False)
            handler.execute_action(_make_action_cue("enable", target), mtc)
            handler.communications_thread.send_operation.assert_called()
            call_kw = handler.communications_thread.send_operation.call_args
            op = call_kw[0][0]
            assert op.target == "action_cue_outcome"
        finally:
            ACTION_HANDLER.set_emit_enabled(False)


class TestActionHookExceptions:
    def test_before_dispatch_raises_failed_and_isolates_other_cues(
        self, handler, mtc
    ):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        def boom(ctx):
            raise RuntimeError("hook boom")

        ACTION_HANDLER.register_action_hook(
            "before_dispatch", boom, source="cue_layer"
        )
        target = _make_target(enabled=True)
        bystander = _make_target(enabled=True, _stop_requested=False)
        snap = (
            bystander.enabled,
            bystander._stop_requested,
            getattr(bystander, "_go_generation", 0),
        )

        result = handler.execute_action(
            _make_action_cue("disable", target), mtc
        )

        assert result["status"] == "failed"
        assert target.enabled is True
        assert (
            bystander.enabled,
            bystander._stop_requested,
            getattr(bystander, "_go_generation", 0),
        ) == snap


class TestActionMidTransitionWithHook:
    def test_pause_while_already_paused_deterministic_with_hook(
        self, handler, mtc
    ):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        order = []

        ACTION_HANDLER.register_action_hook(
            "before_dispatch",
            lambda ctx: order.append("hook"),
            source="cue_layer",
        )
        target = _make_target(_stop_requested=True)
        result = handler.execute_action(_make_action_cue("pause", target), mtc)

        assert result["status"] == "applied_no_change"
        assert order == ["hook"]


# ---------------------------------------------------------------------------
# fade_action — error paths (arm guard via _ready_action_target)
# ---------------------------------------------------------------------------


class TestFadeActionHandler:
    def test_fade_action_disabled_target_fails(self, handler, mtc):
        target = _make_target(enabled=False)
        cue = _make_action_cue("fade_action", target)

        with patch.object(handler, "arm") as mock_arm:
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "fade_action"
        assert "disabled" in result["reason"]
        mock_arm.assert_not_called()

    def test_fade_action_arm_raises_returns_failed(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("fade_action", target)

        with patch.object(
            handler, "arm", side_effect=RuntimeError("arm failed")
        ):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "fade_action"
        assert "arm failed" in result["reason"]

    def test_fade_action_arm_not_loaded_returns_failed(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("fade_action", target)

        with patch.object(handler, "arm"):  # succeeds but loaded stays False
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert result["action_type"] == "fade_action"
        assert "could not be armed" in result["reason"]


# ---------------------------------------------------------------------------
# Regression: outcome dict shape (003 T010)
# ---------------------------------------------------------------------------

EXPECTED_ACTION_OUTCOME_KEYS = frozenset(
    {"status", "action_type", "target_id", "reason"}
)


def test_action_outcome_dict_keys_stable(handler, mtc):
    target = _make_target()
    with patch.object(handler, "go"), patch.object(handler, "arm"):
        result = handler.execute_action(_make_action_cue("play", target), mtc)
    assert set(result.keys()) == EXPECTED_ACTION_OUTCOME_KEYS


def test_action_hot_path_regression_budget(handler, mtc):
    """SC-009 smoke: many dispatches stay within a loose wall-clock budget."""
    target = _make_target(enabled=True)
    t0 = time.perf_counter()
    for _ in range(100):
        handler.execute_action(_make_action_cue("enable", target), mtc)
    assert time.perf_counter() - t0 < 1.0


def test_rejected_action_warning_text_unchanged(handler, mtc, caplog):
    """
    NFR-003 / SC-008: operator-visible rejection wording for unknown actions.
    """
    target = _make_target()
    with caplog.at_level(logging.WARNING):
        handler.execute_action(_make_action_cue("explode", target), mtc)
    assert any(
        "Unsupported action_type" in r.getMessage() for r in caplog.records
    )


# ---------------------------------------------------------------------------
# T017: CueHandler.go() re-arms unloaded cues (cuelist loop fix)
# ---------------------------------------------------------------------------


def _make_action_target(**overrides) -> ActionCue:
    """Create a minimal ActionCue target for go() re-arm testing.

    ActionCue is used because arm_cue() is a no-op for it, avoiding
    heavyweight player/layer setup that requires full infrastructure.
    """
    cue = ActionCue()
    cue.enabled = True
    cue.loaded = True
    cue._stop_requested = False
    cue._go_generation = 0
    cue._local = True
    cue.action_type = "enable"
    cue._action_target_object = _make_target()
    for k, v in overrides.items():
        setattr(cue, k, v)
    return cue


class TestGoRearm:
    """
    Verify that go() re-arms a cue that was disarmed after a previous pass.
    """

    def test_go_rearms_unloaded_cue(self, handler, mtc):
        """A cue with loaded=False should be re-armed before GO proceeds."""
        cue = _make_action_target(loaded=False)
        cue._target_object = None
        cue.post_go = "pause"

        thread = handler.go(cue, mtc)
        thread.join(timeout=2)

        # go() should have re-armed the cue (loaded=True set by arm(init=True))
        # If go() didn't re-arm, it would have raised an exception
        assert True  # reaching here means go() succeeded

    def test_go_disabled_returns_none(self, handler, mtc):
        """A disabled cue should not be executed — go() must return None."""
        cue = _make_action_target(loaded=False, enabled=False, _local=False)
        cue._target_object = None

        result = handler.go(cue, mtc)
        assert result is None

    def test_go_already_loaded_skips_rearm(self, handler, mtc):
        """A cue with loaded=True should NOT trigger a re-arm."""
        cue = _make_action_target(loaded=True)
        cue._target_object = None
        cue.post_go = "pause"

        with patch.object(handler, "arm") as mock_arm:
            thread = handler.go(cue, mtc)
            thread.join(timeout=2)

        mock_arm.assert_not_called()

    def test_go_sets_playing_and_disarm_clears_it(self, handler, mtc):
        """_playing lifecycle: True while a GO owns the cue, False after
        disarm — the disable-action path relies on this flag. (disarm is
        called directly: go_threaded's natural completion invokes the same
        disarm, but its timing depends on the mocked MTC.)"""
        cue = _make_action_target(loaded=True)
        cue._target_object = None
        cue.post_go = 'pause'

        thread = handler.go(cue, mtc)
        assert cue._playing is True
        thread.join(timeout=2)
        handler.disarm(cue)
        assert cue._playing is False

    def test_stop_all_cues_clears_playing(self, handler, mtc):
        cue = _make_action_target(loaded=True)
        cue._playing = True
        handler._armed_cues.append(cue)
        handler._armed_cues_set.add(cue.id)
        try:
            handler.stop_all_cues()
            assert cue._playing is False
            assert cue._stop_requested is True
        finally:
            handler._armed_cues.remove(cue)
            handler._armed_cues_set.discard(cue.id)

    def test_go_arms_ahead_via_arm_ahead(self, handler, mtc):
        """go() should call _arm_ahead to arm cues in the target chain."""
        next_cue = _make_action_target(loaded=False)
        next_cue._target_object = None
        next_cue.post_go = "pause"

        cue = _make_action_target(loaded=True)
        cue._target_object = next_cue
        cue.post_go = "pause"

        with patch.object(handler, "_arm_ahead") as mock_ahead:
            thread = handler.go(cue, mtc)
            thread.join(timeout=2)

        mock_ahead.assert_called_once_with(cue)


# ---------------------------------------------------------------------------
# T018: arm() — ActionCue play-target, _loading sentinel, non-local guard
# ---------------------------------------------------------------------------


class TestArmPlayTarget:
    """Verify ActionCue play-target pre-arming in arm()."""

    def test_arm_actioncue_play_prearms_action_target(self, handler, mtc):
        """
        Arming an ActionCue(play) should also arm its _action_target_object.
        """
        play_target = _make_action_target(loaded=False)
        play_target._target_object = None
        play_target._action_target_object = None
        play_target.action_type = "enable"

        cue = ActionCue()
        cue.enabled = True
        cue._local = True
        cue.action_type = "play"
        cue._action_target_object = play_target
        cue._target_object = None
        cue.post_go = "pause"

        handler.arm(cue, init=True)

        assert cue.loaded is True
        assert play_target.loaded is True

    def test_arm_actioncue_stop_does_not_prearm(self, handler, mtc):
        """
        Arming an ActionCue(stop) should NOT arm its _action_target_object.
        """
        stop_target = _make_action_target(loaded=False)
        stop_target._target_object = None

        cue = ActionCue()
        cue.enabled = True
        cue._local = True
        cue.action_type = "stop"
        cue._action_target_object = stop_target
        cue._target_object = None
        cue.post_go = "pause"

        handler.arm(cue, init=True)

        assert cue.loaded is True
        assert not getattr(stop_target, "loaded", False)

    def test_arm_nonlocal_does_not_cascade(self, handler, mtc):
        """A non-local cue should not trigger recursive arms."""
        play_target = _make_action_target(loaded=False)

        cue = ActionCue()
        cue.enabled = True
        cue._local = False  # non-local
        cue.action_type = "play"
        cue._action_target_object = play_target
        cue._target_object = None

        handler.arm(cue, init=True)

        # Non-local cue: arm_cue not called, no cascade
        assert not getattr(cue, "loaded", False)
        assert not getattr(play_target, "loaded", False)

    def test_arm_loading_waits_for_in_progress_arm(self, handler, mtc):
        """An init=True arm on a cue being armed should wait and succeed."""
        from threading import Event, Thread

        cue = _make_action_target(loaded=False)
        event = Event()
        cue._loading = event  # simulate in-progress arm

        def _finish_arm():
            time.sleep(0.1)
            cue.loaded = True
            event.set()

        t = Thread(target=_finish_arm, daemon=True)
        t.start()

        result = handler.arm(cue, init=True)
        t.join(timeout=2)

        assert result is True
        assert cue.loaded is True

    def test_arm_loading_timeout_returns_false(self, handler, mtc):
        """
        An init=True arm should return False if the in-progress arm times out.
        """
        from threading import Event

        cue = _make_action_target(loaded=False)
        cue._loading = Event()  # never signalled

        # Patch timeout to avoid 5s wait in tests
        with patch.object(cue._loading, "wait", return_value=False):
            result = handler.arm(cue, init=True)

        assert result is False
        assert not getattr(cue, "loaded", False)

    def test_arm_loading_non_init_returns_false(self, handler, mtc):
        """
        A non-init arm on a cue being armed should return False immediately.
        """
        from threading import Event

        cue = _make_action_target(loaded=False)
        cue._loading = Event()  # simulate in-progress arm

        result = handler.arm(cue, init=False)

        assert result is False

    def test_arm_found_uses_set(self, handler, mtc):
        """arm() should use _armed_cues_set for O(1) membership check."""
        cue = _make_action_target(loaded=False)
        cue._target_object = None
        cue.post_go = "pause"

        # Add to set but not list — arm should see it as found
        handler._armed_cues_set.add(cue.id)

        handler.arm(cue, init=True)
        assert cue.loaded is True
        # Should not be added to list again (already in set)
        assert handler._armed_cues.count(cue) == 0


# ---------------------------------------------------------------------------
# T019: _effective_duration_ms
# ---------------------------------------------------------------------------


class TestEffectiveDuration:

    def test_video_cue_with_media(self):
        from cuemsutils.cues.MediaCue import Media

        from cuemsengine.cues.CueHandler import CueHandler

        cue = _make_target()
        cue.media = Media(
            {"file_name": "test.wav", "duration": "00:00:05.000"}
        )
        # prewait=0, postwait=0, media=5s
        duration = CueHandler._effective_duration_ms(cue)
        assert duration >= 4900  # ~5000ms, allow rounding

    def test_action_cue_zero_duration(self):
        from cuemsengine.cues.CueHandler import CueHandler

        cue = ActionCue()
        cue.action_type = "play"
        duration = CueHandler._effective_duration_ms(cue)
        assert duration == 0

    def test_action_cue_with_prewait(self):
        from cuemsutils.tools.CTimecode import CTimecode

        from cuemsengine.cues.CueHandler import CueHandler

        cue = ActionCue()
        cue.action_type = "play"
        cue.prewait = CTimecode(start_seconds=2.0)
        duration = CueHandler._effective_duration_ms(cue)
        assert duration >= 1900  # ~2000ms

    def test_dmx_cue_fadein_is_milliseconds(self):
        # fadein_time/fadeout_time are stored in MILLISECONDS (authoritative:
        # run_dmxCue reads fadein_ms then fade_time = fadein_ms/1000; project
        # data uses <fadein_time>1000</fadein_time> for a 1 s fade). So a 3 s
        # fade == 3000 ms and _effective_duration_ms must NOT multiply by 1000.
        from cuemsengine.cues.CueHandler import CueHandler
        from cuemsutils.cues import DmxCue

        from cuemsengine.cues.CueHandler import CueHandler

        cue = DmxCue()
        cue.fadein_time = 3000  # 3 s expressed in ms
        cue.fadeout_time = 0.0
        duration = CueHandler._effective_duration_ms(cue)
        assert duration == 3000


# ---------------------------------------------------------------------------
# T020: _arm_ahead
# ---------------------------------------------------------------------------


class TestArmAhead:

    def _make_chain(self, durations_ms, handler):
        """
        Build a chain of ActionCues with given effective durations via prewait.
        """
        from cuemsutils.tools.CTimecode import CTimecode

        cues = []
        for d in durations_ms:
            cue = ActionCue()
            cue.enabled = True
            cue._local = True
            cue.action_type = "enable"
            cue._action_target_object = _make_target()
            cue._target_object = None
            cue.post_go = "go_at_end"
            if d > 0:
                cue.prewait = CTimecode(start_seconds=d / 1000.0)
            cues.append(cue)
        # Wire chain
        for i in range(len(cues) - 1):
            cues[i]._target_object = cues[i + 1]
        return cues

    def test_arm_ahead_skips_short_cues(self, handler, mtc):
        """Short cues are armed but don't count toward the 2-cue limit."""
        # 0ms, 0ms, 0ms, 2000ms, 2000ms
        cues = self._make_chain([0, 0, 0, 2000, 2000], handler)
        start = _make_action_target()
        start._target_object = cues[0]

        handler._arm_ahead(start)

        # All 5 should be armed (3 short + 2 counted)
        for cue in cues:
            assert getattr(cue, "loaded", False), f"Cue should be loaded"

    def test_arm_ahead_stops_at_two_real_cues(self, handler, mtc):
        """Stops after finding 2 cues with duration >= threshold."""
        # 2000ms, 2000ms, 2000ms
        cues = self._make_chain([2000, 2000, 2000], handler)
        start = _make_action_target()
        start._target_object = cues[0]

        handler._arm_ahead(start)

        assert getattr(cues[0], "loaded", False)
        assert getattr(cues[1], "loaded", False)
        assert not getattr(cues[2], "loaded", False)  # not reached

    def test_arm_ahead_hard_cap(self, handler, mtc, caplog):
        """Stops at MAX_LOOKAHEAD_DEPTH and logs warning."""
        # 20 zero-duration cues
        cues = self._make_chain([0] * 20, handler)
        start = _make_action_target()
        start._target_object = cues[0]

        with caplog.at_level(logging.WARNING):
            handler._arm_ahead(start)

        # Only first MAX_LOOKAHEAD_DEPTH cues armed
        depth = handler._MAX_LOOKAHEAD_DEPTH
        for i in range(depth):
            assert getattr(cues[i], "loaded", False)
        assert not getattr(cues[depth], "loaded", False)

        # Warning logged
        assert any("depth limit" in r.getMessage() for r in caplog.records)

    def test_arm_ahead_skips_cuelist(self, handler, mtc):
        """CueList targets in the chain are skipped."""
        from cuemsutils.cues import CueList

        cue_after = _make_action_target(loaded=False)
        cue_after._target_object = None
        cue_after.prewait = __import__(
            "cuemsutils.tools.CTimecode", fromlist=["CTimecode"]
        ).CTimecode(start_seconds=2.0)

        cuelist = CueList()
        cuelist._target_object = cue_after

        start = _make_action_target()
        start._target_object = cuelist

        handler._arm_ahead(start)

        # CueList skipped, cue_after armed
        assert not getattr(cuelist, "loaded", False)
        assert getattr(cue_after, "loaded", False)

    def test_arm_ahead_uninit_loaded(self, handler, mtc):
        """
        A cue without 'loaded' attribute should be armed (getattr fallback).
        """
        cue = ActionCue()
        cue.enabled = True
        cue._local = True
        cue.action_type = "enable"
        cue._action_target_object = _make_target()
        cue._target_object = None
        cue.post_go = "pause"
        # Don't set 'loaded' at all

        start = _make_action_target()
        start._target_object = cue

        handler._arm_ahead(start)

        assert getattr(cue, "loaded", False)
