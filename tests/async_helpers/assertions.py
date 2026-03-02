"""Reusable assertion helpers for async cue lifecycle tests."""

from __future__ import annotations

import asyncio
from typing import Any


def assert_lifecycle_completed(cue: Any) -> None:
    """Verify that a cue has returned to idle after a full lifecycle.

    Checks:
      - ``cue.loaded`` is ``False``
    """
    assert cue.loaded is False, (
        f"Cue {cue.id} still loaded after lifecycle completion"
    )


def assert_timing_budget(elapsed_ms: float, budget_ms: float) -> None:
    """Assert *elapsed_ms* is within the allowed *budget_ms*."""
    assert elapsed_ms <= budget_ms, (
        f"Timing budget exceeded: {elapsed_ms:.1f} ms > {budget_ms:.1f} ms"
    )


def assert_resources_released(cue: Any, player_handler: Any) -> None:
    """Verify no leaked players or OSC clients after disarm.

    Args:
        cue: The cue under test.
        player_handler: The ``MockPlayerHandler`` instance.
    """
    assert cue._osc is None, f"Cue {cue.id} still has an OSC client"
    assert not player_handler.has_player(cue), (
        f"PlayerHandler still holds a player for cue {cue.id}"
    )


async def assert_loop_identity(
    expected_loop: asyncio.AbstractEventLoop,
) -> None:
    """Coroutine that verifies it runs on *expected_loop*.

    Designed to be submitted via ``run_coroutine_threadsafe`` or
    ``loop.create_task`` and will raise ``AssertionError`` if the
    running loop differs.
    """
    running = asyncio.get_running_loop()
    assert running is expected_loop, (
        f"Task running on wrong loop: expected {id(expected_loop)}, "
        f"got {id(running)}"
    )
