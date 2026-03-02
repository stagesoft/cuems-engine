"""FR-013: CueHandler.wait_for_cue — missing method tests.

Exposes the currently undefined ``wait_for_cue`` method as a test failure.
``NodeEngine.go_script()`` calls ``CUE_HANDLER.wait_for_cue(main_thread)``
but the method does not exist yet.
"""

from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# T037 — wait_for_cue does not exist
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWaitForCueMissing:
    """CueHandler.wait_for_cue() should raise AttributeError until implemented."""

    def test_attribute_error(self) -> None:
        """Verify wait_for_cue is not defined on CueHandler.

        Expected signature (from NodeEngine.go_script call site)::

            def wait_for_cue(self, task: asyncio.Task) -> None:
                '''Block the calling thread until the cue task completes.'''
        """
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()

        with pytest.raises(AttributeError):
            handler.wait_for_cue("dummy_task")


# ---------------------------------------------------------------------------
# T038 — Expected wait_for_cue contract (xfail)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.xfail(reason="wait_for_cue not yet implemented", strict=True)
class TestWaitForCueContract:
    """Spec test that will pass once wait_for_cue is implemented."""

    def test_blocks_until_task_completes(
        self, cue_loop: asyncio.AbstractEventLoop
    ) -> None:
        from cuemsengine.cues.CueHandler import CueHandler

        handler = CueHandler()
        result_holder: list[str] = []

        async def slow_task():
            await asyncio.sleep(0.1)
            result_holder.append("completed")

        future = asyncio.run_coroutine_threadsafe(slow_task(), cue_loop)
        task = asyncio.wrap_future(future)

        # This should block until the task completes
        handler.wait_for_cue(task)
        assert result_holder == ["completed"]
