# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869fbyjzx: honest log lines when a cue is not armed at GO.

A GO that finds its cue still being armed (a pre-arm, an audio player still
starting) used to log "this should not happen, pre-arm may have failed.
Re-arming as fallback." It had not failed: it was in flight, and the GO waited
for it. The two sites — go() and the cue's own thread (go_threaded) — now say
which case it is, and report the wait from what arm() actually did.

True fallbacks keep "not loaded at go() time" / "not loaded at dispatch" and
"Re-arming as fallback": the harnesses and an acceptance criterion count them.
"""

import logging
import sys
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.modules.setdefault("cuemsutils.tools.Osc_nodes_hub", Mock())

from cuemsutils.tools.CTimecode import CTimecode  # noqa: E402

from cuemsengine.cues.CueHandler import CueHandler  # noqa: E402

HELD = "held by PreArm:abc for 0.3s"


def _cue(cid="c1"):
    return SimpleNamespace(
        id=cid,
        _local=True,
        enabled=True,
        loaded=False,
        post_go="pause",
        _go_generation=1,
    )


def _arm_that(waited_s=None, holder="PreArm:abc"):
    """An arm() stand-in that loads the cue and, when waited_s is given,
    reports a wait the way the real arm() does."""

    def arm(cue, init=False, walk=None, epoch=None, wait_report=None):
        if waited_s is not None and wait_report is not None:
            wait_report["waited_s"] = waited_s
            wait_report["holder"] = holder
        cue.loaded = True
        return True

    return MagicMock(side_effect=arm)


def _go_handler(in_flight, arm):
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._disarm_epoch = 0
    ch._chain_epoch = 0
    ch._last_stop_chain_epoch = 0
    ch._stamp_skipped_locked = MagicMock()
    ch._arm_ahead = MagicMock()
    ch.go_threaded = MagicMock()
    ch.describe_arm_in_flight = MagicMock(return_value=in_flight)
    ch.arm = arm
    return ch


def _go(ch, cue, chain_epoch=None):
    with patch("cuemsengine.cues.CueHandler.Thread") as thread:
        ch.go(cue, MagicMock(), 0.0, chain_epoch=chain_epoch)
    return thread


class TestGoSite:
    def test_a_fresh_go_on_an_arm_in_flight_waits_and_says_so(self, caplog):
        cue = _cue()
        ch = _go_handler(HELD, _arm_that(waited_s=0.41))
        with caplog.at_level(logging.INFO):
            _go(ch, cue)
        text = caplog.text
        assert f"is still being armed ({HELD}) at go() time" in text
        assert "waiting for the arm in progress" in text
        assert "waited 0.41s at go() time" in text
        assert "Re-arming as fallback" not in text
        assert "pre-arm may have failed" not in text

    def test_a_fresh_go_with_nothing_in_flight_is_a_fallback(self, caplog):
        cue = _cue()
        ch = _go_handler(None, _arm_that())
        with caplog.at_level(logging.INFO):
            _go(ch, cue)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "not loaded at go() time — no arm in flight" in r.getMessage()
            and "Re-arming as fallback" in r.getMessage()
            for r in warnings
        ), caplog.text
        assert "pre-arm may have failed" not in caplog.text

    def test_a_continuation_dispatches_and_does_not_claim_to_wait(self, caplog):
        cue = _cue()
        arm = _arm_that()
        ch = _go_handler(HELD, arm)
        with caplog.at_level(logging.INFO):
            _go(ch, cue, chain_epoch=1)
        assert "not armed yet at go() time — dispatching" in caplog.text
        assert "waited" not in caplog.text
        assert "Re-arming as fallback" not in caplog.text
        arm.assert_not_called()  # a continuation never arms in go()

    def test_the_arm_finished_before_this_go_looked(self, caplog):
        # in flight at the first look, but arm() found it loaded: no wait.
        cue = _cue()
        ch = _go_handler(HELD, _arm_that(waited_s=None))
        with caplog.at_level(logging.INFO):
            _go(ch, cue)
        assert "had finished before this call looked; no wait" in caplog.text

    def test_a_wait_the_first_look_missed_is_still_reported(self, caplog):
        # Nothing in flight at the first look (the WARNING), but arm() then
        # waited on an arm that started in between: the wait is reported.
        cue = _cue()
        ch = _go_handler(None, _arm_that(waited_s=0.2))
        with caplog.at_level(logging.INFO):
            _go(ch, cue)
        assert "Re-arming as fallback" in caplog.text
        assert "waited 0.20s at go() time" in caplog.text

    def test_the_same_arm_call_as_before(self):
        cue = _cue()
        arm = _arm_that()
        ch = _go_handler(None, arm)
        _go(ch, cue)
        arm.assert_called_once()
        args, kwargs = arm.call_args
        assert args == (cue,)
        assert kwargs["init"] is True and kwargs["epoch"] == 0
        assert isinstance(kwargs["wait_report"], dict)


class _FakeMtc:
    """MTC whose timeline advances by the duration of each patched sleep (as in
    test_dispatch_reorder.py), so go_threaded's waits terminate."""

    def __init__(self, ms=0.0):
        self.main_tc = SimpleNamespace(
            milliseconds_exact=float(ms),
            milliseconds_rounded=int(ms),
            framerate=25.0,
            frames=0,
        )

    def advance(self, seconds):
        ms = float(seconds) * 1000.0
        self.main_tc.milliseconds_exact += ms
        self.main_tc.milliseconds_rounded = int(self.main_tc.milliseconds_exact)
        self.main_tc.frames = int(self.main_tc.milliseconds_exact / 1000 * 25)


