"""FR-011/012/014: Event loop identity and isolation tests.

Verifies that cue tasks run on the correct event loop and that the
IPC loop and cue loop are isolated.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.async_helpers.assertions import assert_loop_identity
from tests.async_helpers.loops import EventLoopFixture


# ---------------------------------------------------------------------------
# T034 — go() submits to cue orchestration loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCueLoopAffinity:
    """Tasks submitted via the cue loop run on that specific loop."""

    def test_task_runs_on_cue_loop(self, cue_loop: asyncio.AbstractEventLoop) -> None:
        future = asyncio.run_coroutine_threadsafe(
            assert_loop_identity(cue_loop), cue_loop
        )
        future.result(timeout=5)


# ---------------------------------------------------------------------------
# T035 — Cross-thread submission via run_coroutine_threadsafe
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCrossThreadSubmission:
    """From main thread, coroutine runs on the cue loop, not main thread."""

    def test_cross_thread_identity(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        async def check():
            running = asyncio.get_running_loop()
            assert running is cue_loop

        future = asyncio.run_coroutine_threadsafe(check(), cue_loop)
        future.result(timeout=5)


# ---------------------------------------------------------------------------
# T036 — Loop isolation (FR-014)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoopIsolation:
    """Blocking IPC loop does not stall cue loop."""

    def test_blocked_ipc_does_not_stall_cue(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        ipc_loop: asyncio.AbstractEventLoop,
    ) -> None:
        # Block the IPC loop with a 10s sleep
        asyncio.run_coroutine_threadsafe(asyncio.sleep(10), ipc_loop)

        # Cue loop should still respond within budget
        async def quick_task():
            return "done"

        t0 = time.monotonic()
        future = asyncio.run_coroutine_threadsafe(quick_task(), cue_loop)
        result = future.result(timeout=2)
        elapsed_ms = (time.monotonic() - t0) * 1000

        assert result == "done"
        assert elapsed_ms < 100, f"Cue loop stalled: {elapsed_ms:.0f}ms"

    def test_loops_are_distinct_objects(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        ipc_loop: asyncio.AbstractEventLoop,
    ) -> None:
        assert cue_loop is not ipc_loop
        assert id(cue_loop) != id(ipc_loop)
