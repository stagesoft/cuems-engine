# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Pre-arm measurement lines (869f9wqpn follow-up).

Four INFO lines that say what a node holds armed and for how long, so the
pre-arm policy can be judged on data:

- ``Armed <type> <id> in <t> s``: one per published arm;
- ``Armed inventory after <where>: ...``: what is held right now, after every
  GO and at the end of every PreArm thread;
- ``Cue <id> started <t> s after it was armed``: at the reveal commit;
- ``Cue <id> disarmed after <t> s armed, never played (<reason>)``: an arm
  that bought nothing.

They change no behaviour. Design: cuems-RELATIONS
Plans/2026-10-01-engine-prearm-past-pauses-and-inventory.md (Part A).
"""

from __future__ import annotations

import sys
import threading
import time
import uuid
from threading import Lock
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.cues import ActionCue, AudioCue, DmxCue, VideoCue  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402

ARM_CUE = "cuemsengine.cues.CueHandler.arm_cue"
LOGGER = "cuemsengine.cues.CueHandler.Logger"
PLAYERS = "cuemsengine.cues.CueHandler.PLAYER_HANDLER"


def _handler() -> CueHandler:
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch.communications_thread = MagicMock()
    return ch


def _cue(post_go="pause"):
    """ActionCue: arm_cue() is a no-op for it, so no players are involved.
    Its own id: default-built cues can share one, and cues compare by id."""
    cue = ActionCue()
    cue.id = str(uuid.uuid4())
    cue.enabled = True
    cue.loaded = False
    cue._local = True
    cue.action_type = "enable"
    cue._action_target_object = None
    cue._target_object = None
    cue.post_go = post_go
    return cue


def _mtc(ms=0.0):
    mtc = MagicMock()
    mtc.main_tc.milliseconds_exact = float(ms)
    mtc.main_tc.milliseconds_rounded = int(ms)
    return mtc


def _infos(logger, needle):
    return [
        str(c.args[0]) for c in logger.info.call_args_list if needle in str(c.args[0])
    ]


def _arm(ch, cue, **kwargs):
    with patch(ARM_CUE):
        return ch.arm(cue, init=True, **kwargs)


def _go(ch, cue):
    """go() up to its commit, without spawning the cue's thread."""
    ch._arm_ahead = MagicMock()
    with patch.object(CueHandler, "go_threaded"):
        return ch.go(cue, _mtc())


def _run_threaded(ch, cue):
    """go_threaded for a dispatched cue, players patched out."""
    cue._stop_requested = getattr(cue, "_stop_requested", False)
    gen = getattr(cue, "_go_generation", 0)
    with (
        patch("cuemsengine.cues.CueHandler.run_cue"),
        patch("cuemsengine.cues.CueHandler.reveal_cue"),
        patch("cuemsengine.cues.CueHandler.loop_cue"),
        patch(PLAYERS),
    ):
        ch.go_threaded(cue, _mtc(), 0.0, gen, 1, False, arm_epoch=ch.arm_epoch())


