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
from types import SimpleNamespace
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
    """Records set_value per phase (run / reveal / loop). get_node mirrors the
    OssiaClient read-back run_audioCue logs after the offset send."""

    def __init__(self, fail=()):
        self.sent, self.fail, self.phase = [], set(fail), None

    def set_value(self, path, value):
        if path in self.fail:
            raise ValueError("boom")
        self.sent.append((self.phase, path, value))

    def get_node(self, path):
        last = [v for _, p, v in self.sent if p == path]
        return SimpleNamespace(
            parameter=SimpleNamespace(value=last[-1] if last else None)
        )

    def in_phase(self, phase):
        return [(p, v) for ph, p, v in self.sent if ph == phase]

    def paths(self, phase=None):
        return [p for ph, p, _ in self.sent if phase is None or ph == phase]

    def values(self, path):
        return [v for _, p, v in self.sent if p == path]


class FakePlayer:
    def __init__(self, caps=("loop", "varispeed", "dayalign")):
        self.caps = frozenset(caps)
        self.loop_ack = None
        self.last_wrap_ver = -1

    def ack(self, mode, ver):
        """As Player.note_line: the line with the highest ver wins."""
        if mode == "wrap":
            self.last_wrap_ver = max(self.last_wrap_ver, ver)
        if self.loop_ack is None or ver >= self.loop_ack.ver:
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
    osc = cue._osc
    with patch.object(PLAYER_HANDLER, "audio_player", lambda c: player):
        start_ms = mtc.main_tc.milliseconds_exact
        osc.phase = "run"
        run_cue(cue, mtc, start_ms)
        while mtc.main_tc.milliseconds_exact < cue._start_mtc.milliseconds_exact:
            time.sleep(0.01)
        osc.phase = "reveal"
        reveal_cue(cue, mtc, start_ms)
        if on_reveal:
            on_reveal()
        if stop_after_ms is not None:

            def stop():
                time.sleep(stop_after_ms / 1000)
                cue._stop_requested = True

            threading.Thread(target=stop, daemon=True).start()
        osc.phase = "loop"
        loop_cue(cue, mtc)
    return mtc, start_ms


def _before(seq, first, then):
    """*first* is sent, *then* is sent, and *first* comes before *then*."""
    assert first in seq and then in seq, (first, then, seq)
    assert seq.index(first) < seq.index(then), (first, then, seq)


# --------------------------------------------------------------------------- wrap


def test_wrap_mode_sends_loop_and_never_reanchors():
    cue, player = _cue(3), FakePlayer()
    mtc, start = _lifecycle(cue, player, on_reveal=lambda: player.ack("wrap", 1))
    osc = cue._osc
    run = osc.in_phase("run")
    tod = [v for p, v in run if p == "/start_tod"]
    assert len(tod) == 1 and isinstance(tod[0], int)  # whole ms, int32 (day-align §7.2)
    assert tod[0] == round(start) % loop_mode.DAY_MS
    assert ("/loop", [3, 19200, 48000]) in run
    _before(osc.paths("run"), "/start_tod", "/loop")  # the loop after the start
    assert "/offset" not in osc.paths() and "/mtcfollow" not in osc.paths("run")
    reveal = osc.paths("reveal")
    _before(reveal, "/start_tod", "/mtcfollow")
    _before(reveal, "/loop", "/mtcfollow")  # /loop applied before following starts
    assert ("/mtcfollow", 1) in osc.in_phase("reveal")
    # the passes: one /loop re-send per later pass, no offset, no /mtcfollow 0
    assert osc.in_phase("loop") == [("/loop", [3, 19200, 48000])] * 2
    assert cue._player_wraps is True and cue._wrap_fallback is False
    # the timeline on P, from the absolute instants (G20)
    base = loop_mode.tc_at(25, start).milliseconds_exact
    assert abs(cue._end_mtc.milliseconds_exact - (base + 3 * P_MS)) <= 40


def test_no_wrap_ack_within_the_timeout_falls_back_to_legacy_on_P():
    cue, player = _cue(5), FakePlayer()
    with patch.object(loop_mode, "WRAP_ACK_TIMEOUT_S", 0.5):
        _lifecycle(cue, player)
    assert cue._wrap_fallback is True and cue._player_wraps is False
    loop = cue._osc.in_phase("loop")
    paths = [p for p, _ in loop]
    _before(loop, ("/loop", [1]), ("/start_tod", loop[paths.index("/start_tod")][1]))
    after = paths[loop.index(("/loop", [1])) + 1 :]
    assert set(after) <= {"/start_tod", "/mtcfollow"} and "/loop" not in after
    assert loop[-1] == ("/mtcfollow", 0)  # legacy ends with /mtcfollow 0
    # the per-pass re-sends after the fallback are one P apart
    tods = [v for p, v in loop if p == "/start_tod"]
    assert len(tods) >= 2 and all(b - a == 400 for a, b in zip(tods, tods[1:]))


