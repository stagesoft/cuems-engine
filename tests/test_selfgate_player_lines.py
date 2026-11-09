# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.1d-g, §5: the stdout lines of a ``selfgate`` cuems-audioplayer
as the engine's reader parses them, the CAPS predicate, and the per-player
state the engine keeps (cuems-RELATIONS
Plans/2026-11-03-audio-first-pass-head-869feynrj.md).

Wire formats, from cuems-audioplayer 9e207cc (playercore.cpp):
``[<slug>] [OK] START <start_ms_mod_day> <target_samples_signed> <file_rate>``,
``[<slug>] [OK] CANCEL <seq> <hold|play|pastend> <ms_of_output>``,
``[<slug>] [OK] LATENCY <frames> <rate> <period_frames>[ override]``.
"""

import pytest

from cuemsengine.cues import loop_mode
from cuemsengine.players.AudioPlayer import AudioPlayer
from cuemsengine.players.Player import (
    CancelAck,
    LatencyLine,
    Player,
    StartLine,
    parse_cancel,
    parse_latency,
    parse_start,
)

SLUG = b"[Cuems:d0123456789abcdef0123456789abcdef]"


def _player():
    return AudioPlayer(port=0, path="cuems-audioplayer", args="", media="m.wav")


class TestParsers:
    def test_start_line(self):
        s = parse_start(SLUG + b" [OK] START 600080 -480 48000\n")
        assert s == StartLine(600080, -480, 48000)
        assert s.late_ms == 0.0

    def test_start_line_late_in_ms(self):
        s = parse_start(SLUG + b" [OK] START 600080 2205 44100\n")
        assert s.target == 2205 and s.late_ms == pytest.approx(50.0)
        assert s.snap is False

    def test_start_line_snap_field(self):
        # 869feynrj step 5: a trailing "snap" = late but started at sample 0
        s = parse_start(SLUG + b" [OK] START 600080 57 44100 snap\n")
        assert s == StartLine(600080, 57, 44100, True)
        assert s.late_ms == pytest.approx(57000 / 44100)
        # an unknown 4th field is ignored, as before
        assert parse_start(SLUG + b" [OK] START 600080 57 44100 other\n").snap is False

    @pytest.mark.parametrize("state", ["hold", "play", "pastend"])
    def test_cancel_line(self, state):
        a = parse_cancel(SLUG + f" [OK] CANCEL 7 {state} 23\n".encode())
        assert a == CancelAck(7, state, 23)

    def test_cancel_line_unknown_state_is_not_an_ack(self):
        assert parse_cancel(SLUG + b" [OK] CANCEL 7 maybe 23\n") is None

    def test_latency_line(self):
        lat = parse_latency(SLUG + b" [OK] LATENCY 1536 48000 512\n")
        assert lat == LatencyLine(1536, 48000, 512, False)
        # latency + one JACK period (§4.5d, review 4 m1): 32 + 10.7 ms
        assert lat.out_latency_ms == pytest.approx(42.667, abs=1e-3)

    def test_latency_line_override(self):
        lat = parse_latency(SLUG + b" [OK] LATENCY 1680 48000 512 override\n")
        assert lat.override is True and lat.frames == 1680

    @pytest.mark.parametrize(
        "line",
        [
            b"[x] [OK] START 1 2\n",
            b"[x] [OK] START a b c\n",
            b"[x] [OK] CANCEL x play 1\n",
            b"[x] [OK] LATENCY 1536 0 512\n",
            b"[x] [OK] RUNNING!\n",
        ],
    )
    def test_malformed_lines_are_ignored(self, line):
        assert parse_start(line) is None
        assert parse_cancel(line) is None
        assert parse_latency(line) is None


class TestCaps:
    def test_selfgate_token(self):
        p = _player()
        p.note_line(SLUG + b" [OK] CAPS: loop varispeed dayalign selfgate\n")
        assert loop_mode.player_selfgate(p) is True
        assert loop_mode.player_capable(p) and loop_mode.player_dayalign(p)

    def test_older_player_is_not_selfgate(self):
        p = _player()
        p.note_line(SLUG + b" [OK] CAPS: loop varispeed dayalign\n")
        assert loop_mode.player_selfgate(p) is False
        assert loop_mode.player_selfgate(None) is False


class TestNoteLine:
    def test_lines_reach_the_hook_and_the_player(self, monkeypatch):
        seen = []
        monkeypatch.setattr(Player, "selfgate_hook", lambda p, k, v: seen.append(k))
        p = _player()
        p.note_line(SLUG + b" [OK] LATENCY 1536 48000 512\n")
        p.note_line(SLUG + b" [OK] START 1000 -10 48000\n")
        p.note_line(SLUG + b" [OK] CANCEL 1 hold 0\n")
        assert seen == ["latency", "start", "cancel"]
        assert p.latency.frames == 1536
        assert p.last_start.target == -10

    def test_a_raising_hook_never_reaches_the_reader(self, monkeypatch):
        def boom(*a):
            raise RuntimeError("boom")

        monkeypatch.setattr(Player, "selfgate_hook", boom)
        _player().note_line(SLUG + b" [OK] START 1000 -10 48000\n")  # no raise

    def test_loop_lines_still_parse(self, monkeypatch):
        monkeypatch.setattr(Player, "selfgate_hook", None)
        p = _player()
        p.note_line(SLUG + b" [OK] LOOP 2 3 576512 48000 wrap\n")
        assert p.loop_ack.mode == "wrap"


class TestPlayerState:
    def test_defaults(self):
        p = _player()
        assert p.may_follow is False
        assert p.cancel_seq == 0 and p.cancel_records == {}
        assert p.follow_pass is None and p.fade_deadline == 0.0

    def test_reset_per_run(self):
        p = _player()
        p.may_follow = True
        p.cancel_seq = 4
        p.cancel_records[4] = object()
        p.reset_selfgate_state()
        assert p.may_follow is False
        assert p.cancel_seq == 0 and p.cancel_records == {}
