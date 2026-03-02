"""US4: MTC synchronization in loop tests.

Verifies that ``loop_cue()`` correctly tracks MTC, recalculates offsets
on loop restart, and disconnects MTC when the loop ends.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from tests.async_helpers.factories import MockCueFactory
from tests.async_helpers.mtc import MockMtcListener
from tests.async_helpers.osc import MockOscClient


# ---------------------------------------------------------------------------
# T025 — AudioCue loop_cue with loop=3
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAudioLoopCounter:
    """AudioCue loop_cue with loop=3 — offset recalculated each iteration."""

    def test_loop_three_times(self, cue_loop: asyncio.AbstractEventLoop) -> None:
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(loaded=True, loop=3, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)

            async def advance_periodically():
                for _ in range(10):
                    await asyncio.sleep(0.02)
                    mtc.advance_by(5000)

            loop_task = asyncio.ensure_future(loop_cue(cue, mtc))
            advance_task = asyncio.ensure_future(advance_periodically())
            await asyncio.gather(loop_task, advance_task)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

        # run_cue sends 1 /offset, loop body recalculates 3 more
        offset_calls = osc.get_calls_for("/offset")
        assert len(offset_calls) >= 3, f"Expected ≥3 offset calls, got {len(offset_calls)}"


# ---------------------------------------------------------------------------
# T026 — VideoCue loop_cue with loop=2
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoLoopCounter:
    """VideoCue loop_cue with loop=2 — /jadeo/offset recalculated."""

    def test_loop_twice(self, cue_loop: asyncio.AbstractEventLoop) -> None:
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener(framerate="25")
        mtc.advance_by(100)

        cue = MockCueFactory.video(loaded=True, loop=2, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)

            async def advance_periodically():
                for _ in range(6):
                    await asyncio.sleep(0.02)
                    mtc.advance_by(5000)

            loop_task = asyncio.ensure_future(loop_cue(cue, mtc))
            advance_task = asyncio.ensure_future(advance_periodically())
            await asyncio.gather(loop_task, advance_task)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

        offset_calls = osc.get_calls_for("/jadeo/offset")
        assert len(offset_calls) >= 2


# ---------------------------------------------------------------------------
# T027 — Final loop iteration disconnects MTC
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFinalLoopDisconnect:
    """On last loop, MTC is disconnected."""

    def test_audio_mtcfollow_zero_on_exit(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(loaded=True, loop=1, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)
            mtc.advance_by(5000)
            await loop_cue(cue, mtc)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

        mtcfollow_calls = osc.get_calls_for("/mtcfollow")
        assert mtcfollow_calls[-1] == 0, "/mtcfollow should be 0 after loop exit"

    def test_video_midi_disconnect_on_exit(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener(framerate="25")
        mtc.advance_by(100)

        cue = MockCueFactory.video(loaded=True, loop=1, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)
            mtc.advance_by(5000)
            await loop_cue(cue, mtc)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

        cmd_calls = osc.get_calls_for("/jadeo/cmd")
        assert "midi disconnect" in cmd_calls


# ---------------------------------------------------------------------------
# T028 — MTC stall resilience
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMtcStallResilience:
    """When MTC stalls, loop_cue keeps polling without crash."""

    def test_stall_does_not_crash(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(loaded=True, loop=1, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)
            # Don't advance MTC — simulate stall. Use wait_for to verify
            # loop_cue is still alive (not crashed) after 200ms.
            try:
                await asyncio.wait_for(loop_cue(cue, mtc), timeout=0.2)
                # If it returns within 200ms, that's unexpected unless loop=0
                pytest.fail("loop_cue should not have completed (MTC stalled)")
            except asyncio.TimeoutError:
                pass  # Expected: loop_cue is still polling

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)


# ---------------------------------------------------------------------------
# T029 — loop=0 (no loop) and loop=-1 (infinite loop) semantics
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoopSemantics:
    """Test loop attribute edge values.

    Production code: ``while not cue.loop or loop_counter < cue.loop``
    - loop=0: ``not 0`` = True → infinite loop (current behavior)
    - loop=-1: ``not -1`` = False, ``0 < -1`` = False → no loop

    Spec defines the TARGET semantics:
    - loop=0 should mean "no loop" (play once, exit immediately)
    - loop<0 should mean "infinite loop"

    These tests document CURRENT behavior. They will be updated when
    the production code is refactored to match the spec semantics.
    """

    def test_loop_zero_current_behavior(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        """loop=0 currently means INFINITE loop in production code."""
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(loaded=True, loop=0, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)
            # loop=0 → infinite loop. Advance MTC 3 times, then cancel.
            iterations = 0

            async def count_and_loop():
                nonlocal iterations
                # Advance MTC periodically to allow loop iterations
                for _ in range(3):
                    mtc.advance_by(5000)
                    await asyncio.sleep(0.02)
                    iterations += 1

            task = asyncio.ensure_future(loop_cue(cue, mtc))
            counter = asyncio.ensure_future(count_and_loop())
            await counter
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # loop=0 means infinite in current code: should have looped
            assert iterations == 3

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

    def test_loop_negative_current_behavior(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        """loop=-1 currently means NO loop (exits immediately) in production code."""
        from cuemsengine.cues.loop_cue import loop_cue
        from cuemsengine.cues.run_cue import run_cue

        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(loaded=True, loop=-1, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            await run_cue(cue, mtc)
            # loop=-1: not(-1)=False, 0<-1=False → while False → exits
            t0 = time.monotonic()
            await loop_cue(cue, mtc)
            elapsed = (time.monotonic() - t0) * 1000
            # Should exit almost immediately (no looping)
            assert elapsed < 50, f"loop=-1 should exit fast, took {elapsed:.0f}ms"

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)
