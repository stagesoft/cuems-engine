"""Controllable MTC time source for tests — no MIDI hardware required."""

from __future__ import annotations

from cuemsutils.tools.CTimecode import CTimecode


class MockMtcListener:
    """Simulates ``MtcListener`` with programmatically advancing timecode.

    Attributes:
        main_tc: Current timecode, readable the same way production code
            accesses ``mtc.main_tc``.
    """

    def __init__(
        self,
        initial_tc: str = "0:0:0:0",
        framerate: str = "1000",
    ) -> None:
        self.main_tc = CTimecode(initial_tc, framerate=framerate)
        self._framerate = framerate

    def advance_to(self, tc_string: str) -> None:
        """Set the current timecode to *tc_string*."""
        self.main_tc = CTimecode(tc_string, framerate=self._framerate)

    def advance_by(self, milliseconds: int) -> None:
        """Advance the current timecode by *milliseconds* ms.

        Uses the internal framerate to convert milliseconds into the
        equivalent frame count so that ``main_tc.milliseconds`` matches
        the expected value at frame boundaries.
        """
        delta = CTimecode(start_seconds=milliseconds / 1000)
        if self._framerate != "1000":
            delta = delta.return_in_other_framerate(self._framerate)
        self.main_tc = self.main_tc + delta