class TestArmTime:
    def test_a_published_arm_logs_its_time(self):
        ch = _handler()
        cue = _cue()
        with patch(LOGGER) as logger:
            assert _arm(ch, cue) is True
        lines = _infos(logger, "Armed ActionCue")
        assert len(lines) == 1
        assert lines[0].startswith(f"Armed ActionCue {cue.id} in ")
        assert lines[0].endswith(" s")

    def test_an_abandoned_arm_logs_no_arm_time(self):
        ch = _handler()
        cue = _cue()
        with (
            patch(LOGGER) as logger,
            patch(ARM_CUE, side_effect=lambda c: ch.stop_all_cues()),
            patch(PLAYERS),
        ):
            assert ch.arm(cue, init=True) is False
        assert _infos(logger, "Armed ActionCue") == []

    def test_publish_stamps_the_cue(self):
        ch = _handler()
        cue = _cue()
        before = time.monotonic()
        _arm(ch, cue)
        assert before <= cue._armed_at <= time.monotonic()
        assert cue._ever_played is False

    def test_a_re_arm_resets_the_stamps(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        first = cue._armed_at
        _go(ch, cue)
        assert cue._ever_played is True
        with patch(PLAYERS):
            ch.disarm(cue, reason="cue_end")
        time.sleep(0.002)
        _arm(ch, cue)
        assert cue._ever_played is False
        assert cue._armed_at > first


class TestStartedAfterArmed:
    def test_go_marks_the_cue_played_at_its_commit(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        assert _go(ch, cue) is not None
        assert cue._ever_played is True

    def test_a_refused_dispatch_does_not_mark_it_played(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        stale = ch.arm_epoch()
        ch.stop_all_cues()
        with patch.object(CueHandler, "go_threaded"):
            assert ch.go(cue, _mtc(), arm_epoch=stale) is None
        assert cue._ever_played is False

    def test_the_reveal_logs_how_long_the_cue_was_armed(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        cue._armed_at = time.monotonic() - 2.5
        _go(ch, cue)
        with patch(LOGGER) as logger:
            _run_threaded(ch, cue)
        lines = _infos(logger, "after it was armed")
        assert len(lines) == 1
        assert lines[0].startswith(f"Cue {cue.id} started 2.")
        assert lines[0].endswith(" s after it was armed")

    def test_a_cue_stopped_before_its_reveal_logs_nothing(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        _go(ch, cue)
        cue._stop_requested = True
        with patch(LOGGER) as logger:
            _run_threaded(ch, cue)
        assert _infos(logger, "after it was armed") == []


class TestNeverPlayed:
    def test_disarming_a_never_dispatched_cue_logs_the_waste(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        cue._armed_at = time.monotonic() - 61.0
        with patch(LOGGER) as logger, patch(PLAYERS):
            ch.disarm(cue, reason="load")
        lines = _infos(logger, "never played")
        assert len(lines) == 1
        assert lines[0].startswith(f"Cue {cue.id} disarmed after 61.")
        assert lines[0].endswith(" s armed, never played (load)")

    def test_a_played_cue_logs_nothing(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        _go(ch, cue)
        with patch(LOGGER) as logger, patch(PLAYERS):
            ch.disarm(cue, reason="stop")
        assert _infos(logger, "never played") == []

    def test_cue_end_logs_nothing(self):
        ch = _handler()
        cue = _cue()
        _arm(ch, cue)
        with patch(LOGGER) as logger, patch(PLAYERS):
            ch.disarm(cue, reason="cue_end")
        assert _infos(logger, "never played") == []

    def test_an_abandoned_arm_logs_nothing(self):
        ch = _handler()
        cue = _cue()
        with (
            patch(LOGGER) as logger,
            patch(ARM_CUE, side_effect=lambda c: ch.stop_all_cues()),
            patch(PLAYERS),
        ):
            ch.arm(cue, init=True)
            ch.disarm_all(reason="stop")
        assert _infos(logger, "never played") == []

    def test_disarm_all_logs_each_never_played_cue(self):
        ch = _handler()
        a, b, played = _cue(), _cue(), _cue()
        for cue in (a, b, played):
            _arm(ch, cue)
        _go(ch, played)
        with patch(LOGGER) as logger, patch(PLAYERS):
            ch.disarm_all(reason="load")
        lines = _infos(logger, "never played")
        assert len(lines) == 2
        assert {line.split(" ")[1] for line in lines} == {str(a.id), str(b.id)}


def _loaded(cue, playing=False, layers=()):
    cue.loaded = True
    cue._playing = playing
    if layers:
        cue._layer_ids = list(layers)
    return cue


class TestInventory:
    def _held(self):
        ch = _handler()
        cues = [
            _loaded(VideoCue(), playing=True, layers=("l1", "l2")),
            _loaded(VideoCue(), layers=("l3",)),
            _loaded(AudioCue()),
            _loaded(DmxCue()),
            _loaded(_cue()),
        ]
        registered_only = ActionCue()  # a non-init arm: listed, not loaded
        registered_only.loaded = False
        for cue in cues + [registered_only]:
            ch._armed_cues.append(cue)
            ch._armed_cues_set.add(cue.id)
        return ch

    def test_counts_by_type_layers_and_state(self):
        inv = self._held().armed_inventory()
        assert inv == {
            "cues": 5,
            "video": 2,
            "layers": 3,
            "audio": 1,
            "dmx": 1,
            "other": 1,
            "playing": 1,
            "idle": 4,
        }

    def test_the_log_line(self):
        ch = self._held()
        with patch(LOGGER) as logger:
            ch.log_armed_inventory("GO")
        assert _infos(logger, "Armed inventory") == [
            "Armed inventory after GO: 5 cues (video 2 cues / 3 layers, "
            "audio 1 players, dmx 1, other 1); playing 1; idle 4"
        ]

    def test_an_empty_handler(self):
        assert _handler().armed_inventory()["cues"] == 0

    def test_a_failure_never_reaches_the_caller(self):
        ch = _handler()
        ch._armed_cues = None  # anything that makes the count raise
        with patch(LOGGER) as logger:
            ch.log_armed_inventory("GO")
        logger.warning.assert_called_once()


def test_the_inventory_reads_under_the_lock():
    """A GO's thread publishing while the inventory counts must not make it
    iterate a list that changes size."""
    ch = _handler()
    seen = []
    real_lock = ch._lock

    class Spy:
        def __enter__(self):
            seen.append(threading.current_thread().name)
            return real_lock.__enter__()

        def __exit__(self, *a):
            return real_lock.__exit__(*a)

    ch._lock = Spy()
    ch.armed_inventory()
    assert seen, "armed_inventory did not take the handler lock"
