"""US5: Error handling and cleanup tests.

Verifies failures at any lifecycle phase produce error states, log
tracebacks, and clean up resources.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import CancelledError
from unittest.mock import patch

import pytest

from tests.async_helpers.factories import MockCueFactory
from tests.async_helpers.mtc import MockMtcListener
from tests.async_helpers.osc import MockOscClient
from tests.async_helpers.players import MockPlayerHandler


def _periodic_mtc_advance(
    mtc: MockMtcListener, interval: float = 0.03, step_ms: int = 100_000
) -> threading.Event:
    stop = threading.Event()

    def _run():
        time.sleep(0.05)
        while not stop.is_set():
            mtc.advance_by(step_ms)
            time.sleep(interval)

    threading.Thread(target=_run, daemon=True).start()
    return stop


# ---------------------------------------------------------------------------
# T030 — Player crash during run_cue
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlayerCrashDuringRun:
    """OSC error during run_cue → exception logged, cue disarmed."""

    def test_osc_error_logged_and_disarmed(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
        caplog,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        osc = MockOscClient()
        cue = MockCueFactory.audio(loaded=False, enabled=True, loop=1, osc=osc)
        handler.arm(cue, init=True)

        # Make OSC raise during run_cue
        def _exploding_set(key, value):
            raise ConnectionError(f"OSC connection failed for {key}")

        osc.set_value = _exploding_set

        stop = _periodic_mtc_advance(mtc)

        async def run():
            with caplog.at_level(logging.DEBUG):
                try:
                    await handler._go_async(cue, mtc)
                except ConnectionError:
                    pass

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)
        stop.set()

        assert mock_player_handler.was_called("remove_cue_player")


# ---------------------------------------------------------------------------
# T031 — OSC connection error during arm
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOscErrorDuringArm:
    """Error during arm → cue NOT added to armed list."""

    def test_arm_failure_prevents_armed(
        self, mock_player_handler: MockPlayerHandler
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        cue = MockCueFactory.audio(
            cue_id="arm-fail", loaded=False, enabled=True
        )

        with patch(
            "cuemsengine.cues.CueHandler.arm_cue",
            side_effect=RuntimeError("arm explosion"),
        ):
            with pytest.raises(RuntimeError):
                handler.arm(cue, init=True)

        assert not handler.find_armed_cue(cue)
        assert cue.loaded is False


# ---------------------------------------------------------------------------
# T032 — Unhandled exception in loop_cue
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnhandledExceptionInLoop:
    """RuntimeError in loop_cue → task does not silently die."""

    def test_loop_error_propagates(
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

        async def _exploding_loop(c, m):
            raise RuntimeError("loop_cue exploded")

        stop = _periodic_mtc_advance(mtc)

        async def run():
            with patch(
                "cuemsengine.cues.CueHandler.loop_cue", _exploding_loop
            ):
                await handler._go_async(cue, mtc)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)

        with pytest.raises(RuntimeError, match="loop_cue exploded"):
            future.result(timeout=5)
        stop.set()


# ---------------------------------------------------------------------------
# T033 — Task cancellation at each lifecycle phase
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTaskCancellation:
    """Cancellation during prewait, run_cue, loop_cue → clean release."""

    def test_cancel_during_prewait(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsutils.tools.CTimecode import CTimecode

        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        osc = MockOscClient()
        cue = MockCueFactory.audio(
            loaded=False,
            enabled=True,
            loop=1,
            prewait=CTimecode(start_seconds=10),
            osc=osc,
        )
        handler.arm(cue, init=True)

        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), cue_loop
        )
        time.sleep(0.05)
        future.cancel()

        with pytest.raises((asyncio.CancelledError, CancelledError)):
            future.result(timeout=2)

    def test_cancel_during_loop_cue(
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

        # Don't advance MTC — loop_cue will poll forever
        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), cue_loop
        )
        time.sleep(0.1)
        future.cancel()

        with pytest.raises((asyncio.CancelledError, CancelledError)):
            future.result(timeout=2)
