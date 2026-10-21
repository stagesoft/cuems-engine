# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Looping AudioCues in wrap mode and in legacy mode (plan 869ejxng3 +
1amfwm7e6cw rev 3.14, §4.2, §4.5): what run → reveal → loop send, the timeline
on P, the ack rules and their fallback, the 2-frame disarm delay.

Real time, a fake MTC (25 fps whole frames, as the listener holds it), a fake
OSC client that records ``set_value`` and a fake player with the CAPS/LOOP
state the stdout reader keeps.
"""

import threading
import time
import uuid
from unittest.mock import patch

import pytest
from cuemsutils.cues import AudioCue
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.media_sidecars import Period

from cuemsengine.cues import loop_mode
from cuemsengine.cues.loop_cue import loop_cue
from cuemsengine.cues.run_cue import reveal_cue, run_cue
from cuemsengine.players.Player import LoopAck
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER


class FakeMtc:
    def __init__(self, base_ms=600_000.0):
        self.base_ms, self.t0 = base_ms, time.monotonic()

    def ms(self):
        return self.base_ms + (time.monotonic() - self.t0) * 1000.0

    @property
    def main_tc(self):
        return CTimecode(framerate=25, start_seconds=int(self.ms() // 40) * 0.040)


class FakeOsc:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def set_value(self, path, value):
        if path in self.fail:
            raise ValueError("boom")
        self.sent.append((path, value))

    def paths(self):
        return [p for p, _ in self.sent]


class FakePlayer:
    def __init__(self, caps=("loop", "varispeed")):
        self.caps = frozenset(caps)
        self.loop_ack = None
        self.last_wrap_ver = -1

    def ack(self, mode, ver):
        if mode == "wrap":
            self.last_wrap_ver = max(self.last_wrap_ver, ver)
        self.loop_ack = LoopAck(ver, 3, 0, 0, mode)


P_MS = 400.0
PERIOD = Period(
    num=19200,
    den=48000,
    rate=48000,
    real_frames=None,
    fps=None,
    rule="walk",
    frames_rule=None,
    vfr=False,
    size=1,
    mtime=0,
    ffprobe="fake",
)


def _cue(loop, period=PERIOD, duration="00:00:00.360"):
    d = {
        "id": str(uuid.uuid4()),
        "name": "wrap test",
        "loop": loop,
        "Media": {"file_name": "a.wav", "id": str(uuid.uuid4()), "duration": duration},
    }
    cue = AudioCue(d)
    cue._local = True
    cue._stop_requested = False
    cue._loop_period = period
    cue._osc = FakeOsc()
    return cue


def _lifecycle(cue, player, stop_after_ms=None, on_reveal=None):
    """run → wait for the start → reveal → loop, as CueHandler.go_threaded does."""
    mtc = FakeMtc()
    with patch.object(PLAYER_HANDLER, "audio_player", lambda c: player):
        start_ms = mtc.main_tc.milliseconds_exact
        run_cue(cue, mtc, start_ms)
        while mtc.main_tc.milliseconds_exact < cue._start_mtc.milliseconds_exact:
            time.sleep(0.01)
        reveal_cue(cue, mtc, start_ms)
        if on_reveal:
            on_reveal()
        if stop_after_ms is not None:

            def stop():
                time.sleep(stop_after_ms / 1000)
                cue._stop_requested = True

            threading.Thread(target=stop, daemon=True).start()
        loop_cue(cue, mtc)
    return mtc, start_ms


# --------------------------------------------------------------------------- wrap


def test_wrap_mode_sends_loop_and_never_reanchors():
    cue, player = _cue(3), FakePlayer()
    mtc, start = _lifecycle(cue, player, on_reveal=lambda: player.ack("wrap", 1))
    p = cue._osc.paths()
    assert cue._osc.sent[0][0] == "/offset_i"
    assert isinstance(cue._osc.sent[0][1], int)  # whole ms, int32 (G1b)
    assert cue._osc.sent[1] == ("/loop", [3, 19200, 48000])
    assert p[2] == "/volmaster"
    assert p[3:6] == [
        "/offset_i",
        "/loop",
        "/mtcfollow",
    ]  # reveal: offset, loop, follow
    assert p[6:] == ["/loop", "/loop"]  # one re-send per later pass
    assert (
        "/mtcfollow" not in p[6:] and "/offset" not in p and p.count("/offset_i") == 2
    )
    assert cue._player_wraps is True and cue._wrap_fallback is False
    # the timeline on P, from the absolute instants (G20)
    base = loop_mode.tc_at(25, start).milliseconds_exact
    assert abs(cue._end_mtc.milliseconds_exact - (base + 3 * P_MS)) <= 40


def test_no_wrap_ack_within_1s_falls_back_to_legacy_on_P():
    cue, player = _cue(5), FakePlayer()
    with patch.object(loop_mode, "WRAP_ACK_TIMEOUT_S", 0.5):
        _lifecycle(cue, player)
    p = cue._osc.paths()
    assert cue._wrap_fallback is True and cue._player_wraps is False
    i = p.index("/loop", 4)  # the first pass re-send …
    fb = [
        k for k, (path, v) in enumerate(cue._osc.sent) if path == "/loop" and v == [1]
    ]
    assert fb, "the fallback /loop [1]"
    after = p[fb[0] + 1 :]
    assert after and set(after) <= {
        "/offset_i",
        "/mtcfollow",
    }  # per-pass re-anchor, then the end
    assert after[-1] == "/mtcfollow"  # legacy ends with /mtcfollow 0
    assert i < fb[0]


def test_an_off_ack_newer_than_the_wrap_falls_back():
    cue, player = _cue(4), FakePlayer()

    def acks():
        player.ack("wrap", 1)
        threading.Timer(0.5, lambda: player.ack("off", 2)).start()

    _lifecycle(cue, player, on_reveal=acks)
    assert cue._wrap_fallback is True
    assert ("/loop", [1]) in cue._osc.sent


def test_an_old_off_below_the_last_wrap_is_ignored():
    cue, player = _cue(3), FakePlayer()

    def acks():
        player.ack("off", 1)
        player.ack("wrap", 2)
        player.loop_ack = LoopAck(1, 3, 0, 0, "off")  # a late receipt line, older ver

    _lifecycle(cue, player, on_reveal=acks)
    assert cue._wrap_fallback is False


def test_the_fallback_is_latched_for_the_go():
    cue, player = _cue(5), FakePlayer()
    with patch.object(loop_mode, "WRAP_ACK_TIMEOUT_S", 0.3):

        def late():
            time.sleep(0.8)
            player.ack("wrap", 7)  # would re-enable wrap mode: must not

        threading.Thread(target=late, daemon=True).start()
        _lifecycle(cue, player)
    assert cue._wrap_fallback is True and cue._player_wraps is False


# --------------------------------------------------------------------------- legacy


@pytest.mark.parametrize("why", ["once", "cuelist", "no_period"])
def test_a_capable_player_gets_loop_1_when_not_wrapping(why):
    cue = _cue(1 if why == "once" else 3, period=None if why == "no_period" else PERIOD)
    if why == "cuelist":
        cue._in_cuelist = True
    _lifecycle(cue, FakePlayer())
    assert cue._osc.sent[1] == ("/loop", [1])
    assert cue._wrap_requested is False
    assert cue._osc.paths()[-1] == "/mtcfollow" and cue._osc.sent[-1][1] == 0
    assert "/offset" not in cue._osc.paths()


def test_an_old_player_gets_no_loop_and_float_offsets_reanchored_on_P():
    cue = _cue(3)
    mtc, start = _lifecycle(cue, None)
    p = cue._osc.paths()
    assert "/loop" not in p and "/offset_i" not in p
    offsets = [v for path, v in cue._osc.sent if path == "/offset"]
    base = offsets[0]
    assert isinstance(base, float)
    # run, reveal, then one re-anchor per later pass, each one P further
    assert [round(o - base) for o in offsets] == [0, 0, -400, -800]


def test_an_abort_before_the_offset_leaves_no_wrap():
    cue = _cue(3)
    cue._osc = FakeOsc(fail={"/offset_i"})
    mtc = FakeMtc()
    with patch.object(PLAYER_HANDLER, "audio_player", lambda c: FakePlayer()):
        run_cue(cue, mtc, mtc.main_tc.milliseconds_exact)
    assert cue._player_wraps is False and cue._wrap_requested is False
    assert "/loop" not in cue._osc.paths()


def test_a_newer_go_ends_a_stale_loop():
    cue, player = _cue(-1), FakePlayer()
    cue._go_generation = 1

    def bump():
        time.sleep(0.6)
        cue._go_generation = 2

    threading.Thread(target=bump, daemon=True).start()
    t0 = time.monotonic()
    _lifecycle(cue, player, on_reveal=lambda: player.ack("wrap", 1))
    assert time.monotonic() - t0 < 3.0


# --------------------------------------------------------------------------- the end


def test_only_a_wrap_cue_s_disarm_waits_two_frames():
    from cuemsengine.cues.CueHandler import CUE_HANDLER

    mtc = FakeMtc()
    cue = _cue(3)
    cue._end_mtc = CTimecode(framerate=25, start_seconds=int(mtc.ms() // 40) * 0.040)
    cue._wrap_requested, cue._wrap_fallback, cue._go_generation = True, False, 0
    t0 = time.monotonic()
    CUE_HANDLER._wait_wrap_player_end(cue, mtc, 0)
    assert 0.04 <= time.monotonic() - t0 <= 0.2  # 2 frames past _end_mtc
    cue._wrap_fallback = True  # legacy: no wait
    t0 = time.monotonic()
    CUE_HANDLER._wait_wrap_player_end(cue, mtc, 0)
    assert time.monotonic() - t0 < 0.02
