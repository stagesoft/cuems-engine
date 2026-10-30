# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Which length a looping cue loops on (plan 869ejxng3 + 1amfwm7e6cw rev 3.17,
D15, §4.1a, §4.5): ``loop_mode.choose_period`` (the rule: own track, A within
the slack threshold T = max(2 frames, 80 ms), a same-file pair on A within
S = 500 ms and on the longest track beyond, V quantized to the audio grid, R1)
and ``NodeEngine._choose_loop_lengths`` (the grouping over the whole project,
the pair INFO, the force-period knob after the choice, R3, the int32 re-check,
R12, the same-file-different-starts WARNING, R10).

Lengths are built from whole samples at 48 kHz and whole frames at 25 fps
unless a case says otherwise: 1 frame = 1920 samples, T = 80 ms = 3840 samples
(2 frames at 25 fps), S = 500 ms = 24000 samples.
"""

import uuid
from fractions import Fraction
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cuemsutils.cues import AudioCue, CueList, VideoCue
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.media_sidecars import Period

from cuemsengine.cues import loop_mode
from cuemsengine.tools import test_knobs

RATE = 48000


def _p(a_samples=None, frames=None, fps="25/1", rate=RATE):
    """A file's period as the probe gives it: num/den = A when the file has
    audio (rate set), V otherwise; realFrames at fps = V."""
    if a_samples is None:  # video-only
        fn, fd = (int(x) for x in fps.split("/"))
        return Period(
            num=frames * fd,
            den=fn,
            rate=None,
            real_frames=frames,
            fps=fps,
            rule="stream",
            frames_rule="stream",
            vfr=False,
            size=1,
            mtime=0,
            ffprobe="fake",
        )
    return Period(
        num=a_samples,
        den=rate,
        rate=rate,
        real_frames=frames,
        fps=fps if frames is not None else None,
        rule="walk",
        frames_rule="stream" if frames is not None else None,
        vfr=False,
        size=1,
        mtime=0,
        ffprobe="fake",
    )


def _secs(period):
    return Fraction(period.num, period.den)


# --------------------------------------------------------------------------- the rule


def test_audio_only_and_video_only_files_loop_their_track():
    audio = loop_mode.choose_period(_p(96000), False, False)
    assert audio.origin == "audio" and audio.period == _p(96000)
    video = loop_mode.choose_period(_p(None, 50), True, False)
    assert video.origin == "video" and _secs(video.period) == 2
    assert audio.treatment == video.treatment == ""


def test_within_T_the_audio_rules_for_every_cue():
    # 30 s of video, the audio 80 ms (= T at 25 fps) longer: A for both kinds
    p = _p(30 * RATE + 3840, 750)
    for is_video in (True, False):
        for paired in (True, False):
            c = loop_mode.choose_period(p, is_video, paired)
            assert c.origin == "audio" and c.period == p and not c.paired
    held = loop_mode.choose_period(p, True, False)
    assert held.treatment == "held" and abs(held.tail_ms - 80.0) < 1e-9
    # the video 80 ms longer: cut, still A
    cut = loop_mode.choose_period(_p(30 * RATE - 3840, 750), True, False)
    assert cut.origin == "audio" and cut.treatment == "cut"


def test_the_80_ms_floor_keeps_a_60_fps_export_in_the_audio_row():
    # the sweep's worst mkv AAC at 60 fps: +45.8 ms = 2.75 frames (R5)
    p = _p(round((10.0 + 0.0458) * RATE), 600, fps="60/1")
    c = loop_mode.choose_period(p, True, False)
    assert c.origin == "audio" and c.period == p
    # under a frame-only threshold it would have looped its own track
    assert 0.0458 * 60 > 2


def test_beyond_T_a_lone_cue_loops_its_own_track():
    p = _p(30 * RATE + 3841, 750)  # one sample beyond T
    v = loop_mode.choose_period(p, True, False)
    assert v.origin == "video" and (v.period.num, v.period.den) == (750, 25)
    assert v.treatment == "" and v.tail_ms == 0.0
    a = loop_mode.choose_period(p, False, False)
    assert a.origin == "audio" and a.period == p and a.treatment == ""


def test_a_lone_video_at_29_97_gets_its_exact_frame_count():
    # P = V: num = frames x 1001, den = 30000 -> Pf = realFrames exactly
    # (the audio 25 s against 29.997 s of video: beyond T, the lone video's own)
    p = _p(48000 * 25, 899, fps="30000/1001")
    c = loop_mode.choose_period(p, True, False)
    assert (c.period.num, c.period.den) == (899 * 1001, 30000)
    pf = Fraction(c.period.num * 30000, c.period.den * 1001)
    assert pf == 899


def test_a_pair_within_S_loops_on_A_the_video_held_or_cut():
    # the audio 300 ms longer (v30a30.3): A, the last frame held 300 ms
    longer = _p(round(30.3 * RATE), 750)
    v = loop_mode.choose_period(longer, True, True)
    a = loop_mode.choose_period(longer, False, True)
    assert v.period == a.period == longer and v.origin == a.origin == "audio"
    assert v.paired and v.treatment == "held" and abs(v.tail_ms - 300) < 1e-9
    assert a.treatment == ""
    # the video 300 ms longer (v30a29.7): still A, the video cut 300 ms (R23)
    shorter = _p(round(29.7 * RATE), 750)
    v = loop_mode.choose_period(shorter, True, True)
    a = loop_mode.choose_period(shorter, False, True)
    assert v.period == a.period == shorter and v.origin == "audio"
    assert v.treatment == "cut" and abs(v.tail_ms - 300) < 1e-9
    assert a.treatment == ""  # the music is never padded inside S


def test_the_edges_of_S():
    at_s = _p(30 * RATE + 24000, 750)  # exactly 500 ms
    c = loop_mode.choose_period(at_s, True, True)
    assert c.origin == "audio" and c.treatment == "held"
    beyond = _p(30 * RATE + 24001, 750)
    c = loop_mode.choose_period(beyond, True, True)
    assert c.origin == "longest" and c.treatment == "not drawn"
    at_s = _p(30 * RATE - 24000, 750)
    assert loop_mode.choose_period(at_s, False, True).origin == "audio"
    beyond = _p(30 * RATE - 24001, 750)
    c = loop_mode.choose_period(beyond, False, True)
    assert c.origin == "longest" and c.treatment == "silent"


def test_a_pair_beyond_S_loops_on_the_longest_track():
    # the audio 2 s longer (v30a32): A for both, the video not drawn for 2 s
    p = _p(32 * RATE, 750)
    v = loop_mode.choose_period(p, True, True)
    a = loop_mode.choose_period(p, False, True)
    assert v.period == a.period == p and v.origin == a.origin == "longest"
    assert v.treatment == "not drawn" and abs(v.tail_ms - 2000) < 1e-9
    # the video 2 s longer (v30a28): V quantized to the audio grid, the audio silent
    p = _p(28 * RATE, 750)
    v = loop_mode.choose_period(p, True, True)
    a = loop_mode.choose_period(p, False, True)
    assert (v.period.num, v.period.den) == (30 * RATE, RATE)
    assert v.period == a.period and v.origin == "longest"
    assert a.treatment == "silent" and abs(a.tail_ms - 2000) < 1e-9
    assert v.treatment == ""  # 30 s is a whole number of samples: no tail


def test_sintel_as_a_pair_and_alone():
    # 888.064 s of audio (48 kHz), 21 311 frames at 24 fps = 887.958 s
    p = _p(42627072, 21311, fps="24/1")
    pair = loop_mode.choose_period(p, True, True)
    assert pair.origin == "audio" and pair.treatment == "held"
    assert 105 < pair.tail_ms < 107  # the mastering slack, 2.5 frames, held
    alone = loop_mode.choose_period(p, True, False)  # 106 ms > T = 83.3 ms
    assert alone.origin == "video" and (alone.period.num, alone.period.den) == (
        21311,
        24,
    )


def test_r1_the_quantized_period_agrees_at_both_ends_over_a_million_passes():
    """R1: the player wraps on P_s = (num x rate + den/2) / den whole samples
    (audiofstream.cpp setLoop), the videocomposer on Pf = num x fps_num /
    (den x fps_den) frames, in integer rationals. With den = rate the two are
    the same instant at every pass; both are linear in the pass index, so
    equality at pass 10^6 is equality at every pass up to it."""
    k = 1_000_000
    for fps, rate, frames, a_short in (
        ("30000/1001", 48000, 899, 28 * 48000),
        ("30000/1001", 44100, 1798, 50 * 44100),
        ("24000/1001", 48000, 1439, 50 * 48000),
        ("25/1", 44100, 751, 25 * 44100),
        ("60/1", 48000, 1801, 25 * 48000),
    ):
        p = _p(a_short, frames, fps=fps, rate=rate)
        c = loop_mode.choose_period(p, True, True)
        assert c.origin == "longest" and c.period.den == rate
        num, den = c.period.num, c.period.den
        p_s = (num * rate + den // 2) // den  # the player's arithmetic
        fn, fd = (int(x) for x in fps.split("/"))
        player = Fraction(k * p_s, rate)  # the pass boundary in seconds
        vc = Fraction(k * num * fn, den * fd) * Fraction(fd, fn)  # k·Pf frames
        assert player == vc
        # the video's own tail is sub-sample, held (≤ 10 µs)
        v = Fraction(frames * fd, fn)
        assert 0 <= Fraction(num, den) - v + Fraction(1, 2 * rate)
        assert abs(Fraction(num, den) - v) <= Fraction(1, 2 * rate)
    # the negative control: the exact V unquantized drifts in the player
    num, den = 899 * 1001, 30000
    p_s = (num * 48000 + den // 2) // den
    drift = abs(Fraction(k * p_s, 48000) - Fraction(k * num, den))
    assert drift * 48000 > 1  # more than a sample over 10^6 passes (4 s here)


# --------------------------------------------------------------------------- the grouping


def _media(
    kind,
    period=None,
    file_name="pair.mp4",
    prewait=0.0,
    post_go="pause",
    target=None,
    local=True,
    loop=-1,
    enabled=True,
):
    c = kind(
        {
            "id": str(uuid.uuid4()),
            "name": "d15",
            "loop": loop,
            "enabled": enabled,
            "Media": {
                "file_name": file_name,
                "id": str(uuid.uuid4()),
                "duration": "00:00:30.000",
            },
        }
    )
    c._local = local
    c._loop_period = period if local else None
    c.post_go = post_go
    c._target_object = target
    c.prewait = CTimecode(start_seconds=prewait)
    return c


def _node(*contents):
    from cuemsengine.NodeEngine import NodeEngine

    root = CueList()
    root.contents = list(contents)
    n = NodeEngine.__new__(NodeEngine)
    n.script = SimpleNamespace(cuelist=root)
    n._legacy_period = []
    return n


def _choose(node, cues):
    with patch("cuemsengine.NodeEngine.Logger") as log:
        node._choose_loop_lengths(cues)
    return log


def _lines(log, level):
    return [str(c.args[0]) for c in getattr(log, level).call_args_list]


@pytest.fixture(autouse=True)
def _no_knobs(monkeypatch):
    for n in ("CUEMS_TEST_KNOBS", "CUEMS_TEST_FORCE_PERIOD"):
        monkeypatch.delenv(n, raising=False)
    test_knobs.reset_for_tests()
    yield
    test_knobs.reset_for_tests()


def test_a_same_file_pair_started_together_loops_on_the_longest_track():
    raw = _p(28 * RATE, 750)  # the video 2 s longer
    video = _media(VideoCue, raw)
    audio = _media(AudioCue, raw, post_go="go", target=video)
    log = _choose(_node(audio, video), [audio, video])
    assert audio._loop_period == video._loop_period
    assert (audio._loop_period.num, audio._loop_period.den) == (30 * RATE, RATE)
    assert audio._loop_origin == video._loop_origin == "longest"
    assert audio._loop_period_raw is raw
    assert audio._loop_partners == [str(video.id)]
    pairs = [l for l in _lines(log, "info") if l.startswith("A/V pair on pair.mp4")]
    assert len(pairs) == 1 and "tail 2000.000 ms on the audio, silent" in pairs[0]
    assert not _lines(log, "warning")


def test_a_pair_split_across_nodes_chooses_the_same_length_on_both():
    raw = _p(28 * RATE, 750)
    # node A plays the audio, node B the video: the same project on both
    v_remote = _media(VideoCue, raw, local=False)
    a_local = _media(AudioCue, raw, post_go="go", target=v_remote)
    _choose(_node(a_local, v_remote), [a_local])
    v_local = _media(VideoCue, raw)
    a_remote = _media(AudioCue, raw, post_go="go", target=v_local, local=False)
    _choose(_node(a_remote, v_local), [v_local])
    assert (a_local._loop_period.num, a_local._loop_period.den) == (
        v_local._loop_period.num,
        v_local._loop_period.den,
    )
    assert a_local._loop_origin == v_local._loop_origin == "longest"


def test_lone_cues_beyond_T_loop_their_own_track_without_a_pair_line():
    raw = _p(32 * RATE, 750)
    video = _media(VideoCue, raw)
    audio = _media(AudioCue, raw, file_name="other.wav")
    log = _choose(_node(audio, video), [audio, video])
    assert (video._loop_period.num, video._loop_period.den) == (750, 25)
    assert video._loop_origin == "video" and video._loop_partners == []
    assert audio._loop_origin == "audio"
    assert not [l for l in _lines(log, "info") if l.startswith("A/V pair")]


def test_same_file_cues_with_different_starts_are_no_pair_and_warn():
    raw = _p(32 * RATE, 750)
    video = _media(VideoCue, raw)
    audio = _media(AudioCue, raw, prewait=1.0)  # not started together
    log = _choose(_node(audio, video), [audio, video])
    assert video._loop_origin == "video" and audio._loop_origin == "audio"
    warnings = _lines(log, "warning")
    assert len(warnings) == 1
    assert "same file, different starts" in warnings[0]
    assert "2000.000 ms per pass" in warnings[0]
    # within T they loop on the same length: DEBUG only
    raw = _p(30 * RATE + 1920, 750)
    video = _media(VideoCue, raw)
    audio = _media(AudioCue, raw, prewait=1.0)
    log = _choose(_node(audio, video), [audio, video])
    assert not _lines(log, "warning")
    assert any("loop on the same length" in l for l in _lines(log, "debug"))


def test_a_disabled_member_still_makes_the_pair():
    raw = _p(28 * RATE, 750)
    video = _media(VideoCue, raw)
    audio = _media(AudioCue, raw, post_go="go", target=video, enabled=False)
    _choose(_node(audio, video), [audio, video])
    assert video._loop_origin == "longest"
    assert video._loop_period.num == 30 * RATE


def test_several_videocues_and_one_audiocue_form_one_group():
    raw = _p(32 * RATE, 750)
    v1 = _media(VideoCue, raw)
    v2 = _media(VideoCue, raw, post_go="go", target=v1)
    audio = _media(AudioCue, raw, post_go="go", target=v2)
    log = _choose(_node(audio, v1, v2), [audio, v1, v2])
    assert v1._loop_period == v2._loop_period == audio._loop_period == raw
    assert {c._loop_origin for c in (audio, v1, v2)} == {"longest"}
    assert len([l for l in _lines(log, "info") if l.startswith("A/V pair")]) == 1


def test_a_cuelist_child_never_makes_a_pair():
    raw = _p(28 * RATE, 750)
    child = _media(VideoCue, raw)
    inner = CueList()
    inner.contents = [child]
    audio = _media(AudioCue, raw)
    _choose(_node(audio, inner), [audio])
    assert audio._loop_origin == "audio" and audio._loop_period == raw


def test_a_play_once_cue_never_makes_a_pair():
    raw = _p(28 * RATE, 750)
    once = _media(VideoCue, raw, loop=1)
    audio = _media(AudioCue, raw, post_go="go", target=once)
    _choose(_node(audio, once), [audio])
    assert audio._loop_origin == "audio"


def test_an_unknown_video_length_is_an_audio_only_choice():
    raw = _p(32 * RATE, None)  # R21: no stream duration, the count missed
    video = _media(VideoCue, raw)
    audio = _media(AudioCue, raw, post_go="go", target=video)
    _choose(_node(audio, video), [audio, video])
    assert audio._loop_period == video._loop_period == raw
    assert audio._loop_origin == video._loop_origin == "audio"


def test_the_force_period_knob_overrides_the_choice(monkeypatch):
    # R3: on a pair whose choice is the longest track, the forced period
    # (1 s shorter than the video, beyond S) must reach the videocomposer
    raw = _p(28 * RATE, 750)
    video = _media(VideoCue, raw)
    audio = _media(AudioCue, raw, post_go="go", target=video)
    monkeypatch.setenv("CUEMS_TEST_KNOBS", "1")
    monkeypatch.setenv("CUEMS_TEST_FORCE_PERIOD", f"{str(video.id)[:8]}:29:1")
    log = _choose(_node(audio, video), [audio, video])
    assert (video._loop_period.num, video._loop_period.den) == (29, 1)
    assert audio._loop_period.num == 30 * RATE  # the knob names one cue
    assert any(
        "TEST KNOB" in w and "longest choice" in w for w in _lines(log, "warning")
    )


def test_the_int32_bound_is_rechecked_on_the_chosen_length():
    # a lone VideoCue at 29.97 on 2.2 M frames: num = frames x 1001 > 2^31 - 1
    raw = _p(48000 * 60, 2_200_000, fps="30000/1001")
    video = _media(VideoCue, raw)
    log = _choose(_node(video), [video])
    assert video._loop_period is None
    assert any("int32" in e for e in _lines(log, "error"))
