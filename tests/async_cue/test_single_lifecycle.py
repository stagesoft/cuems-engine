"""US1: Single cue async lifecycle tests.

Verifies that each cue type progresses through the complete async lifecycle:
arm → go → prewait → run_cue → postwait → loop_cue → disarm.

Key pattern: loop_cue polls MTC in a tight loop (asyncio.sleep(5ms)),
so tests must advance MockMtcListener from the main thread while
the coroutine runs on a background event loop.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from cuemsutils.tools.CTimecode import CTimecode

from tests.async_helpers.assertions import (
    assert_lifecycle_completed,
    assert_resources_released,
    assert_timing_budget,
)
from tests.async_helpers.factories import MockCueFactory
from tests.async_helpers.mtc import MockMtcListener
from tests.async_helpers.osc import MockOscClient
from tests.async_helpers.players import MockPlayerHandler

FAR_FUTURE_TC = "9:59:59:0"


def _advance_mtc_after(mtc: MockMtcListener, delay: float = 0.05) -> None:
    """Advance MTC past any reasonable end timecode after *delay* seconds."""
    import threading

    def _advance():
        time.sleep(delay)
        mtc.advance_to(FAR_FUTURE_TC)

    t = threading.Thread(target=_advance, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# T010 — AudioCue full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAudioCueLifecycle:
    """arm → go → prewait → run_cue → postwait → loop_cue → disarm for AudioCue."""

    def test_full_lifecycle(
        self, cue_loop: asyncio.AbstractEventLoop, mock_player_handler: MockPlayerHandler
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)
        cue = MockCueFactory.audio(loaded=False, enabled=True, loop=1, osc=osc)

        handler.arm(cue, init=True)
        assert cue.loaded is True

        _advance_mtc_after(mtc)
        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), cue_loop
        )
        future.result(timeout=5)

        assert_lifecycle_completed(cue)
        assert mock_player_handler.was_called("remove_cue_player")

    def test_osc_offset_and_mtcfollow_sent(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        """run_cue sets /offset and /mtcfollow=1; loop_cue sets /mtcfollow=0."""
        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(500)

        cue = MockCueFactory.audio(loaded=True, loop=1, osc=osc)
        cue.media.duration = "0:0:1:0"

        async def run():
            from cuemsengine.cues.loop_cue import loop_cue
            from cuemsengine.cues.run_cue import run_cue

            await run_cue(cue, mtc)
            assert cue._start_mtc is not None
            assert cue._end_mtc is not None
            mtc.advance_to(FAR_FUTURE_TC)
            await loop_cue(cue, mtc)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

        offset_calls = osc.get_calls_for("/offset")
        assert len(offset_calls) >= 1, "Expected at least one /offset call"
        mtcfollow_calls = osc.get_calls_for("/mtcfollow")
        assert 1 in mtcfollow_calls, "/mtcfollow=1 not sent"
        assert 0 in mtcfollow_calls, "/mtcfollow=0 not sent"


# ---------------------------------------------------------------------------
# T011 — VideoCue full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoCueLifecycle:
    """arm → go → prewait → run_cue → postwait → loop_cue → disarm for VideoCue."""

    def test_full_lifecycle(
        self, cue_loop: asyncio.AbstractEventLoop, mock_player_handler: MockPlayerHandler
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        osc = MockOscClient()
        mtc = MockMtcListener(framerate="25")
        mtc.advance_by(100)
        cue = MockCueFactory.video(loaded=False, enabled=True, loop=1, osc=osc)

        handler.arm(cue, init=True)
        assert cue.loaded is True

        _advance_mtc_after(mtc)
        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), cue_loop
        )
        future.result(timeout=5)

        assert_lifecycle_completed(cue)
        assert mock_player_handler.was_called("remove_cue_player")

    def test_osc_jadeo_commands_sent(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        """run_cue sends /jadeo/offset and /jadeo/cmd; loop_cue sends midi disconnect."""
        osc = MockOscClient()
        mtc = MockMtcListener(framerate="25")
        mtc.advance_by(500)

        cue = MockCueFactory.video(loaded=True, loop=1, osc=osc)
        cue.media.duration = "0:0:2:0"

        async def run():
            from cuemsengine.cues.loop_cue import loop_cue
            from cuemsengine.cues.run_cue import run_cue

            await run_cue(cue, mtc)
            assert cue._start_mtc is not None
            mtc.advance_to(FAR_FUTURE_TC)
            await loop_cue(cue, mtc)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)

        offset_calls = osc.get_calls_for("/jadeo/offset")
        assert len(offset_calls) >= 1
        cmd_calls = osc.get_calls_for("/jadeo/cmd")
        assert "midi connect Midi Through" in cmd_calls
        assert "midi disconnect" in cmd_calls


# ---------------------------------------------------------------------------
# T012 — ActionCue lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestActionCueLifecycle:
    """ActionCue dispatches to correct CueHandler method per action_type."""

    @pytest.mark.parametrize(
        "action_type,expected_method",
        [
            ("load", "arm"),
            ("unload", "disarm"),
        ],
    )
    def test_action_dispatches(
        self,
        action_type: str,
        expected_method: str,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        target = MockCueFactory.audio(cue_id="target-cue")
        cue = MockCueFactory.action(
            action_type=action_type,
            action_target=target,
            loaded=True,
            loop=1,
        )

        async def run():
            from cuemsengine.cues.run_cue import run_cue

            handler = CueHandler()
            with patch.object(handler, expected_method) as mocked:
                with patch(
                    "cuemsengine.cues.CueHandler.CUE_HANDLER", handler
                ):
                    await run_cue(cue, MockMtcListener())
                    mocked.assert_called_once()

        asyncio.run(run())

    def test_enable_action(self) -> None:
        target = MagicMock()
        target.enabled = False
        cue = MockCueFactory.action(
            action_type="enable", action_target=target, loaded=True, loop=1
        )

        async def run():
            from cuemsengine.cues.run_cue import run_cue

            await run_cue(cue, MockMtcListener())

        asyncio.run(run())
        assert target.enabled is True

    def test_disable_action(self) -> None:
        target = MagicMock()
        target.enabled = True
        cue = MockCueFactory.action(
            action_type="disable", action_target=target, loaded=True, loop=1
        )

        async def run():
            from cuemsengine.cues.run_cue import run_cue

            await run_cue(cue, MockMtcListener())

        asyncio.run(run())
        assert target.enabled is False


# ---------------------------------------------------------------------------
# T012b — CueList lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCueListLifecycle:
    """CueList.run_cue triggers go() on first child in contents."""

    def test_cuelist_triggers_first_child(
        self, mock_player_handler: MockPlayerHandler
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        child = MockCueFactory.audio(cue_id="child-01", loaded=True)
        cue = MockCueFactory.cuelist(contents=[child], loaded=True, loop=1)
        mtc = MockMtcListener()

        async def run():
            from cuemsengine.cues.run_cue import run_cue

            handler = CueHandler()
            with patch.object(handler, "go") as mock_go:
                with patch(
                    "cuemsengine.cues.CueHandler.CUE_HANDLER", handler
                ):
                    await run_cue(cue, mtc)
                    mock_go.assert_called_once_with(child, mtc)

        asyncio.run(run())


# ---------------------------------------------------------------------------
# T013 — Prewait enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrewaitEnforcement:
    """run_cue is not invoked until at least prewait ms have elapsed."""

    def test_prewait_delays_execution(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        prewait = CTimecode(start_seconds=0.1)
        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.video(
            loaded=True,
            enabled=True,
            loop=1,
            prewait=prewait,
            osc=osc,
        )
        cue.media.duration = "0:0:1:0"

        _advance_mtc_after(mtc, delay=0.15)

        async def run():
            t0 = time.monotonic()
            await handler._go_async(cue, mtc)
            elapsed_ms = (time.monotonic() - t0) * 1000
            assert elapsed_ms >= 90, f"Prewait not respected: {elapsed_ms:.0f}ms"

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)


# ---------------------------------------------------------------------------
# T014 — Postwait enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostwaitEnforcement:
    """loop_cue is not called until at least postwait ms after run_cue."""

    def test_postwait_delays_loop(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        postwait = CTimecode(start_seconds=0.05)
        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(
            loaded=True,
            enabled=True,
            loop=1,
            postwait=postwait,
            osc=osc,
        )
        cue.media.duration = "0:0:1:0"

        _advance_mtc_after(mtc, delay=0.1)

        async def run():
            t0 = time.monotonic()
            await handler._go_async(cue, mtc)
            elapsed_ms = (time.monotonic() - t0) * 1000
            assert elapsed_ms >= 40, f"Postwait not respected: {elapsed_ms:.0f}ms"

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)


# ---------------------------------------------------------------------------
# T015 — Disarm cleanup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDisarmCleanup:
    """After lifecycle completes, resources are released."""

    def test_cleanup_after_lifecycle(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(loaded=False, enabled=True, loop=1, osc=osc)

        handler.arm(cue, init=True)
        assert cue.loaded is True

        _advance_mtc_after(mtc)
        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue, mtc), cue_loop
        )
        future.result(timeout=5)

        assert cue.loaded is False
        assert cue._osc is None
        assert mock_player_handler.was_called("remove_cue_player")
        assert_resources_released(cue, mock_player_handler)


# ---------------------------------------------------------------------------
# T016 — Timing budget
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTimingBudget:
    """Full lifecycle with zero prewait/postwait completes within budget."""

    def test_lifecycle_within_budget(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        osc = MockOscClient()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue = MockCueFactory.audio(loaded=False, enabled=True, loop=1, osc=osc)

        handler.arm(cue, init=True)

        _advance_mtc_after(mtc, delay=0.01)

        async def run():
            t0 = time.monotonic()
            await handler._go_async(cue, mtc)
            elapsed_ms = (time.monotonic() - t0) * 1000
            # Budget allows up to 100ms for the loop_cue polling + MTC advance delay
            assert_timing_budget(elapsed_ms, 100.0)

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=5)
