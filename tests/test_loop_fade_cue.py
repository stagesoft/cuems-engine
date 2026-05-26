# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Unit tests for loop_fadeCue (Phase 6).

Per FR-019: a FadeCue MUST occupy the cue runner for its `duration` so general
cue lifecycle (auto-disarm of the FadeCue itself) fires only after gradient-motiond
finishes. loop_fadeCue blocks until mtc.main_tc.milliseconds_rounded >= cue._end_mtc.milliseconds_rounded.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from cuemsutils.cues.FadeCue import FadeCue


def _make_fade_cue() -> FadeCue:
    cue = FadeCue(
        {
            "action_target": "some-target-uuid",
            "target_value": 80,
            "duration": "0:0:0:1",
            "curve_type": "linear",
        }
    )
    return cue


class _AdvancingMtc:
    """Mock MTC whose .main_tc.milliseconds_rounded advances over wall time."""

    def __init__(self, start_ms: int, ms_per_second: float = 1000.0):
        self._start_wall = time.monotonic()
        self._start_ms = start_ms
        self._rate = ms_per_second
        self.main_tc = self  # so mtc.main_tc.milliseconds_rounded works

    @property
    def milliseconds_rounded(self) -> int:
        return int(self._start_ms + (time.monotonic() - self._start_wall) * self._rate)


def test_fade_cue_registered_in_loop_cue_dispatch():
    """FadeCue must have its own loop_cue branch (not inherit no-op ActionCue)."""
    from cuemsengine.cues.loop_cue import loop_cue

    registry = loop_cue.registry
    assert FadeCue in registry, (
        "FadeCue must be registered in loop_cue singledispatch — "
        "without it, FadeCue inherits the no-op loop_actionCue and would not "
        "occupy the cue runner for its duration."
    )


def test_loop_fade_cue_blocks_until_end_mtc():
    """loop_fadeCue MUST block until mtc.main_tc.milliseconds_rounded >= cue._end_mtc.milliseconds_rounded."""
    from cuemsengine.cues.loop_cue import loop_cue

    cue = _make_fade_cue()
    cue._stop_requested = False
    end_mtc = MagicMock()
    end_mtc.milliseconds_rounded = 200
    cue._end_mtc = end_mtc

    mtc = _AdvancingMtc(start_ms=0, ms_per_second=1000.0)

    t0 = time.monotonic()
    loop_cue(cue, mtc)
    elapsed = time.monotonic() - t0

    # Should block ~0.2s (200ms of MTC at 1000ms/sec wall rate). Allow generous slack.
    assert elapsed >= 0.15, f"loop_fadeCue returned too quickly: {elapsed}s"
    assert elapsed < 1.0, f"loop_fadeCue blocked too long: {elapsed}s"


def test_loop_fade_cue_returns_early_on_stop_requested():
    """loop_fadeCue MUST return promptly when cue._stop_requested becomes True."""
    from cuemsengine.cues.loop_cue import loop_cue

    cue = _make_fade_cue()
    cue._stop_requested = False
    end_mtc = MagicMock()
    end_mtc.milliseconds_rounded = 10_000  # 10 seconds — would block forever otherwise
    cue._end_mtc = end_mtc

    mtc = _AdvancingMtc(start_ms=0, ms_per_second=1.0)  # MTC barely advances

    def trigger_stop():
        time.sleep(0.1)
        cue._stop_requested = True

    threading.Thread(target=trigger_stop, daemon=True).start()

    t0 = time.monotonic()
    loop_cue(cue, mtc)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.5, f"loop_fadeCue did not respect _stop_requested: {elapsed}s"


def test_loop_fade_cue_no_end_mtc_returns_immediately():
    """If _end_mtc is missing (defensive), loop_fadeCue must not loop forever."""
    from cuemsengine.cues.loop_cue import loop_cue

    cue = _make_fade_cue()
    cue._stop_requested = False
    # No _end_mtc attribute set (simulating a bug upstream)

    mtc = _AdvancingMtc(start_ms=0, ms_per_second=1000.0)

    t0 = time.monotonic()
    loop_cue(cue, mtc)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.2, "loop_fadeCue without _end_mtc must return immediately"
