# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The cue start on the wire (cuems-RELATIONS
Plans/2026-10-25-mtc-day-align-24h-wrap.md §7.2, §7.4b): ``/start_tod`` = the
start as MTC position modulo 24 h in whole ms (rounded first, then taken modulo
the day) to a player whose CAPS line carries ``dayalign``, the float ``/offset``
(= -start) to every other player; ``dayalign`` is a predicate of its own,
independent of the wrap/varispeed capability."""

from types import SimpleNamespace

import pytest
from pyossia import ValueType

from cuemsengine.cues import loop_mode
from cuemsengine.osc.endpoints import OSC_AUDIOPLAYER_CONF
from cuemsengine.players.Player import parse_caps

DAY = 86_400_000


@pytest.mark.parametrize(
    "start_ms, tod",
    [
        (0.0, 0),
        (321_040.0, 321_040),  # 00:05:21.040
        (DAY - 1.0, DAY - 1),
        (DAY - 0.4, 0),  # rounds to one day, then the modulo: 0
        (DAY - 0.6, DAY - 1),
        (86_399_999.6, 0),  # the plan's edge: round first, then mod
        (DAY + 40.0, 40),  # day 1 + 40 ms
        (30 * DAY + 3_600_000.0, 3_600_000),  # 30 days of engine MTC
        (30 * DAY + DAY - 0.2, 0),
    ],
)
def test_round_then_mod(start_ms, tod):
    v = loop_mode.start_tod(start_ms)
    assert v == tod and isinstance(v, int)
    assert 0 <= v < DAY  # always fits an int32


def test_thirty_days_never_overflows_int32():
    for k in range(0, 40):
        assert 0 <= loop_mode.start_tod(k * DAY + 12_345.4) < 2**31


def _cue(dayalign):
    return SimpleNamespace(_audio_dayalign=dayalign)


def test_key_choice_dayalign_gets_start_tod():
    assert loop_mode.start_message(_cue(True), DAY + 600_080.0) == (
        "/start_tod",
        600_080,
    )


def test_key_choice_otherwise_float_offset():
    for c in (_cue(False), SimpleNamespace()):
        key, value = loop_mode.start_message(c, DAY + 600_080.0)
        assert key == "/offset" and value == -(DAY + 600_080.0)


def test_dayalign_is_independent_of_loop_varispeed():
    def player(*caps):
        return SimpleNamespace(caps=frozenset(caps))

    assert loop_mode.player_dayalign(player("loop", "varispeed", "dayalign"))
    assert loop_mode.player_capable(player("loop", "varispeed", "dayalign"))
    assert not loop_mode.player_dayalign(player("loop", "varispeed"))
    assert loop_mode.player_capable(player("loop", "varispeed"))
    assert loop_mode.player_dayalign(player("dayalign"))
    assert not loop_mode.player_capable(player("dayalign"))
    assert not loop_mode.player_dayalign(None)
    assert not loop_mode.player_dayalign(SimpleNamespace(caps=["dayalign"]))


def test_the_caps_line_of_a_phase_2_player():
    caps = parse_caps(b"[d1] [OK] CAPS: loop varispeed dayalign\n")
    assert caps == {"loop", "varispeed", "dayalign"}
    assert loop_mode.player_dayalign(SimpleNamespace(caps=caps))


def test_offset_i_is_gone_and_start_tod_is_an_int_without_the_filter():
    assert "/offset_i" not in OSC_AUDIOPLAYER_CONF
    conf = OSC_AUDIOPLAYER_CONF["/start_tod"]
    assert conf[0] == ValueType.Int and conf[3] is False
    assert OSC_AUDIOPLAYER_CONF["/offset"][0] == ValueType.Float
