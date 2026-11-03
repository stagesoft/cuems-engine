# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""What a cuems-audioplayer announces on stdout (plan 869ejxng3 + 1amfwm7e6cw
rev 3.14, §4.2): the CAPS line and the LOOP acks, as ``Player`` keeps them —
the line with the highest ``ver`` wins, ``last_wrap_ver`` tracks the newest
``wrap`` so an older ``off`` never counts — reset per subprocess run.
"""

import sys

from cuemsengine.players.Player import LoopAck, Player, parse_caps, parse_loop_ack

SLUG = b"[Cuems:d0123] "


def test_parse_caps():
    assert parse_caps(SLUG + b"[OK] CAPS: loop varispeed\n") == {"loop", "varispeed"}
    assert parse_caps(b"something else") == frozenset()


def test_parse_loop_ack():
    assert parse_loop_ack(SLUG + b"[OK] LOOP 4 3 576512 48000 wrap\n") == LoopAck(
        4, 3, 576512, 48000, "wrap"
    )
    assert parse_loop_ack(SLUG + b"[OK] LOOP 1 1 0 0 once") == LoopAck(
        1, 1, 0, 0, "once"
    )
    for bad in (
        b"[OK] LOOP 1 2 3",
        b"[OK] LOOP a b c d wrap",
        b"[OK] LOOP 1 2 3 4 maybe",
    ):
        assert parse_loop_ack(bad) is None


class _P(Player):
    def run(self):
        pass


def test_the_highest_ver_wins_and_off_is_judged_against_the_last_wrap():
    p = _P()
    p.note_line(SLUG + b"[OK] LOOP 0 3 1 1 pending")
    p.note_line(SLUG + b"[OK] LOOP 2 3 1 1 wrap")
    p.note_line(SLUG + b"[OK] LOOP 1 3 1 1 off")  # an older line written late
    assert p.loop_ack.mode == "wrap" and p.last_wrap_ver == 2
    p.note_line(SLUG + b"[OK] LOOP 3 3 1 1 off")
    assert p.loop_ack.mode == "off" and p.loop_ack.ver > p.last_wrap_ver


def test_the_stdout_reader_records_caps_and_acks_and_resets_per_run():
    script = (
        "import sys,time;"
        "w=sys.stdout.buffer.write;"
        "w(b'[s] [OK] CAPS: loop varispeed\\n');"
        "w(b'[s] [OK] RUNNING!\\n');"
        "w(b'[s] [OK] LOOP 0 3 19200 48000 pending\\n');"
        "w(b'[s] [OK] LOOP 1 3 19200 48000 wrap\\n');"
        "sys.stdout.flush()"
    )
    p = _P()
    p.call_subprocess([sys.executable, "-c", script])
    assert p.ready.is_set()
    assert p.caps == {"loop", "varispeed"}
    assert p.loop_ack == LoopAck(1, 3, 19200, 48000, "wrap")
    p.call_subprocess(
        [sys.executable, "-c", "print('[s] [OK] RUNNING!')"]
    )  # an old player
    assert p.caps == frozenset() and p.loop_ack is None and p.last_wrap_ver == -1
