"""Shared fixtures for async cue execution tests.

Composes reusable components from ``tests.async_helpers`` into pytest fixtures
with automatic cleanup.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# pyossia is a C extension that may not be available in the test environment.
# Mock it before any cuemsengine import triggers the chain.
if "pyossia" not in sys.modules:
    _pyossia_mock = MagicMock()
    for _mod in ("pyossia", "pyossia.ossia", "pyossia.ossia_python"):
        sys.modules[_mod] = _pyossia_mock

from tests.async_helpers.factories import MockCueFactory
from tests.async_helpers.loops import EventLoopFixture
from tests.async_helpers.mtc import MockMtcListener
from tests.async_helpers.osc import MockOscClient
from tests.async_helpers.players import MockPlayerHandler


# ---------------------------------------------------------------------------
# Singleton reset (autouse) — prevents cross-test contamination
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset CueHandler and PlayerHandler singletons between tests."""
    from cuemsengine.cues.CueHandler import CueHandler
    from cuemsengine.players.PlayerHandler import PlayerHandler

    yield

    CueHandler._instance = None
    PlayerHandler._instance = None


# ---------------------------------------------------------------------------
# Mock cue fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_audio_cue():
    """A ready-to-use AudioCue mock."""
    return MockCueFactory.audio()


@pytest.fixture
def mock_video_cue():
    """A ready-to-use VideoCue mock."""
    return MockCueFactory.video()


@pytest.fixture
def mock_action_cue():
    """A ready-to-use ActionCue mock."""
    return MockCueFactory.action()


@pytest.fixture
def mock_cuelist_cue():
    """A ready-to-use CueList mock with one child audio cue."""
    child = MockCueFactory.audio(cue_id="child-audio-01")
    return MockCueFactory.cuelist(contents=[child])


# ---------------------------------------------------------------------------
# Event loop fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cue_loop():
    """A background asyncio event loop for cue orchestration."""
    handle = EventLoopFixture.start(name="test-cue-loop")
    yield handle.loop
    EventLoopFixture.stop(handle)


@pytest.fixture
def ipc_loop():
    """A second background asyncio event loop for isolation tests."""
    handle = EventLoopFixture.start(name="test-ipc-loop")
    yield handle.loop
    EventLoopFixture.stop(handle)


# ---------------------------------------------------------------------------
# Mock infrastructure fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mtc():
    """A controllable MTC time source."""
    return MockMtcListener()


@pytest.fixture
def mock_osc():
    """A recording OSC client."""
    return MockOscClient()


@pytest.fixture
def mock_player_handler():
    """A stub PlayerHandler — patches the singleton globally."""
    handler = MockPlayerHandler()
    with patch(
        "cuemsengine.players.PlayerHandler.PLAYER_HANDLER", handler
    ), patch(
        "cuemsengine.cues.CueHandler.PLAYER_HANDLER", handler
    ), patch(
        "cuemsengine.cues.arm_cue.PLAYER_HANDLER", handler
    ):
        yield handler
