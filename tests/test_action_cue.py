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

    ``ACTION_HANDLER`` is bound to this instance so ``arm`` / ``go`` patches apply.
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

        with patch.object(handler, "go") as mock_go, patch.object(handler, "arm"):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "play"
        mock_go.assert_called_once()
        assert target._stop_requested is False

    def test_play_disabled_target_fails(self, handler, mtc):
        target = _make_target(enabled=False)
        cue = _make_action_cue("play", target)

        with patch.object(handler, "go") as mock_go, patch.object(handler, "arm"):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "failed"
        assert "disabled" in result["reason"]
        mock_go.assert_not_called()


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

        with patch.object(handler, "go") as mock_go, patch.object(handler, "arm"):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "fade_in"
        mock_go.assert_called_once()


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

        with patch.object(handler, "arm") as mock_arm:
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "go_to"
        mock_arm.assert_called_once()


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

        with patch.object(handler, "go"), patch.object(handler, "arm"), \
             patch.object(handler, "disarm"):
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
        ACTION_HANDLER.register_action_hook("after_dispatch", after, source="cue_layer")
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

    def test_default_path_calls_send_operation_when_sink_unset(self, handler, mtc):
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
    def test_before_dispatch_raises_failed_and_isolates_other_cues(self, handler, mtc):
        from cuemsengine.cues.ActionHandler import ACTION_HANDLER

        def boom(ctx):
            raise RuntimeError("hook boom")

        ACTION_HANDLER.register_action_hook("before_dispatch", boom, source="cue_layer")
        target = _make_target(enabled=True)
        bystander = _make_target(enabled=True, _stop_requested=False)
        snap = (
            bystander.enabled,
            bystander._stop_requested,
            getattr(bystander, "_go_generation", 0),
        )

        result = handler.execute_action(_make_action_cue("disable", target), mtc)

        assert result["status"] == "failed"
        assert target.enabled is True
        assert (
            bystander.enabled,
            bystander._stop_requested,
            getattr(bystander, "_go_generation", 0),
        ) == snap


class TestActionMidTransitionWithHook:
    def test_pause_while_already_paused_deterministic_with_hook(self, handler, mtc):
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
    """NFR-003 / SC-008: operator-visible rejection wording for unknown actions."""
    target = _make_target()
    with caplog.at_level(logging.WARNING):
        handler.execute_action(_make_action_cue("explode", target), mtc)
    assert any("Unsupported action_type" in r.getMessage() for r in caplog.records)
