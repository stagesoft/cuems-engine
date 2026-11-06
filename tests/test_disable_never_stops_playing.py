# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj S0-21 (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-
869feynrj.md §12, Q-S0-A = (A), Ion 2026-11-05): no disable path stops a
playing cue -- a disable takes effect from the next round. The two leaks of
that design, one test each:

- a CueList child never got a playing mark (children bypass go()), so
  disabling a playing CueList disarmed -- cut -- its child
  (0a-0c-inventory row 15);
- arm() disarmed a loaded, disabled cue even while it played (row 21).
"""

import importlib
import uuid
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cuemsutils.cues import AudioCue, CueList
from cuemsutils.tools.CTimecode import CTimecode

from cuemsengine.cues.CueHandler import CueHandler


class _Mtc:
    def __init__(self, ms):
        self.main_tc = SimpleNamespace(
            milliseconds_exact=float(ms), framerate=25, frames=int(ms // 40)
        )

    def advance(self, seconds):
        self.main_tc.milliseconds_exact += float(seconds) * 1000.0


def _audio():
    cue = AudioCue(
        {
            "id": str(uuid.uuid4()),
            "name": "child",
            "Media": {
                "file_name": "a.wav",
                "id": str(uuid.uuid4()),
                "duration": "00:00:01.000",
            },
        }
    )
    cue._local = True
    cue.loaded = True
    return cue


def _cuelist(child):
    cl = CueList({"id": str(uuid.uuid4()), "name": "cl", "contents": [child]})
    cl._local = True
    cl.loaded = True
    cl.post_go = "pause"
    cl._target_object = None
    cl._stop_requested = False
    cl._go_generation = 1
    cl._revealed = False
    return cl


def _ch():
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    ch.disarm = MagicMock()
    ch.go = MagicMock(return_value=None)
    ch._next_local_fire = MagicMock(return_value=(None, 0.0))
    ch._arm_ahead = MagicMock()
    return ch


def _play_cuelist(ch, cl):
    """One pass of the CueList, its child set up and revealed, as go_threaded
    runs it (the players patched out)."""
    mtc = _Mtc(1000.0)

    def setup(c, m, start_ms):
        child = c.contents[0]
        child._start_mtc = CTimecode(framerate=25, start_seconds=start_ms / 1000)

    with (
        patch("cuemsengine.cues.CueHandler.run_cue", side_effect=setup),
        patch("cuemsengine.cues.CueHandler.reveal_cue"),
        patch("cuemsengine.cues.CueHandler.loop_cue"),
        patch("cuemsengine.cues.CueHandler.blank_cue"),
        patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
    ):
        ch.go_threaded(cl, mtc, frozen_mtc_ms=1000.0, go_gen=1)


class TestCueListChildIsPlaying:
    def test_the_pass_marks_its_child_playing_and_revealed(self):
        ch = _ch()
        child = _audio()
        cl = _cuelist(child)
        _play_cuelist(ch, cl)
        assert child._playing is True and child._revealed is True

    def test_disabling_a_playing_cuelist_leaves_its_child_alone(self):
        ch = _ch()
        child = _audio()
        cl = _cuelist(child)
        _play_cuelist(ch, cl)
        ch.disarm.reset_mock()  # the parent's own end-of-pass disarm
        ch._armed_cues = [cl, child]
        ch._armed_cues_set = {cl.id, child.id}
        cl._playing = True
        NE = importlib.import_module("cuemsengine.NodeEngine")
        node = object.__new__(NE.NodeEngine)
        node.next_cue_pointer = None
        with patch.object(NE, "CUE_HANDLER", ch):
            node._apply_cue_enabled_side_effects(cl, False)
        ch.disarm.assert_not_called()
        assert child._stop_requested is not True
        assert child._playing is True

    def test_a_stopped_pass_marks_nothing(self):
        ch = _ch()
        child = _audio()
        cl = _cuelist(child)
        cl._stop_requested = True
        _play_cuelist(ch, cl)
        assert getattr(child, "_playing", False) is not True


class TestArmNeverDisarmsAPlayingCue:
    def _cue(self, playing):
        return SimpleNamespace(
            id=str(uuid.uuid4()),
            loaded=True,
            enabled=False,
            _local=True,
            _playing=playing,
            post_go="pause",
            _target_object=None,
        )

    def test_a_playing_disabled_cue_survives_an_arm(self):
        ch = _ch()
        cue = self._cue(playing=True)
        assert ch.arm(cue, init=True) is True
        ch.disarm.assert_not_called()

    def test_an_idle_disabled_cue_is_still_disarmed(self):
        ch = _ch()
        cue = self._cue(playing=False)
        assert ch.arm(cue, init=True) is False
        ch.disarm.assert_called_once_with(cue, reason="disabled")