def _chain_cue(cid):
    """A continuation cue shaped like test_dispatch_reorder.py's _cue()."""
    return SimpleNamespace(
        id=cid,
        _local=True,
        enabled=True,
        loaded=False,
        post_go="go",
        prewait=CTimecode(start_seconds=0),
        postwait=CTimecode(start_seconds=0),
        _target_object=None,
        _stop_requested=False,
        _go_generation=1,
        _revealed=False,
        _start_mtc=None,
    )


def _dispatch_handler(in_flight, arm):
    """go_threaded on a continuation cue, as test_dispatch_reorder drives it."""
    ch = object.__new__(CueHandler)
    ch._lock = Lock()
    ch._armed_cues = []
    ch._armed_cues_set = set()
    ch._disarm_epoch = 0
    ch.communications_thread = MagicMock()
    ch.disarm = MagicMock()
    ch._arm_ahead = MagicMock()
    ch.go = MagicMock(return_value=None)
    ch._next_local_fire = MagicMock(return_value=(None, 0.0))
    ch.describe_arm_in_flight = MagicMock(return_value=in_flight)
    ch.arm = arm
    return ch


class TestDispatchSite:
    @staticmethod
    def _dispatch(ch, cue):
        mtc = _FakeMtc(0)
        c = _chain_cue(cue.id)
        with (
            patch("cuemsengine.cues.CueHandler.run_cue"),
            patch("cuemsengine.cues.CueHandler.reveal_cue"),
            patch("cuemsengine.cues.CueHandler.loop_cue"),
            patch("cuemsengine.cues.CueHandler.sleep", side_effect=mtc.advance),
        ):
            ch.go_threaded(c, mtc, 0.0, c._go_generation, 1)
        return c

    def test_an_arm_in_flight_is_waited_for(self, caplog):
        ch = _dispatch_handler(HELD, _arm_that(waited_s=0.36))
        with caplog.at_level(logging.INFO):
            self._dispatch(ch, _cue())
        assert f"is still being armed ({HELD}) at dispatch" in caplog.text
        assert "waited 0.36s at dispatch" in caplog.text
        assert "Re-arming as fallback" not in caplog.text

    def test_nothing_in_flight_is_a_fallback(self, caplog):
        ch = _dispatch_handler(None, _arm_that())
        with caplog.at_level(logging.INFO):
            self._dispatch(ch, _cue())
        assert "not loaded at dispatch — no arm in flight" in caplog.text
        assert "Re-arming as fallback" in caplog.text