def test_an_off_ack_newer_than_the_wrap_falls_back():
    cue, player = _cue(4), FakePlayer()

    def acks():
        player.ack("wrap", 1)
        threading.Timer(0.5, lambda: player.ack("off", 2)).start()

    _lifecycle(cue, player, on_reveal=acks)
    assert cue._wrap_fallback is True
    assert ("/loop", [1]) in cue._osc.in_phase("loop")


def test_an_old_off_below_the_last_wrap_is_ignored():
    cue, player = _cue(3), FakePlayer()

    def acks():
        player.ack("off", 1)
        player.ack("wrap", 2)
        player.ack("off", 1)  # a receipt line written late, with an older ver

    _lifecycle(cue, player, on_reveal=acks)
    assert cue._wrap_fallback is False
    assert ("/loop", [1]) not in cue._osc.in_phase("loop")


def test_the_fallback_is_latched_for_the_go():
    cue, player = _cue(5), FakePlayer()
    with patch.object(loop_mode, "WRAP_ACK_TIMEOUT_S", 0.3):

        def late():
            time.sleep(0.8)
            player.ack("wrap", 7)  # would re-enable wrap mode: must not

        threading.Thread(target=late, daemon=True).start()
        _lifecycle(cue, player)
    assert cue._wrap_fallback is True and cue._player_wraps is False
    loop = cue._osc.in_phase("loop")
    i = loop.index(("/loop", [1]))
    assert ("/loop", [5, 19200, 48000]) not in loop[i:]  # no wrap re-send after it


# --------------------------------------------------------------------------- legacy


@pytest.mark.parametrize("why", ["once", "cuelist", "no_period"])
def test_a_capable_player_gets_loop_1_when_not_wrapping(why):
    cue = _cue(1 if why == "once" else 3, period=None if why == "no_period" else PERIOD)
    if why == "cuelist":
        cue._in_cuelist = True
    _lifecycle(cue, FakePlayer())
    osc = cue._osc
    assert ("/loop", [1]) in osc.in_phase("run")
    _before(osc.paths("run"), "/start_tod", "/loop")
    assert cue._wrap_requested is False
    assert osc.values("/loop") == [[1]]  # never a wrap request, never re-sent
    assert osc.in_phase("loop")[-1] == ("/mtcfollow", 0)
    assert "/offset" not in osc.paths()


def test_an_old_player_gets_no_loop_and_float_offsets_reanchored_on_P():
    cue = _cue(3)
    _lifecycle(cue, None)
    osc = cue._osc
    assert "/loop" not in osc.paths() and "/start_tod" not in osc.paths()
    run, reveal, loop = (
        [v for p, v in osc.in_phase(ph) if p == "/offset"]
        for ph in ("run", "reveal", "loop")
    )
    assert len(run) == 1 and isinstance(run[0], float)
    assert reveal == run  # the reveal re-asserts the same offset
    # one re-anchor per later pass, each one P further (re-anchored on P, not on
    # the stored 360 ms duration)
    assert [round(o - run[0]) for o in loop] == [-400, -800]
    assert osc.in_phase("loop")[-1] == ("/mtcfollow", 0)


def test_loop_varispeed_without_dayalign_keeps_wrap_mode_with_a_float_offset():
    # a feature player of before the day alignment (F0/F1): wrap mode is kept,
    # the start goes as /offset (day-align §7.3, E2 x F0/F1)
    cue, player = _cue(3), FakePlayer(caps=("loop", "varispeed"))
    mtc, start = _lifecycle(cue, player, on_reveal=lambda: player.ack("wrap", 1))
    osc = cue._osc
    assert "/start_tod" not in osc.paths()
    run = [v for p, v in osc.in_phase("run") if p == "/offset"]
    assert len(run) == 1 and isinstance(run[0], float) and run[0] == -start
    assert ("/loop", [3, 19200, 48000]) in osc.in_phase("run")
    assert cue._wrap_requested is True and cue._player_wraps is True


def test_dayalign_without_loop_varispeed_gets_start_tod_and_legacy_loops():
    cue, player = _cue(3), FakePlayer(caps=("dayalign",))
    _lifecycle(cue, player)
    osc = cue._osc
    assert "/loop" not in osc.paths() and "/offset" not in osc.paths()
    run = [v for p, v in osc.in_phase("run") if p == "/start_tod"]
    loop = [v for p, v in osc.in_phase("loop") if p == "/start_tod"]
    assert len(run) == 1 and [b - run[0] for b in loop] == [400, 800]


def test_an_abort_before_the_offset_leaves_no_wrap():
    cue = _cue(3)
    cue._osc = FakeOsc(fail={"/start_tod"})
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
