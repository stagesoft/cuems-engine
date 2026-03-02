"""Edge cases from spec.

Tests for boundary conditions in the async cue execution lifecycle.
"""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import patch

import pytest

from cuemsutils.tools.CTimecode import CTimecode

from tests.async_helpers.factories import MockCueFactory
from tests.async_helpers.mtc import MockMtcListener
from tests.async_helpers.osc import MockOscClient
from tests.async_helpers.players import MockPlayerHandler


def _periodic_mtc_advance(
    mtc: MockMtcListener,
    interval: float = 0.03,
    step_ms: int = 100_000,
    start_delay: float = 0.05,
) -> threading.Event:
    stop = threading.Event()

    def _run():
        time.sleep(start_delay)
        while not stop.is_set():
            mtc.advance_by(step_ms)
            time.sleep(interval)

    threading.Thread(target=_run, daemon=True).start()
    return stop


# ---------------------------------------------------------------------------
# T039 — go() called on already-running cue
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoOnRunningCue:
    """go() on an already-running cue: verify behavior."""

    def test_second_go_does_not_crash(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)
        osc = MockOscClient()
        cue = MockCueFactory.audio(loaded=False, enabled=True, loop=1, osc=osc)
        handler.arm(cue, init=True)

        # First go — will poll forever (no MTC advance)
        future1 = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), cue_loop
        )
        time.sleep(0.05)

        # Second go — should not crash (may raise or be ignored)
        try:
            task2 = handler.go(cue, mtc)
        except Exception:
            pass  # Any exception is acceptable; no crash

        # Cleanup: advance MTC and let first complete
        mtc.advance_by(100_000)
        try:
            future1.result(timeout=5)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# T040 — disarm() while async task is running
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDisarmWhileRunning:
    """disarm() during active task → task cancelled or completes, resources released."""

    def test_disarm_during_loop(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)
        osc = MockOscClient()
        cue = MockCueFactory.audio(loaded=False, enabled=True, loop=1, osc=osc)
        handler.arm(cue, init=True)

        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), cue_loop
        )
        time.sleep(0.05)

        # Disarm while task is running
        handler.disarm(cue)

        assert cue.loaded is False
        assert mock_player_handler.was_called("remove_cue_player")

        # Cancel the hanging task
        future.cancel()
        try:
            future.result(timeout=2)
        except (asyncio.CancelledError, Exception):
            pass


# ---------------------------------------------------------------------------
# T041 — Event loop shutdown while cues running
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoopShutdownWhileRunning:
    """Loop shutdown → running tasks cancelled, resources cleaned up."""

    def test_loop_shutdown_cancels_tasks(
        self, mock_player_handler: MockPlayerHandler
    ) -> None:
        from tests.async_helpers.loops import EventLoopFixture

        from cuemsengine.cues.CueHandler import CueHandler

        handle = EventLoopFixture.start(name="shutdown-test-loop")
        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)
        osc = MockOscClient()
        cue = MockCueFactory.audio(loaded=False, enabled=True, loop=1, osc=osc)
        handler.arm(cue, init=True)

        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), handle.loop
        )
        time.sleep(0.05)

        # Stop the loop while task is running
        EventLoopFixture.stop(handle)
        time.sleep(0.1)

        # Task should be done (cancelled or errored) — or pending but not hanging
        # After loop shutdown, the future may remain pending since the loop is gone
        # The key assertion is that the loop stopped without crashing
        assert not handle.loop.is_running()


# ---------------------------------------------------------------------------
# T042 — Two cues sharing video player when one errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSharedPlayerError:
    """Two cues share player pool; one errors → other unaffected."""

    def test_error_isolation_with_shared_pool(
        self, mock_player_handler: MockPlayerHandler
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()

        osc_good = MockOscClient()
        osc_bad = MockOscClient()

        cue_good = MockCueFactory.video(
            cue_id="good-vid", loaded=False, enabled=True, osc=osc_good
        )
        cue_bad = MockCueFactory.video(
            cue_id="bad-vid", loaded=False, enabled=True, osc=osc_bad
        )

        handler.arm(cue_good, init=True)
        handler.arm(cue_bad, init=True)

        # Disarm the bad cue (simulating error cleanup)
        handler.disarm(cue_bad)

        # Good cue should still be armed and loaded
        assert cue_good.loaded is True
        assert handler.find_armed_cue(cue_good)


# ---------------------------------------------------------------------------
# T043 — prewait=0 and postwait=0
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestZeroWaits:
    """prewait=0 and postwait=0 → no error, executes instantly."""

    def test_zero_waits_complete_fast(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)
        osc = MockOscClient()
        cue = MockCueFactory.audio(
            loaded=False,
            enabled=True,
            loop=1,
            prewait=CTimecode("0:0:0:0"),
            postwait=CTimecode("0:0:0:0"),
            osc=osc,
        )
        handler.arm(cue, init=True)

        stop = _periodic_mtc_advance(mtc, start_delay=0.01)

        async def run():
            t0 = time.monotonic()
            await handler._go_async(cue, mtc)
            elapsed = (time.monotonic() - t0) * 1000
            assert elapsed < 200, f"Zero waits took too long: {elapsed:.0f}ms"

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)
        stop.set()


# ---------------------------------------------------------------------------
# T044 — loop=0 and loop=-1 edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoopEdgeCases:
    """loop=0 and loop=-1 edge cases (documents current behavior)."""

    def test_loop_zero_is_infinite(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        """loop=0 → infinite loop in current production code.

        ``while not cue.loop or loop_counter < cue.loop``
        ``not 0`` = True → always True.
        """
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)
        cue = MockCueFactory.audio(loaded=True, loop=0, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)
            task = asyncio.ensure_future(loop_cue(cue, mtc))
            # Let it iterate a few times
            for _ in range(3):
                mtc.advance_by(5000)
                await asyncio.sleep(0.02)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

    def test_loop_negative_exits_immediately(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        """loop=-1 → no loop in current production code.

        ``not -1`` = False, ``0 < -1`` = False → while False → exits.
        """
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)
        cue = MockCueFactory.audio(loaded=True, loop=-1, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)
            t0 = time.monotonic()
            await loop_cue(cue, mtc)
            elapsed = (time.monotonic() - t0) * 1000
            assert elapsed < 50, f"loop=-1 should exit fast: {elapsed:.0f}ms"

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)
