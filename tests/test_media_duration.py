# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Media duration through the five places the engine reads it (FR-016).

``media.duration`` arrives as a ``CTimecode``, or as ``None`` for an empty
``<duration/>`` (schema-valid). The characterization cases pin today's timing
arithmetic so removing the ``CTimecode(...)`` re-wraps cannot move a cue
(FR-016a); the ``None`` cases pin that an empty duration is zero, never an
exception, and is said out loud once (FR-016b).
"""

import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Match the repo's test convention (avoid the OSC hub import at collection time).
sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", MagicMock())

from cuemsutils.cues import AudioCue, VideoCue  # noqa: E402
from cuemsutils.cues.MediaCue import Media  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402
from cuemsengine.cues.loop_cue import loop_audioCue, loop_videoCue  # noqa: E402
from cuemsengine.cues.run_cue import run_audioCue, run_videoCue  # noqa: E402
from cuemsengine.tools.ids import id_str  # noqa: E402

DURATIONS = ["00:00:12.500", "00:01:00.000"]
FRAMERATES = ["25", "30"]
# The helper's own wording; CueHandler logs a separate "zero body" warning
# for enabled A/V cues, which is not what FR-016b counts.
NONE_WARNING = "no media duration"


def _mtc(framerate, seconds=3600):
    """An MTC stand-in already far past any cue end, so loops never wait."""
    return SimpleNamespace(
        main_tc=CTimecode(framerate=framerate, start_seconds=seconds)
    )


def _cue(cls, duration):
    cue = cls()
    cue.media = Media({"file_name": "media.file", "duration": duration})
    if duration is None:
        cue.media.duration = None
    cue._osc = MagicMock()
    return cue


def _audio(duration):
    return _cue(AudioCue, duration)


def _video(duration):
    cue = _cue(VideoCue, duration)
    cue._layer_ids = ["L1"]
    return cue


def _run(cue, mtc):
    runner = run_audioCue if isinstance(cue, AudioCue) else run_videoCue
    with patch("cuemsengine.cues.run_cue.PLAYER_HANDLER") as ph:
        ph.get_audio_mixer.return_value = None
        ph.get_all_cue_output_names.return_value = []
        ph.media_dimensions.return_value = (1920, 1080)
        runner(cue, mtc)


def _loop_twice(cue, mtc):
    """Two iterations on a local cue: the second end is first end + duration."""
    cue.loop = 2
    cue._local = True
    cue._stop_requested = False
    cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, frames=100)
    cue._end_mtc = CTimecode(framerate=mtc.main_tc.framerate, frames=200)
    first_end = cue._end_mtc
    looper = loop_audioCue if isinstance(cue, AudioCue) else loop_videoCue
    looper(cue, mtc)
    return first_end


def _converted(duration, framerate):
    return CTimecode(duration).return_in_other_framerate(framerate)


# ─── FR-016a: characterization, green before the wraps are touched ──────────


@pytest.mark.parametrize("framerate", FRAMERATES)
@pytest.mark.parametrize("duration", DURATIONS)
@pytest.mark.parametrize("make", [_audio, _video], ids=["audio", "video"])
def test_run_sets_end_to_start_plus_converted_duration(make, duration, framerate):
    cue = make(duration)
    _run(cue, _mtc(framerate))
    expected = cue._start_mtc + _converted(duration, framerate)
    assert cue._end_mtc.frames == expected.frames
    assert str(cue._end_mtc) == str(expected)


@pytest.mark.parametrize("framerate", FRAMERATES)
@pytest.mark.parametrize("duration", DURATIONS)
@pytest.mark.parametrize("make", [_audio, _video], ids=["audio", "video"])
def test_loop_rebases_by_converted_duration(make, duration, framerate):
    cue = make(duration)
    first_end = _loop_twice(cue, _mtc(framerate))
    expected = CTimecode(framerate=framerate, frames=first_end.frames) + _converted(
        duration, framerate
    )
    assert cue._end_mtc.frames == expected.frames


@pytest.mark.parametrize("duration", DURATIONS)
@pytest.mark.parametrize("cls", [AudioCue, VideoCue])
def test_effective_duration_body_is_milliseconds_exact(cls, duration):
    cue = _cue(cls, duration)
    assert CueHandler._effective_duration_ms(cue) == (
        CTimecode(duration).milliseconds_exact
    )


# ─── FR-016b: an empty <duration/> is zero, logged once, never raised ───────


def _none_warnings(caplog, cue):
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and NONE_WARNING in r.getMessage()
        and id_str(cue.id) in r.getMessage()
    ]


@pytest.mark.parametrize("make", [_audio, _video], ids=["audio", "video"])
def test_run_with_no_duration_is_zero_and_warned(make, caplog):
    cue = make(None)
    mtc = _mtc("25")
    with caplog.at_level(logging.WARNING):
        _run(cue, mtc)
    assert cue._end_mtc.frames == cue._start_mtc.frames
    assert len(_none_warnings(caplog, cue)) == 1


@pytest.mark.parametrize("make", [_audio, _video], ids=["audio", "video"])
def test_loop_with_no_duration_is_zero_and_warned(make, caplog):
    cue = make(None)
    mtc = _mtc("25")
    with caplog.at_level(logging.WARNING):
        first_end = _loop_twice(cue, mtc)
    assert cue._end_mtc.frames == first_end.frames
    assert len(_none_warnings(caplog, cue)) == 1


@pytest.mark.parametrize("cls", [AudioCue, VideoCue])
def test_effective_duration_with_no_duration_is_zero_and_warned(cls, caplog):
    cue = _cue(cls, None)
    with caplog.at_level(logging.WARNING):
        assert CueHandler._effective_duration_ms(cue) == 0
    assert len(_none_warnings(caplog, cue)) == 1
