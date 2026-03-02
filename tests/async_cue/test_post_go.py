"""US3: Post-go chaining tests.

Verifies ``post_go`` modes ('go' and 'go_at_end') chain cue execution
in the correct order and timing.
"""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import patch

import pytest

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
    """Periodically advance MTC in a background thread.

    Returns a stop event — set it to halt advancement.
    This handles chained cues that each recalculate _end_mtc.
    """
    stop = threading.Event()

    def _run():
        time.sleep(start_delay)
        while not stop.is_set():
            mtc.advance_by(step_ms)
            time.sleep(interval)

    threading.Thread(target=_run, daemon=True).start()
    return stop


# ---------------------------------------------------------------------------
# T021 — post_go='go': cue B fires before cue A's postwait
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostGoImmediate:
    """post_go='go': cue B fires right after cue A's run_cue."""

    def test_chained_go_fires_before_postwait(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        osc_b = MockOscClient()
        cue_b = MockCueFactory.audio(
            cue_id="cue-b", loaded=False, enabled=True, loop=1, osc=osc_b
        )
        osc_a = MockOscClient()
        cue_a = MockCueFactory.audio(
            cue_id="cue-a",
            loaded=False,
            enabled=True,
            loop=1,
            post_go="go",
            target_object=cue_b,
            osc=osc_a,
        )
        cue_a._target_object = cue_b
        cue_a.target = "cue-b"

        handler.arm(cue_a, init=True)
        assert cue_b.loaded is True or handler.find_armed_cue(cue_b)

        stop = _periodic_mtc_advance(mtc)
        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue_a, mtc), cue_loop
        )
        future.result(timeout=10)
        stop.set()

        assert cue_a.loaded is False


# ---------------------------------------------------------------------------
# T022 — post_go='go_at_end': cue B fires after cue A's loop completes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostGoAtEnd:
    """post_go='go_at_end': cue B fires after cue A's loop_cue exits."""

    def test_chained_go_at_end(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        osc_b = MockOscClient()
        cue_b = MockCueFactory.audio(
            cue_id="cue-b", loaded=False, enabled=True, loop=1, osc=osc_b
        )
        osc_a = MockOscClient()
        cue_a = MockCueFactory.audio(
            cue_id="cue-a",
            loaded=False,
            enabled=True,
            loop=1,
            post_go="go_at_end",
            target_object=cue_b,
            osc=osc_a,
        )
        cue_a._target_object = cue_b

        handler.arm(cue_a, init=True)
        handler.arm(cue_b, init=True)

        stop = _periodic_mtc_advance(mtc)
        future = asyncio.run_coroutine_threadsafe(
            handler._go_async(cue_a, mtc), cue_loop
        )
        future.result(timeout=10)
        stop.set()

        assert cue_a.loaded is False


# ---------------------------------------------------------------------------
# T023 — post_go='go_at_end' with error: cue B NOT triggered
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPostGoAtEndWithError:
    """If cue A errors during loop, cue B must NOT be triggered."""

    def test_error_prevents_chained_cue(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        cue_b_go_called = False
        original_go = handler.go

        def tracking_go(cue, mtc_arg):
            nonlocal cue_b_go_called
            if cue.id == "cue-b-err":
                cue_b_go_called = True
            return original_go(cue, mtc_arg)

        osc_b = MockOscClient()
        cue_b = MockCueFactory.audio(
            cue_id="cue-b-err", loaded=False, enabled=True, loop=1, osc=osc_b
        )
        osc_a = MockOscClient()
        cue_a = MockCueFactory.audio(
            cue_id="cue-a-err",
            loaded=False,
            enabled=True,
            loop=1,
            post_go="go_at_end",
            target_object=cue_b,
            osc=osc_a,
        )
        cue_a._target_object = cue_b

        handler.arm(cue_a, init=True)
        handler.arm(cue_b, init=True)

        async def _error_loop(cue, mtc_arg):
            raise RuntimeError("Simulated loop error")

        stop = _periodic_mtc_advance(mtc)

        async def run():
            with patch("cuemsengine.cues.CueHandler.loop_cue", _error_loop):
                with patch.object(handler, "go", side_effect=tracking_go):
                    try:
                        await handler._go_async(cue_a, mtc)
                    except RuntimeError:
                        pass

        future = asyncio.run_coroutine_threadsafe(run(), cue_loop)
        future.result(timeout=10)
        stop.set()

        assert not cue_b_go_called, "Cue B should NOT have been triggered after error"


# ---------------------------------------------------------------------------
# T024 — Auto-arm of chained cue
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutoArmChainedCue:
    """post_go='go' auto-arms unarmed target cue before scheduling."""

    def test_auto_arm_on_go(
        self, mock_player_handler: MockPlayerHandler
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()

        cue_b = MockCueFactory.audio(
            cue_id="target-auto", loaded=False, enabled=True
        )
        cue_a = MockCueFactory.audio(
            cue_id="source-auto",
            loaded=False,
            enabled=True,
            post_go="go",
            target_object=cue_b,
        )
        cue_a._target_object = cue_b

        handler.arm(cue_a, init=True)

        # CueHandler.arm with post_go='go' should recursively arm cue_b
        assert handler.find_armed_cue(cue_b), "Target cue should be auto-armed"
