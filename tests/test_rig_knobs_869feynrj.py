# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj step 5 (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-
869feynrj.md §7.2): the rig-row test knobs, in tools/test_knobs.py's framework
(inert without CUEMS_TEST_KNOBS=1, announced once at start).

    CUEMS_TEST_GO_PHASE_SWEEP=<start>:<step>      R1, controller
    CUEMS_TEST_FORCE_LEAD_MS=<ms>                 R15 / R16, controller
    CUEMS_TEST_HOLD_COMMAND_LOCK_MS=<ms>          R10, node
    CUEMS_TEST_CANCEL_AT=<action>:<offset_ms>     R4, node
    CUEMS_TEST_DROP_OSC=/cancelstart:1 | /mtcfollow:1   R5 (existing knob)
"""

import importlib
import socket
import struct
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyossia
import pytest
from cuemsutils.cues import AudioCue
from cuemsutils.tools.CTimecode import CTimecode

from cuemsengine.cues import go_lead
from cuemsengine.tools import test_knobs

KNOBS = (
    "CUEMS_TEST_KNOBS",
    "CUEMS_TEST_DROP_OSC",
    "CUEMS_TEST_PROBE_BUDGET_S",
    "CUEMS_TEST_FORCE_PERIOD",
    "CUEMS_TEST_GO_PHASE_SWEEP",
    "CUEMS_TEST_FORCE_LEAD_MS",
    "CUEMS_TEST_HOLD_COMMAND_LOCK_MS",
    "CUEMS_TEST_CANCEL_AT",
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for n in KNOBS:
        monkeypatch.delenv(n, raising=False)
    test_knobs.reset_for_tests()
    yield
    test_knobs.reset_for_tests()


@pytest.fixture
def knobs(monkeypatch):
    def set_(**env):
        monkeypatch.setenv("CUEMS_TEST_KNOBS", "1")
        for k, v in env.items():
            monkeypatch.setenv(f"CUEMS_TEST_{k}", v)

    return set_


class TestFramework:
    def test_inert_without_the_master_switch(self, monkeypatch):
        monkeypatch.setenv("CUEMS_TEST_GO_PHASE_SWEEP", "0:7")
        monkeypatch.setenv("CUEMS_TEST_FORCE_LEAD_MS", "250")
        monkeypatch.setenv("CUEMS_TEST_HOLD_COMMAND_LOCK_MS", "300")
        monkeypatch.setenv("CUEMS_TEST_CANCEL_AT", "stop:-40")
        assert test_knobs.go_phase_next() is None
        assert test_knobs.forced_lead_ms() is None
        assert test_knobs.hold_command_lock_ms() is None
        assert test_knobs.cancel_at() is None

    def test_parsing(self, knobs):
        knobs(
            GO_PHASE_SWEEP="38:5",
            FORCE_LEAD_MS="10",
            HOLD_COMMAND_LOCK_MS="150",
            CANCEL_AT="actionpause:-120.5",
        )
        assert [test_knobs.go_phase_next() for _ in range(3)] == [38.0, 3.0, 8.0]
        assert test_knobs.forced_lead_ms() == 10.0
        assert test_knobs.hold_command_lock_ms() == 150.0
        # (action, offset, k, len): the single-offset form is a list of one
        assert test_knobs.cancel_at() == ("actionpause", -120.5, 1, 1)
        assert test_knobs.cancel_at() == ("actionpause", -120.5, 1, 1)

    def test_a_list_of_offsets_is_used_in_turn_one_per_go(self, knobs):
        """The n-th GO uses offset[n mod len], as the phase sweep counts."""
        knobs(CANCEL_AT="stop:-200,-45,0,30")
        got = [test_knobs.cancel_at() for _ in range(5)]
        assert got == [
            ("stop", -200.0, 1, 4),
            ("stop", -45.0, 2, 4),
            ("stop", 0.0, 3, 4),
            ("stop", 30.0, 4, 4),
            ("stop", -200.0, 1, 4),
        ]

    @pytest.mark.parametrize(
        "name, value",
        [
            ("GO_PHASE_SWEEP", "x:1"),
            ("FORCE_LEAD_MS", "-5"),
            ("HOLD_COMMAND_LOCK_MS", "abc"),
            ("CANCEL_AT", "explode:10"),
            ("CANCEL_AT", "stop"),
            ("CANCEL_AT", "stop:-40,x"),
            ("CANCEL_AT", "stop:"),
        ],
    )
    def test_a_bad_value_is_ignored(self, knobs, name, value):
        knobs(**{name: value})
        assert test_knobs.go_phase_next() is None
        assert test_knobs.forced_lead_ms() is None
        assert test_knobs.hold_command_lock_ms() is None
        assert test_knobs.cancel_at() is None

    def test_announce_names_them(self, knobs, monkeypatch):
        knobs(GO_PHASE_SWEEP="0:7", CANCEL_AT="stop:10")
        seen = []
        monkeypatch.setattr(
            test_knobs.Logger, "warning", lambda m, *a, **k: seen.append(m)
        )
        test_knobs.announce()
        assert len(seen) == 1
        assert "CUEMS_TEST_GO_PHASE_SWEEP=0:7" in seen[0]
        assert "CUEMS_TEST_CANCEL_AT=stop:10" in seen[0]


class _Clock:
    """An interpolated MTC that moves by each patched sleep."""

    def __init__(self, ms):
        self.ms = float(ms)

    def __call__(self):
        return self.ms

    def sleep(self, s):
        self.ms += s * 1000.0


class TestGoPhase:
    """R1: the press lands on a set phase of the 40 ms frame, advancing per GO."""

    def test_waits_for_the_phase(self, knobs):
        knobs(GO_PHASE_SWEEP="7:5")
        clock = _Clock(1013.0)
        with patch.object(test_knobs, "sleep", side_effect=clock.sleep):
            with patch.object(test_knobs.Logger, "warning") as warn:
                assert test_knobs.wait_for_phase(clock) == 7.0
        assert clock.ms % 40.0 == pytest.approx(7.0)
        assert clock.ms - 1013.0 < 40.0
        assert "TEST KNOB: GO phase 7.0 ms" in str(warn.call_args)
        with patch.object(test_knobs, "sleep", side_effect=clock.sleep):
            assert test_knobs.wait_for_phase(clock) == 12.0
        assert clock.ms % 40.0 == pytest.approx(12.0)

    def test_already_on_the_phase_does_not_wait_a_frame(self, knobs):
        knobs(GO_PHASE_SWEEP="13:1")
        clock = _Clock(1013.0)
        with patch.object(test_knobs, "sleep", side_effect=clock.sleep):
            test_knobs.wait_for_phase(clock)
        assert clock.ms == pytest.approx(1013.0)

    def test_no_knob_no_wait(self):
        clock = _Clock(1013.0)
        with patch.object(test_knobs, "sleep") as sleep:
            assert test_knobs.wait_for_phase(clock) is None
        sleep.assert_not_called()


def _controller(interp_clock):
    from cuemsengine.ControllerEngine import ControllerEngine

    c = object.__new__(ControllerEngine)
    c._required_nodes = set()
    c._adopted_nodes = set()
    c._run_seq = 7
    c.script = MagicMock()
    c.get_status = MagicMock(return_value="yes")
    c.set_status = MagicMock()
    c.mtc_listener = MagicMock()
    c.mtc_listener.is_receiving.return_value = True
    c.mtc_listener.interpolated_ms.side_effect = interp_clock
    return c


def _go(c):
    with patch.object(c, "_forward_command_to_nodes") as fwd:
        c.go_script(None)
    return fwd.call_args.args[1]


class TestControllerKnobs:
    def test_the_press_is_read_after_the_phase_wait(self, knobs):
        knobs(GO_PHASE_SWEEP="21:0")
        clock = _Clock(5003.0)
        c = _controller(clock)
        with patch.object(test_knobs, "sleep", side_effect=clock.sleep):
            value = _go(c)
        # the press is read after the wait: 5003 -> 5021, phase 21 of its frame
        assert clock.ms == pytest.approx(5021.0)
        assert value["go_mtc_ms"] == go_lead.ceil_frame(5021.0 + value["lead_ms"])

    @pytest.mark.parametrize("forced", [10.0, 250.0, 300.0])
    def test_a_forced_lead_rides_in_the_payload(self, knobs, forced):
        knobs(FORCE_LEAD_MS=str(forced))
        c = _controller(_Clock(5003.0))
        value = _go(c)
        assert value["lead_ms"] == forced
        assert value["go_mtc_ms"] == go_lead.ceil_frame(5003.0 + forced)

    def test_without_knobs_nothing_changes(self):
        c = _controller(_Clock(5003.0))
        value = _go(c)
        assert value["lead_ms"] == go_lead.GO_LEAD_FLOOR_MS


def _node():
    NE = importlib.import_module("cuemsengine.NodeEngine")
    node = object.__new__(NE.NodeEngine)
    node._command_lock = threading.Lock()
    node._follow_relay = None
    return NE, node


class TestHoldCommandLock:
    """R10: a GO's handling made slower than L, inside the command lock."""

    def test_every_go_holds_the_lock(self, knobs):
        knobs(HOLD_COMMAND_LOCK_MS="150")
        NE, node = _node()
        held = []
        node.commands_dict = {"go": lambda v: None, "stop": lambda v: None}
        with (
            patch.object(
                NE,
                "sleep",
                side_effect=lambda s: held.append((s, node._command_lock.locked())),
            ),
            patch.object(NE, "Logger") as log,
        ):
            node.run_command("go", {})
            node.run_command("stop", None)
        assert held == [(0.15, True)]
        lines = [str(c.args[0]) for c in log.info.call_args_list]
        assert any("GO timing: " in s and "test hold 150.0 ms" in s for s in lines)


