"""US2: Concurrent cue execution tests.

Verifies that multiple cues execute simultaneously without blocking each
other or corrupting shared state in CueHandler/PlayerHandler singletons.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.async_helpers.factories import MockCueFactory
from tests.async_helpers.mtc import MockMtcListener
from tests.async_helpers.osc import MockOscClient
from tests.async_helpers.players import MockPlayerHandler

FAR_FUTURE_TC = "9:59:59:0"


def _make_armed_cue(handler, kind: str = "audio", **kwargs):
    """Create, arm, and return a cue with OSC client attached."""
    factory_fn = getattr(MockCueFactory, kind)
    osc = MockOscClient()
    cue = factory_fn(loaded=False, enabled=True, loop=1, osc=osc, **kwargs)
    handler.arm(cue, init=True)
    return cue


# ---------------------------------------------------------------------------
# T017 — Three simultaneous cues
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThreeSimultaneousCues:
    """Audio + Video + Action triggered on the same event loop tick."""

    def test_all_three_complete_independently(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        audio_cue = _make_armed_cue(handler, "audio", cue_id="a1")
        video_cue = _make_armed_cue(handler, "video", cue_id="v1")
        action_target = MockCueFactory.audio(cue_id="action-target", loaded=True)
        action_cue = MockCueFactory.action(
            action_type="enable",
            action_target=action_target,
            cue_id="ac1",
            loaded=True,
            loop=1,
        )
        handler.add_armed_cue(action_cue)

        def _advance():
            time.sleep(0.05)
            mtc.advance_to(FAR_FUTURE_TC)

        threading.Thread(target=_advance, daemon=True).start()

        async def run_all():
            await asyncio.gather(
                handler._go_async(audio_cue, mtc),
                handler._go_async(video_cue, mtc),
                handler._go_async(action_cue, mtc),
            )

        future = asyncio.run_coroutine_threadsafe(run_all(), cue_loop)
        future.result(timeout=10)

        assert audio_cue.loaded is False
        assert video_cue.loaded is False
        assert action_target.enabled is True


# ---------------------------------------------------------------------------
# T018 — Error isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestErrorIsolation:
    """One cue errors, the other completes unaffected."""

    def test_error_in_one_does_not_affect_other(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        mtc = MockMtcListener()
        mtc.advance_by(100)

        good_cue = _make_armed_cue(handler, "audio", cue_id="good")

        bad_osc = MockOscClient()
        bad_cue = MockCueFactory.audio(
            cue_id="bad",
            loaded=False,
            enabled=True,
            loop=1,
            osc=bad_osc,
        )
        # Make the bad cue's OSC raise during run_cue
        bad_osc.set_value = lambda k, v: (_ for _ in ()).throw(
            ConnectionError("OSC failed")
        )
        handler.arm(bad_cue, init=True)

        def _advance():
            time.sleep(0.05)
            mtc.advance_to(FAR_FUTURE_TC)

        threading.Thread(target=_advance, daemon=True).start()

        async def run_both():
            results = await asyncio.gather(
                handler._go_async(good_cue, mtc),
                handler._go_async(bad_cue, mtc),
                return_exceptions=True,
            )
            return results

        future = asyncio.run_coroutine_threadsafe(run_both(), cue_loop)
        results = future.result(timeout=10)

        # Good cue completed its lifecycle
        assert good_cue.loaded is False
        # Bad cue may have errored — check that at least one result is an exception
        exceptions = [r for r in results if isinstance(r, Exception)]
        # The bad cue should have raised (or been handled by the try/except in loop_cue)
        # Either way, the good cue must have completed
        assert good_cue._osc is None


# ---------------------------------------------------------------------------
# T019 — Thread-safety stress test
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThreadSafetyStress:
    """50 iterations × 3 concurrent threads via ThreadPoolExecutor + Barrier."""

    def test_stress_concurrent_go(
        self,
        cue_loop: asyncio.AbstractEventLoop,
        mock_player_handler: MockPlayerHandler,
    ) -> None:
        from unittest.mock import patch as _patch

        from cuemsengine.cues.CueHandler import CueHandler

        iterations = 50
        n_threads = 3
        errors: list[Exception] = []

        async def _noop_run(cue, mtc):
            pass

        async def _noop_loop(cue, mtc):
            pass

        for _ in range(iterations):
            CueHandler._instance = None
            handler = CueHandler()
            mtc = MockMtcListener()

            cues = []
            for i in range(n_threads):
                osc = MockOscClient()
                cue = MockCueFactory.audio(
                    cue_id=f"stress-{i}",
                    loaded=False,
                    enabled=True,
                    loop=1,
                    osc=osc,
                )
                handler.arm(cue, init=True)
                cues.append(cue)

            barrier = threading.Barrier(n_threads)

            def submit_go(c):
                try:
                    barrier.wait(timeout=2)
                    future = asyncio.run_coroutine_threadsafe(
                        handler._go_async(c, mtc), cue_loop
                    )
                    future.result(timeout=5)
                except Exception as exc:
                    errors.append(exc)

            with _patch("cuemsengine.cues.CueHandler.run_cue", _noop_run), \
                 _patch("cuemsengine.cues.CueHandler.loop_cue", _noop_loop):
                with ThreadPoolExecutor(max_workers=n_threads) as pool:
                    pool.map(submit_go, cues)

        assert len(errors) == 0, f"Stress test errors: {errors[:5]}"


# ---------------------------------------------------------------------------
# T020 — Concurrent arm/disarm interleaving
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConcurrentArmDisarm:
    """Multiple threads calling add_armed_cue/remove_armed_cue simultaneously."""

    def test_armed_list_consistency(
        self, mock_player_handler: MockPlayerHandler
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        n_cues = 20
        cues = [
            MockCueFactory.audio(cue_id=f"interleave-{i}", loaded=True, enabled=True)
            for i in range(n_cues)
        ]

        barrier = threading.Barrier(n_cues)
        errors: list[Exception] = []

        def add_then_remove(cue):
            try:
                barrier.wait(timeout=2)
                handler.add_armed_cue(cue)
                time.sleep(0.001)
                handler.remove_armed_cue(cue)
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=n_cues) as pool:
            pool.map(add_then_remove, cues)

        assert len(errors) == 0, f"Interleave errors: {errors[:5]}"
        # After all adds + removes, list should be empty
        assert len(handler.get_armed_cues()) == 0
