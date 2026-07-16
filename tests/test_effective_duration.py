# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Unit tests for CueHandler._effective_duration_ms (prewait + body + postwait).

Regression guard for the DMX fade-unit bug: fadein_time/fadeout_time are stored
in MILLISECONDS (authoritative: run_dmxCue reads fadein_ms then fade_time =
fadein_ms / 1000), so _effective_duration_ms must NOT multiply them by 1000.
Before the fix a chained 1 s DMX fade contributed 1_000_000 ms to the timeline
sum, scheduling the rest of a post_go='go' chain ~16.7 min late.
"""
import sys
from unittest.mock import Mock

# Match the repo's test convention (avoid the OSC hub import at collection time).
sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import ActionCue, AudioCue, DmxCue, VideoCue  # noqa: E402
from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402


def _dmx(fadein_ms=0, fadeout_ms=0, pre="00:00:00.000", post="00:00:00.000"):
    cue = Mock(spec=DmxCue)
    cue.fadein_time = fadein_ms
    cue.fadeout_time = fadeout_ms
    cue.prewait = CTimecode(pre)
    cue.postwait = CTimecode(post)
    return cue


class TestEffectiveDurationDmx:
    def test_dmx_fade_is_milliseconds_not_seconds(self):
        # 1 s fade == fadein_time 1000 ms -> contributes 1000 ms (NOT 1_000_000).
        assert CueHandler._effective_duration_ms(_dmx(fadein_ms=1000)) == 1000.0

    def test_dmx_fade_in_plus_out(self):
        assert (
            CueHandler._effective_duration_ms(_dmx(fadein_ms=1500, fadeout_ms=500))
            == 2000.0
        )

    def test_dmx_fade_plus_prewait_postwait(self):
        # pre 2 s + fade 1 s + post 5 s == 8000 ms
        cue = _dmx(fadein_ms=1000, pre="00:00:02.000", post="00:00:05.000")
        assert CueHandler._effective_duration_ms(cue) == 8000.0

    def test_dmx_zero_fade_only_waits(self):
        cue = _dmx(fadein_ms=0, post="00:00:03.000")
        assert CueHandler._effective_duration_ms(cue) == 3000.0

    def test_chained_dmx_sum_is_sane(self):
        # Three chained 1 s-fade DMX cues must sum to 3000 ms, not 3_000_000.
        cues = [_dmx(fadein_ms=1000) for _ in range(3)]
        total = sum(CueHandler._effective_duration_ms(c) for c in cues)
        assert total == 3000.0


class TestEffectiveDurationActionAndWaits:
    def test_action_body_zero_waits_count(self):
        cue = Mock(spec=ActionCue)
        cue.prewait = CTimecode("00:00:00.000")
        cue.postwait = CTimecode("00:00:04.000")
        # ActionCue body == 0 -> only postwait
        assert CueHandler._effective_duration_ms(cue) == 4000.0