def _audio(prewait_ms=0.0):
    cue = AudioCue(
        {
            "id": str(uuid.uuid4()),
            "name": "t",
            "Media": {
                "file_name": "a.wav",
                "id": str(uuid.uuid4()),
                "duration": "00:00:01.000",
            },
        }
    )
    cue.prewait = CTimecode(start_seconds=prewait_ms / 1000)
    cue._local = True
    cue.enabled = True
    cue.post_go = "pause"
    cue._target_object = None
    return cue


class TestCancelAt:
    """R4: a cancel at the pass's start + offset, through the real path."""

    def _fire(self, knobs, action, offset, arrival=10_000.0, prewait=1000.0):
        knobs(CANCEL_AT=f"{action}:{offset}")
        NE, node = _node()
        node._follow_relay = SimpleNamespace(run_seq=41)
        node._last_go_value = {"run_seq": 41, "lead_ms": 80.0, "go_mtc_ms": 9.0}
        cue = _audio(prewait)
        plan = node._test_cancel_plan(cue, arrival)
        assert plan is not None
        clock = _Clock(arrival)
        calls = []
        node._on_command_received = lambda n, v: calls.append(("hook", n, v)) or False
        node._handle_nng_command = lambda n, v: calls.append(("cmd", n, v))
        with (
            patch.object(NE.CUE_HANDLER, "_interpolated_clock", lambda m: clock),
            patch.object(NE, "sleep", side_effect=clock.sleep),
            patch.object(NE, "Logger") as log,
            patch("cuemsengine.cues.ActionHandler.ACTION_HANDLER") as ah,
        ):
            node.mtc_listener = MagicMock()
            node._test_cancel_fire(*plan)
        return plan, clock, calls, log, ah, cue

    def test_the_plan_is_the_first_local_audio_cue_at_its_start_label(self, knobs):
        knobs(CANCEL_AT="stop:-120")
        NE, node = _node()
        lead = _audio(0.0)
        lead.enabled = False  # skipped
        lead.post_go = "go"
        target = _audio(1010.0)
        lead._target_object = target
        action, offset, cue, at, k, count = node._test_cancel_plan(lead, 10_000.0)
        assert (action, offset, cue, k, count) == ("stop", -120.0, target, 1, 1)
        # the start label the player gets: 11010 rounded to the 40 ms grid
        assert at == round(11_010.0 / 40.0) * 40.0 - 120.0

    @pytest.mark.parametrize("offset", [-200.0, -45.0, 0.0, 30.0])
    def test_fires_at_the_offset_within_a_ms(self, knobs, offset):
        plan, clock, calls, log, ah, cue = self._fire(knobs, "stop", offset)
        at = plan[3]
        assert at <= clock.ms < at + 1.0
        text = str(log.warning.call_args_list[-1])
        assert f"TEST KNOB: cancel stop at start{offset:+.1f} ms (mtc " in text
        assert text.rstrip("')\"").endswith("(offset 1/1")

    def test_successive_gos_take_the_offsets_in_turn(self, knobs):
        knobs(CANCEL_AT="disable:-200,-45,30")
        NE, node = _node()
        cue = _audio(1000.0)
        plans = [node._test_cancel_plan(cue, 10_000.0) for _ in range(4)]
        assert [(p[1], p[4], p[5]) for p in plans] == [
            (-200.0, 1, 3),
            (-45.0, 2, 3),
            (30.0, 3, 3),
            (-200.0, 1, 3),
        ]
        assert plans[1][3] == 11_000.0 - 45.0
        clock = _Clock(10_000.0)
        node._on_command_received = lambda n, v: False
        node._handle_nng_command = lambda n, v: None
        with (
            patch.object(NE.CUE_HANDLER, "_interpolated_clock", lambda m: clock),
            patch.object(NE, "sleep", side_effect=clock.sleep),
            patch.object(NE, "Logger") as log,
        ):
            node.mtc_listener = MagicMock()
            node._test_cancel_fire(*plans[1])
        line = [
            str(c.args[0])
            for c in log.warning.call_args_list
            if str(c.args[0]).startswith("TEST KNOB: cancel disable at")
        ]
        assert len(line) == 1
        assert line[0].startswith("TEST KNOB: cancel disable at start-45.0 ms (mtc ")
        assert line[0].endswith(") (offset 2/3)")

    def test_an_offset_already_past_says_so_and_fires_now(self, knobs):
        knobs(CANCEL_AT="stop:-200")
        NE, node = _node()
        node._last_go_value = None
        cue = _audio(0.0)
        plan = node._test_cancel_plan(cue, 10_080.0)  # a led GO: start 10080
        clock = _Clock(10_000.0)  # the GO is handled at 10000 > 9880
        calls = []
        node._on_command_received = lambda n, v: False
        node._handle_nng_command = lambda n, v: calls.append(n)
        with (
            patch.object(NE.CUE_HANDLER, "_interpolated_clock", lambda m: clock),
            patch.object(NE, "sleep", side_effect=clock.sleep),
            patch.object(NE, "Logger") as log,
        ):
            node.mtc_listener = MagicMock()
            node._test_cancel_fire(*plan)
        assert calls == ["stop"] and clock.ms == 10_000.0
        assert "already 120.0 ms past" in str(log.warning.call_args_list[0])

    def test_stop_takes_the_nng_path(self, knobs):
        _, _, calls, _, _, _ = self._fire(knobs, "stop", -40.0)
        assert calls == [("hook", "stop", None), ("cmd", "stop", None)]

    def test_disable_takes_the_cue_enabled_path(self, knobs):
        _, _, calls, _, _, cue = self._fire(knobs, "disable", -40.0)
        assert calls == [
            ("hook", "cue_enabled", f"{cue.id} 0"),
            ("cmd", "cue_enabled", f"{cue.id} 0"),
        ]

    def test_supersede_is_setnextcue_then_go(self, knobs):
        _, _, calls, _, _, cue = self._fire(knobs, "supersede", -40.0)
        assert [c[:2] for c in calls] == [
            ("hook", "setnextcue"),
            ("cmd", "setnextcue"),
            ("hook", "go"),
            ("cmd", "go"),
        ]
        assert calls[1][2] == str(cue.id)
        assert calls[3][2] == {"run_seq": 41, "lead_ms": 80.0}

    @pytest.mark.parametrize(
        "action, kind",
        [
            ("actionstop", "stop"),
            ("actionpause", "pause"),
            ("actionfadeout", "fade_out"),
        ],
    )
    def test_actions_go_through_the_action_handler(self, knobs, action, kind):
        _, _, calls, _, ah, cue = self._fire(knobs, action, -40.0)
        assert calls == []
        (action_cue, _mtc, _frozen), _ = ah.execute_action.call_args
        assert action_cue.action_type == kind
        assert action_cue._action_target_object is cue

    def test_an_injected_go_arms_no_cancel_of_its_own(self, knobs):
        knobs(CANCEL_AT="supersede:-40")
        NE, node = _node()
        node._test_injecting = True
        with patch.object(NE.threading, "Thread") as thread:
            node._test_cancel_at(_audio(1000.0), 10_000.0)
        thread.assert_not_called()

    def test_no_audio_cue_in_the_pass(self, knobs):
        knobs(CANCEL_AT="stop:0")
        NE, node = _node()
        other = SimpleNamespace(
            id="d", _local=True, enabled=True, post_go="pause", _target_object=None
        )
        assert node._test_cancel_plan(other, 10_000.0) is None


