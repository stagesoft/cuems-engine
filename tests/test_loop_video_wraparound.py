# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""loop_videoCue must only enable videocomposer wraparound for cues that repeat.

869fa89uh: `/loop 1` used to be sent for every video cue. The videocomposer
runs its display latency ahead of MTC, so a play-once cue reached end of file
before the engine hid the layer, wrapped, and showed its first frame again.
"""

from __future__ import annotations

from types import SimpleNamespace

from cuemsutils.cues import VideoCue
from cuemsutils.tools.CTimecode import CTimecode

from cuemsengine.cues.loop_cue import loop_cue

LAYER = "cue_0"
LOOP_PATH = f"/videocomposer/layer/{LAYER}/loop"
OFFSET_PATH = f"/videocomposer/layer/{LAYER}/offset"


class _PastEndMtc:
    """MTC that is always past any cue end, so every pass finishes at once."""

    framerate = 25
    milliseconds_rounded = 10**12

    @property
    def main_tc(self):
        return self


class _RecordingOsc:
    def __init__(self, cue, stop_after=None):
        self.calls = []
        self._cue = cue
        self._stop_after = stop_after

    def set_value(self, path, value):
        self.calls.append((path, value))
        if self._stop_after is not None and len(self.calls) >= self._stop_after:
            self._cue._stop_requested = True


def _run(loop, stop_after=None):
    cue = SimpleNamespace(
        id="cue",
        loop=loop,
        media=SimpleNamespace(duration="00:00:10.000"),
        _layer_ids=[LAYER],
        _local=True,
        _stop_requested=False,
        _start_mtc=CTimecode(framerate=25, frames=1),
        _end_mtc=CTimecode(framerate=25, frames=251),
    )
    cue._osc = _RecordingOsc(cue, stop_after)
    loop_cue.registry[VideoCue](cue, _PastEndMtc())
    return cue._osc.calls


def test_play_once_cue_never_enables_wraparound():
    assert _run(loop=1) == []


def test_counted_loop_wraps_then_clamps_on_its_last_pass():
    calls = _run(loop=3)
    assert calls[0] == (LOOP_PATH, 1)
    assert [c for c in calls if c[0] == LOOP_PATH] == [(LOOP_PATH, 1), (LOOP_PATH, 0)]
    # two rebases (passes 2 and 3); /loop 0 comes right after the last offset
    offsets = [i for i, c in enumerate(calls) if c[0] == OFFSET_PATH]
    assert len(offsets) == 2
    assert calls.index((LOOP_PATH, 0)) == offsets[-1] + 1
    assert calls[-1] == (LOOP_PATH, 0)


def test_infinite_loop_keeps_wrapping():
    calls = _run(loop=-1, stop_after=6)
    assert calls[0] == (LOOP_PATH, 1)
    assert (LOOP_PATH, 0) not in calls
