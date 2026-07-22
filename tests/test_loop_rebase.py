# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Regression test for engine loop-period drift.

Exercises the exact `_start_mtc`/`_end_mtc` rebase arithmetic used inside
`loop_audioCue` and `loop_videoCue` when a cue loops. The historical bug went
through `CTimecode(start_seconds=_end_mtc.milliseconds_rounded/1000)`, which
lost one frame per iteration under older cuemsutils. The engine fix assigns
`_start_mtc` directly from the previous `_end_mtc.frames`. cuemsutils later
also made the ms round-trip lossless; both paths are pinned here.

The symptom was audio cues loop-starting ~29960 ms apart instead of 30000 ms,
drifting linearly against the videocomposer which wraps at the true media
length.
"""

from __future__ import annotations

import pytest
from cuemsutils.tools.CTimecode import CTimecode


def _rebase_fixed(
    end_mtc: CTimecode, duration: CTimecode
) -> tuple[CTimecode, CTimecode]:
    """Mirror of the fixed rebase in loop_cue.py:107-108 and :224-225."""
    start_mtc = CTimecode(framerate=end_mtc.framerate, frames=end_mtc.frames)
    new_end_mtc = start_mtc + duration
    return start_mtc, new_end_mtc


def _rebase_buggy(
    end_mtc: CTimecode, duration: CTimecode, framerate
) -> tuple[CTimecode, CTimecode]:
    """Mirror of the pre-fix rebase — kept for contrast so the test documents
    the drift the fix eliminates."""
    start_mtc = CTimecode(
        framerate=framerate, start_seconds=end_mtc.milliseconds_rounded / 1000
    )
    new_end_mtc = start_mtc + duration
    return start_mtc, new_end_mtc


@pytest.mark.parametrize("framerate", ["25", "30", "24"])
def test_rebase_preserves_30s_duration_over_10_iterations(framerate):
    """After the fix, each loop iteration advances _start_mtc by exactly one
    duration. Drift must be zero across many iterations."""
    duration = CTimecode("00:00:30.000").return_in_other_framerate(framerate)
    duration_ms = 30000

    # simulate cue GO at MTC=0
    start_mtc = CTimecode(framerate=framerate, frames=1)
    end_mtc = start_mtc + duration

    prev_start_ms = start_mtc.milliseconds_rounded
    for i in range(1, 11):
        start_mtc, end_mtc = _rebase_fixed(end_mtc, duration)
        delta = start_mtc.milliseconds_rounded - prev_start_ms
        assert delta == duration_ms, (
            f"iter {i} @ {framerate} fps: _start_mtc advanced by {delta} ms, "
            f"expected {duration_ms} ms (drift = {delta - duration_ms} ms)"
        )
        prev_start_ms = start_mtc.milliseconds_rounded


def test_legacy_ms_roundtrip_rebase_no_longer_drifts_at_25fps():
    """Old start_seconds(ms/1000) rebase used to lose 40 ms/iter at 25 fps.

    cuemsutils CTimecode hardening made that round-trip lossless; the engine
    still uses frame-domain assign (_rebase_fixed) as defense in depth. Pin
    zero drift so a future cuemsutils regression resurfaces here.
    """
    framerate = "25"
    duration = CTimecode("00:00:30.000").return_in_other_framerate(framerate)

    start_mtc = CTimecode(framerate=framerate, frames=1)
    end_mtc = start_mtc + duration

    drifts = []
    prev_start_ms = start_mtc.milliseconds_rounded
    for _ in range(5):
        start_mtc, end_mtc = _rebase_buggy(end_mtc, duration, framerate)
        delta = start_mtc.milliseconds_rounded - prev_start_ms
        drifts.append(delta - 30000)
        prev_start_ms = start_mtc.milliseconds_rounded

    assert all(d == 0 for d in drifts), (
        f"expected ms round-trip rebase to be lossless at 25 fps, got {drifts}"
    )


def test_fixed_rebase_matches_absolute_anchor():
    """Chained direct-assign must yield the same result as an absolute anchor
    computation `start + N*duration` — they're equivalent when duration is
    exact in the working framerate."""
    framerate = "25"
    duration = CTimecode("00:00:30.000").return_in_other_framerate(framerate)
    # simulate cue GO at MTC=33040 ms (25 fps)
    initial_frames = 1 + 33040 // 40

    start_mtc = CTimecode(framerate=framerate, frames=initial_frames)
    end_mtc = start_mtc + duration

    for i in range(1, 6):
        start_mtc, end_mtc = _rebase_fixed(end_mtc, duration)
        anchor = CTimecode(framerate=framerate, frames=initial_frames)
        for _ in range(i):
            anchor = anchor + duration
        assert start_mtc.milliseconds_rounded == anchor.milliseconds_rounded, (
            f"iter {i}: chained rebase ({start_mtc.milliseconds_rounded} ms) "
            f"disagrees with absolute anchor ({anchor.milliseconds_rounded}"
            f"ms)"
        )