# ---- R5: the existing drop knob on a selfgate player, on the wire -----------

wire = pytest.mark.skipif(
    not hasattr(pyossia.Node, "remove_child"),
    reason="installed pyossia has no Node.remove_child",
)


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
    for _ in tt[1:].decode():
        args.append(struct.unpack(">i", d[j : j + 4])[0])
        j += 4
    return a.decode(), args


@wire
def test_drop_osc_loses_one_follow_commit_and_one_cancelstart(knobs, monkeypatch):
    """R5 with the plan's syntax: the first /mtcfollow (the follow commit)
    and the first /cancelstart of a selfgate player never leave; the
    watchdog's re-send of the cancel does."""
    from cuemsengine.players.AudioPlayer import AudioClient, AudioPlayer
    from cuemsengine.players.StartGate import ACK_TIMEOUT_S, StartGate
    from cuemsengine.tools.PortHandler import PORT_HANDLER

    knobs(DROP_OSC="/mtcfollow:1,/cancelstart:1")
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(0.3)
    monkeypatch.setattr(PORT_HANDLER, "new_random_port", _free_port)
    client = AudioClient(player_port=rx.getsockname()[1], name="wire-r5")

    def drain():
        out = []
        while True:
            try:
                out.append(_parse(rx.recv(2048)))
            except socket.timeout:
                return out

    try:
        player = AudioPlayer(port=0, path="x", args="", media="m")
        player.p = SimpleNamespace(poll=lambda: None)
        cue = SimpleNamespace(id="r5")
        gate = StartGate(autostart=False)
        with patch("cuemsengine.osc.OssiaNodes.test_knobs", test_knobs):
            assert gate.commit_follow(cue, player, client, 1)
            assert drain() == []  # the follow commit was dropped
            rec = gate.cancel(cue, player, client, "cancel")
            assert drain() == []  # the first /cancelstart was dropped
            gate.scan(rec.t_sent + ACK_TIMEOUT_S + 1e-6)
            assert drain() == [("/cancelstart", [1, 5])]  # the re-send
            assert gate.commit_follow(cue, player, client, 2)
            assert drain() == [("/mtcfollow", [1])]  # only the first is lost
    finally:
        client.remove_device()
        rx.close()
