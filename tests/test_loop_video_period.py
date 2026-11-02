# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Looping VideoCues on the shared period (plan 869ejxng3 + 1amfwm7e6cw,
Phase B, §4.2, §4.4, §4.5, §4.7; rev 3.17, D15): the track lengths and the
slack threshold, wrap mode (``/loop [1, passes]`` + ``/loop/period`` before
``/mtcfollow``, re-sent per pass, no offset, no ``/loop 0``) whatever the
mismatch, legacy on min(P, V) for an old videocomposer (R24), CueList children
as today, the caps file, the mock videocomposer's caps file, the load-time
period and caps warnings, the D7 drift warning (different files only), and the
sends on the wire. The D15 choice and grouping: ``test_loop_length_d15.py``.

Real time, a fake MTC (25 fps whole frames), a fake OSC client that records
``set_value``.
"""

import os
import socket
import struct
import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pyossia
import pytest
from cuemsutils.cues import AudioCue, CueList, VideoCue
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.media_sidecars import Period

from cuemsengine.cues import loop_mode
from cuemsengine.cues.loop_cue import loop_cue
from cuemsengine.cues.run_cue import reveal_cue, run_cue
from cuemsengine.players import VideoCaps
from cuemsengine.players.LoopPeriods import loop_drift_pairs
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

LAYERS = ["L1", "L2"]
CAPABLE = frozenset({"loop_period"})


class FakeMtc:
    def __init__(self, base_ms=600_000.0):
        self.base_ms, self.t0 = base_ms, time.monotonic()

    def ms(self):
        return self.base_ms + (time.monotonic() - self.t0) * 1000.0

    @property
    def main_tc(self):
        return CTimecode(framerate=25, start_seconds=int(self.ms() // 40) * 0.040)


class FakeOsc:
    def __init__(self):
        self.sent, self.phase = [], None

    def set_value(self, path, value):
        self.sent.append((self.phase, path, value))

    def in_phase(self, phase):
        return [(p, v) for ph, p, v in self.sent if ph == phase]

    def values(self, suffix, phase=None):
        return [
            v
            for ph, p, v in self.sent
            if p.endswith(suffix) and (phase is None or ph == phase)
        ]


class _Out:
    def get_layer_placement(self):
        return 0, 0

    def get_layer_scale(self, w, h):
        return 1.0, 1.0


def _period(num=19200, den=48000, frames=10, fps="25/1"):
    """P = num / den s; 19200 / 48000 = 400 ms = 10 frames at 25 fps."""
    return Period(
        num=num,
        den=den,
        rate=den,
        real_frames=frames,
        fps=fps,
        rule="walk",
        frames_rule="stream",
        vfr=False,
        size=1,
        mtime=0,
        ffprobe="fake",
    )


def _cue(loop, period=None, duration="00:00:00.360", in_cuelist=False):
    d = {
        "id": str(uuid.uuid4()),
        "name": "video loop test",
        "loop": loop,
        "Media": {"file_name": "v.mov", "id": str(uuid.uuid4()), "duration": duration},
    }
    cue = VideoCue(d)
    cue._local = True
    cue._stop_requested = False
    cue._loop_period = period
    cue._loop_origin = "audio" if period is not None else None
    cue._in_cuelist = in_cuelist
    cue._layer_ids = list(LAYERS)
    cue._layer_outputs = {lid: "out" for lid in LAYERS}
    cue._osc = FakeOsc()
    return cue


def _lifecycle(cue, caps=CAPABLE, stop_after_ms=None):
    """run → wait for the start → reveal → loop, as CueHandler.go_threaded does."""
    mtc = FakeMtc()
    osc = cue._osc
    with (
        patch.object(PLAYER_HANDLER, "_video_caps", caps),
        patch.object(PLAYER_HANDLER, "cue_media_dimensions", lambda c: (1920, 1080)),
        patch.object(
            PLAYER_HANDLER, "resolve_video_output_for_cue", lambda c, n: _Out()
        ),
    ):
        start_ms = mtc.main_tc.milliseconds_exact
        osc.phase = "run"
        run_cue(cue, mtc, start_ms)
        while mtc.main_tc.milliseconds_exact < cue._start_mtc.milliseconds_exact:
            time.sleep(0.01)
        osc.phase = "reveal"
        reveal_cue(cue, mtc, start_ms)
        if stop_after_ms is not None:

            def stop():
                time.sleep(stop_after_ms / 1000)
                cue._stop_requested = True

            threading.Thread(target=stop, daemon=True).start()
        osc.phase = "loop"
        loop_cue(cue, mtc)
    return mtc, start_ms


# --------------------------------------------------------------------------- lengths


def test_the_track_lengths_and_the_slack_threshold():
    from fractions import Fraction

    p = _period(num=19200, den=48000, frames=10)
    assert loop_mode.audio_length(p) == Fraction(2, 5)
    assert loop_mode.video_length(p) == Fraction(2, 5)
    # a video-only file: num/den is V already, no A
    vonly = Period(**{**p.__dict__, "rate": None})
    assert loop_mode.audio_length(vonly) is None
    # no frame count or no rate: no V
    assert loop_mode.video_length(_period(frames=None)) is None
    assert loop_mode.video_length(_period(fps=None)) is None
    assert loop_mode.video_length(_period(fps="0/0")) is None
    # 29.97 at 1001 denominators, exact
    ntsc = _period(num=1001, den=300, frames=100, fps="30000/1001")
    assert loop_mode.video_length(ntsc) == Fraction(1001, 300)
    # T = max(2 frames, 80 ms) (R5): 24 fps 83.3 ms, 25 fps 80, 29.97 fps 80,
    # 50 and 60 fps the 80 ms floor (4 and 4.8 frames)
    ms = {
        f: float(loop_mode.slack(_period(fps=f)) * 1000)
        for f in ("24/1", "25/1", "30000/1001", "50/1", "60/1")
    }
    assert abs(ms["24/1"] - 83.333) < 0.01
    assert ms["25/1"] == ms["30000/1001"] == ms["50/1"] == ms["60/1"] == 80.0
    assert loop_mode.slack(_period(fps=None)) == Fraction(2, 25)


def test_the_legacy_pass_is_min_of_P_and_V():
    # R24: an old videocomposer re-anchors on min(P, V)
    assert loop_mode.video_legacy_pass_ms(_cue(3, _period(frames=7))) == 280.0
    assert loop_mode.video_legacy_pass_ms(_cue(3, _period(frames=12))) == 400.0
    assert loop_mode.video_legacy_pass_ms(_cue(3, _period())) == 400.0
    assert loop_mode.video_legacy_pass_ms(_cue(3, None)) is None
    assert loop_mode.video_legacy_pass_ms(_cue(3, _period(frames=None))) is None
    assert loop_mode.video_passes(_cue(3)) == 3
    assert loop_mode.video_passes(_cue(-1)) == -1
    assert loop_mode.video_passes(_cue(0)) == -1


# --------------------------------------------------------------------------- wrap


def test_wrap_mode_sends_loop_and_period_before_mtcfollow_on_every_layer():
    cue = _cue(3, _period())
    _lifecycle(cue)
    run = cue._osc.in_phase("run")
    for lid in LAYERS:
        lp = f"/videocomposer/layer/{lid}"
        seq = [p for p, _ in run if p.startswith(lp + "/")]
        assert seq.index(lp + "/offset") < seq.index(lp + "/loop")
        assert seq.index(lp + "/loop") < seq.index(lp + "/loop/period")
        assert seq.index(lp + "/loop/period") < seq.index(lp + "/mtcfollow")
        assert (lp + "/loop", [1, 3]) in run
        assert (lp + "/loop/period", [19200, 48000, 10]) in run
    assert cue._video_wrap is True


def test_wrap_mode_resends_per_pass_and_never_reanchors():
    cue = _cue(3, _period())
    mtc, start_ms = _lifecycle(cue)
    loop = cue._osc.in_phase("loop")
    assert not [p for p, _ in loop if p.endswith("/offset")]
    assert [1, 3] in cue._osc.values("/loop", "loop")
    assert [0] not in cue._osc.values("/loop")
    # at loop start + once per later pass (2), per layer
    assert len(cue._osc.values("/loop/period", "loop")) == 3 * len(LAYERS)
    # the timeline is on P from the absolute base (G20): the last pass ends at 3 P
    assert (
        abs(cue._end_mtc.milliseconds_exact - (cue._start_mtc.milliseconds_exact + 400))
        <= 40
    )
    assert abs(cue._end_mtc.milliseconds_exact - (start_ms + 3 * 400)) <= 40
    # a finite loop returns at its _end_mtc
    assert mtc.ms() - cue._end_mtc.milliseconds_exact < 200


def test_an_infinite_wrap_sends_minus_one_passes():
    cue = _cue(-1, _period())
    _lifecycle(cue, stop_after_ms=900)
    assert set(map(tuple, cue._osc.values("/loop"))) == {(1, -1)}
    assert not [p for p, _ in cue._osc.in_phase("loop") if p.endswith("/offset")]


def test_no_mismatch_sends_a_cue_to_legacy():
    # D15: D8's bands 2-3 are gone; any period with a frame count wraps
    sintel = _period(num=888106 * 48, den=48000, frames=22200)
    assert loop_mode.video_wrap_eligible(_cue(-1, sintel), CAPABLE)
    assert loop_mode.video_wrap_eligible(_cue(-1, _period(frames=7)), CAPABLE)
    assert loop_mode.video_wrap_eligible(_cue(-1, _period(frames=13)), CAPABLE)
    # without a frame count it cannot wrap (R21)
    assert not loop_mode.video_wrap_eligible(_cue(-1, _period(frames=None)), CAPABLE)


# --------------------------------------------------------------------------- legacy


def test_an_old_videocomposer_gets_today_s_sends_reanchored_on_P():
    cue = _cue(3, _period(), duration="00:00:00.360")
    _lifecycle(cue, caps=frozenset())
    assert cue._video_wrap is False
    assert not cue._osc.values("/loop/period")
    loop = cue._osc.in_phase("loop")
    offsets = [v for p, v in loop if p.endswith("L1/offset")]
    # two re-anchors (passes 2 and 3), on P = 400 ms, not on the 360 ms stored
    base = -cue._osc.values("L1/offset", "run")[0]
    assert [-o - base for o in offsets] == [10, 20]
    # /loop [1] at loop start, /loop [0] right after the last offset
    l1 = [(p, v) for p, v in loop if "/L1/" in p]
    assert l1[0] == ("/videocomposer/layer/L1/loop", [1])
    assert l1[-1] == ("/videocomposer/layer/L1/loop", [0])


def test_an_old_videocomposer_reanchors_a_shorter_video_on_its_own_length():
    # R24: P = 400 ms (the audio of a pair), V = 280 ms: min(P, V)
    cue = _cue(3, _period(frames=7))
    _lifecycle(cue, caps=frozenset())
    assert cue._video_wrap is False
    assert not cue._osc.values("/loop/period")
    offsets = [v for p, v in cue._osc.in_phase("loop") if p.endswith("L1/offset")]
    base = -cue._osc.values("L1/offset", "run")[0]
    assert [-o - base for o in offsets] == [7, 14]  # 280 ms passes


def test_a_capable_videocomposer_wraps_a_shorter_video_on_P():
    # the same cue with a capable videocomposer: wrap on P, the tail is the VC's
    cue = _cue(3, _period(frames=7))
    _lifecycle(cue)
    assert cue._video_wrap is True
    assert [19200, 48000, 7] in cue._osc.values("/loop/period", "run")


def test_no_period_is_today_s_path():
    cue = _cue(-1, None, duration="00:00:00.400")
    _lifecycle(cue, stop_after_ms=700)
    assert cue._osc.values("/loop", "run") == [[1], [1]]  # loop_early, per layer
    assert not cue._osc.values("/loop/period")
    assert [p for p, _ in cue._osc.in_phase("loop") if p.endswith("/offset")]


def test_a_cuelist_child_plays_as_today():
    cue = _cue(-1, _period(), in_cuelist=True)
    assert not loop_mode.video_wrap_eligible(cue, CAPABLE)


def test_a_play_once_cue_sends_no_loop():
    cue = _cue(1, None)
    _lifecycle(cue)
    assert not cue._osc.values("/loop")
    assert not cue._osc.values("/loop/period")


# --------------------------------------------------------------------------- caps file


def test_the_caps_file_of_a_live_videocomposer(tmp_path):
    path = tmp_path / "videocomposer.caps"
    path.write_text(f"pid={os.getpid()}\nloop_period\n")
    with patch.object(VideoCaps, "_names_videocomposer", lambda pid: True):
        assert VideoCaps.read_videocomposer_caps(str(path)) == CAPABLE


def test_a_caps_file_is_stale_when_its_pid_is_gone_or_not_a_videocomposer(tmp_path):
    path = tmp_path / "videocomposer.caps"
    path.write_text("pid=999999999\nloop_period\n")
    assert VideoCaps.read_videocomposer_caps(str(path)) == frozenset()
    # this pytest process is alive but its cmdline names no videocomposer
    path.write_text(f"pid={os.getpid()}\nloop_period\n")
    with patch.object(VideoCaps, "_names_videocomposer", lambda pid: False):
        assert VideoCaps.read_videocomposer_caps(str(path)) == frozenset()


def test_a_missing_or_malformed_caps_file_is_empty(tmp_path):
    assert VideoCaps.read_videocomposer_caps(str(tmp_path / "none")) == frozenset()
    bad = tmp_path / "bad.caps"
    bad.write_text("loop_period\n")
    assert VideoCaps.read_videocomposer_caps(str(bad)) == frozenset()
    bad.write_text("pid=abc\n")
    assert VideoCaps.read_videocomposer_caps(str(bad)) == frozenset()


def test_eperm_counts_as_alive():
    def kill(pid, sig):
        raise PermissionError(1, "EPERM")

    with patch.object(VideoCaps.os, "kill", kill):
        assert VideoCaps._pid_alive(1)


def test_the_mock_videocomposer_writes_and_removes_its_caps_file(tmp_path):
    from cuemsengine.scripts import mock_videocomposer as mock

    path = str(tmp_path / "run" / "cuems" / "videocomposer.caps")
    assert mock.write_caps(path)
    with open(path) as f:
        assert f.read() == f"pid={os.getpid()}\nloop_period\n"
    with patch.object(VideoCaps, "_names_videocomposer", lambda pid: True):
        assert VideoCaps.read_videocomposer_caps(path) == CAPABLE
    mock.remove_caps(path)
    assert not os.path.exists(path)


def test_the_mock_s_cmdline_names_a_videocomposer():
    # the engine's stale check reads /proc/<pid>/cmdline; the mock's path says it
    import cuemsengine.scripts.mock_videocomposer as mock

    assert b"videocomposer" in mock.__file__.encode()


# --------------------------------------------------------------------------- load


def _node(root):
    from cuemsengine.NodeEngine import NodeEngine

    n = NodeEngine.__new__(NodeEngine)
    n.script = SimpleNamespace(cuelist=root)
    n._legacy_period = []
    return n


def test_the_load_walk_takes_local_looping_video_too():
    v = _cue(-1)
    once = _cue(1)
    child = _cue(-1)
    inner = CueList()
    inner.contents = [child]
    root = CueList()
    root.contents = [v, once, inner]
    assert _node(root)._loop_period_cues() == [v]
    assert child._in_cuelist is True


def test_the_video_period_check_warns_only_without_a_frame_count_or_on_vfr():
    from cuemsengine.NodeEngine import NodeEngine

    ok, wide = _cue(-1, _period()), _cue(-1, _period(frames=7))
    blind = _cue(-1, _period(frames=None))
    vfr = _cue(-1, Period(**{**_period().__dict__, "vfr": True}))
    with patch("cuemsengine.NodeEngine.Logger") as log:
        for c in (ok, wide, blind, vfr):
            NodeEngine._check_video_period(c)
    warnings = [str(c.args[0]) for c in log.warning.call_args_list]
    assert len(warnings) == 2
    assert any(
        "without a video frame count" in w and str(blind.id) in w for w in warnings
    )
    assert any("variable frame rate" in w and str(vfr.id) in w for w in warnings)


def test_a_videocomposer_without_the_capability_is_a_warning_when_video_loops():
    from cuemsengine.NodeEngine import NodeEngine

    with (
        patch.object(PLAYER_HANDLER, "refresh_video_caps", lambda: frozenset()),
        patch("cuemsengine.NodeEngine.Logger") as log,
    ):
        NodeEngine._check_video_caps([_cue(-1)])
        NodeEngine._check_video_caps([])
    assert log.warning.call_count == 1
    with (
        patch.object(PLAYER_HANDLER, "refresh_video_caps", lambda: CAPABLE),
        patch("cuemsengine.NodeEngine.Logger") as log,
    ):
        NodeEngine._check_video_caps([_cue(-1)])
    assert log.warning.call_count == 0


# --------------------------------------------------------------------------- D7


def _media(
    kind, period, prewait=0.0, post_go="pause", target=None, local=True, file_name=None
):
    d = {
        "id": str(uuid.uuid4()),
        "name": "d7",
        "loop": -1,
        "Media": {
            "file_name": file_name or f"{uuid.uuid4().hex}.mov",
            "id": str(uuid.uuid4()),
            "duration": "00:00:01.000",
        },
    }
    c = kind(d)
    c._local = local
    c._loop_period = period
    c.post_go = post_go
    c._target_object = target
    c.prewait = CTimecode(start_seconds=prewait)
    return c


def test_d7_warns_for_a_chain_pair_within_5_percent_but_not_equal():
    a2010 = _period(num=96480, den=48000)  # 2.010 s
    v2000 = _period(num=96000, den=48000)  # 2.000 s
    video = _media(VideoCue, v2000)
    audio = _media(AudioCue, a2010, post_go="go", target=video)
    pairs = loop_drift_pairs([audio, video])
    assert len(pairs) == 1 and abs(pairs[0][2] - 10.0) < 1e-6
    # equal periods (an A/V file within T and its extracted audio): no warning
    same = _media(VideoCue, a2010)
    audio2 = _media(AudioCue, a2010, post_go="go", target=same)
    assert loop_drift_pairs([audio2, same]) == []
    # different prewait, another chain, > 5 %, or another node: no warning
    later = _media(VideoCue, v2000, prewait=1.0)
    audio3 = _media(AudioCue, a2010, post_go="go", target=later)
    assert loop_drift_pairs([audio3, later]) == []
    alone = _media(VideoCue, v2000)
    audio4 = _media(AudioCue, a2010)
    assert loop_drift_pairs([audio4, alone]) == []
    far = _media(VideoCue, _period(num=48000, den=48000))
    audio5 = _media(AudioCue, a2010, post_go="go", target=far)
    assert loop_drift_pairs([audio5, far]) == []
    remote = _media(VideoCue, v2000, local=False)
    audio6 = _media(AudioCue, a2010, post_go="go", target=remote)
    assert loop_drift_pairs([audio6, remote]) == []
    # the same file: the D15 pair or the load's own warning, never D7
    one = _media(VideoCue, v2000, file_name="one.mp4")
    audio7 = _media(AudioCue, a2010, post_go="go", target=one, file_name="one.mp4")
    assert loop_drift_pairs([audio7, one]) == []


# --------------------------------------------------------------------------- wire


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _parse(d):
    a = d[: d.index(b"\0")]
    i = (len(a) // 4 + 1) * 4
    tt = d[i : d.index(b"\0", i)]
    j = i + (len(tt) // 4 + 1) * 4
    args = []
    for t in tt[1:].decode():
        if t == "i":
            args.append(struct.unpack(">i", d[j : j + 4])[0])
        j += 4
    return a.decode(), tt.decode(), args


@pytest.fixture
def wire(monkeypatch):
    from cuemsengine.players.VideoPlayer import VideoClient
    from cuemsengine.tools.PortHandler import PORT_HANDLER

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    monkeypatch.setattr(PORT_HANDLER, "new_random_port", _free_port)
    client = VideoClient(player_port=rx.getsockname()[1], name="wire-video-test")
    client.create_layer_endpoints("L1")
    # creating the layer endpoints pushes the initial `visible -1` (endpoints.py):
    # drain it, so each send below reads its own datagram
    rx.settimeout(0.3)
    try:
        while True:
            rx.recv(2048)
    except socket.timeout:
        pass
    rx.settimeout(2)

    def send(path, value):
        client.set_value(path, value)
        return _parse(rx.recv(2048))

    yield send
    client.remove_device()
    rx.close()


@pytest.mark.skipif(
    not hasattr(pyossia.Node, "remove_child"),
    reason=(
        "installed pyossia has no Node.remove_child — node removal is "
        "unsupported by this libossia build; update the system pyossia package"
    ),
)
def test_the_video_loop_sends_on_the_wire(wire):
    lp = "/videocomposer/layer/L1"
    # legacy: byte for byte what the Int endpoint sent
    assert wire(f"{lp}/loop", [1]) == (f"{lp}/loop", ",i", [1])
    assert wire(f"{lp}/loop", [0]) == (f"{lp}/loop", ",i", [0])
    # wrap mode
    assert wire(f"{lp}/loop", [1, 3]) == (f"{lp}/loop", ",ii", [1, 3])
    assert wire(f"{lp}/loop", [1, -1]) == (f"{lp}/loop", ",ii", [1, -1])
    big = [2**31 - 1, 48000, 1234567]
    assert wire(f"{lp}/loop/period", big) == (f"{lp}/loop/period", ",iii", big)
    # the repetition filter is off: the per-pass re-send goes out
    assert wire(f"{lp}/loop/period", big) == (f"{lp}/loop/period", ",iii", big)
    assert wire(f"{lp}/loop", [1, 3]) == (f"{lp}/loop", ",ii", [1, 3])
