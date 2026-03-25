"""Unit tests for ActionCue execution through CueHandler.

Tests cover all supported cue-level actions (FR-002a), idempotency (FR-004),
non-target isolation (FR-006), rapid succession, and invalid-action safety (US2).
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, PropertyMock, patch

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

    We patch the singleton so each test gets isolated state.
    """
    from cuemsengine.cues.CueHandler import CueHandler

    h = object.__new__(CueHandler)
    h._armed_cues = []
    h._armed_cues_set = set()
    h._video_players = {}
    h._front_video_player = None
    h._lock = __import__("threading").Lock()
    h.communications_thread = MagicMock()
    return h


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

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "stop"
        assert target._stop_requested is True
        assert target._go_generation == 2


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
# T011: fade-in — target ramps into active state
# ---------------------------------------------------------------------------


class TestFadeInAction:
    def test_fade_in_starts_target(self, handler, mtc):
        target = _make_target()
        cue = _make_action_cue("fade-in", target)

        with patch.object(handler, "go") as mock_go, patch.object(handler, "arm"):
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "fade-in"
        mock_go.assert_called_once()


# ---------------------------------------------------------------------------
# T012: fade-out — target ramps down and exits active state
# ---------------------------------------------------------------------------


class TestFadeOutAction:
    def test_fade_out_stops_target(self, handler, mtc):
        target = _make_target(_stop_requested=False, _go_generation=0)
        cue = _make_action_cue("fade-out", target)

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "fade-out"
        assert target._stop_requested is True
        assert target._go_generation == 1


# ---------------------------------------------------------------------------
# T013: go-to — execution pointer navigates to target cue
# ---------------------------------------------------------------------------


class TestGoToAction:
    def test_go_to_arms_target(self, handler, mtc):
        target = _make_target(loaded=False)
        cue = _make_action_cue("go-to", target)

        with patch.object(handler, "arm") as mock_arm:
            result = handler.execute_action(cue, mtc)

        assert result["status"] == "applied"
        assert result["action_type"] == "go-to"
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

        with patch.object(handler, "go"), patch.object(handler, "arm"):
            for _ in range(20):
                handler.execute_action(_make_action_cue("stop", target), mtc)
                target._stop_requested = False
                handler.execute_action(_make_action_cue("play", target), mtc)

        assert target._stop_requested is False


# ===========================================================================
# US2: Invalid / unsupported actions
# ===========================================================================

# ---------------------------------------------------------------------------
# T026: unknown action_type — rejected with no state mutation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# T027: missing _action_target_object — rejected safely
# ---------------------------------------------------------------------------


class TestMissingTarget:
    def test_missing_target_rejected(self, handler, mtc):
        cue = ActionCue()
        cue.action_type = "play"
        cue._action_target_object = None

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "rejected"
        assert "Missing target" in result["reason"]


# ---------------------------------------------------------------------------
# T028: action targeting cue from inactive project — rejected safely
# ---------------------------------------------------------------------------


class TestInactiveProjectTarget:
    def test_inactive_project_target_rejected(self, handler, mtc):
        cue = ActionCue()
        cue.action_type = "play"
        cue.action_target = "nonexistent-uuid"
        cue._action_target_object = None

        result = handler.execute_action(cue, mtc)

        assert result["status"] == "rejected"
