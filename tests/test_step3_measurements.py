# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj step 3 (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-
869feynrj.md §6 step 3, S0-18, S0-19): the measurement lines stay in the code,
one INFO line each, fixed wording to grep, numbers in ms with one decimal.

    GO lead: press <P> ms (interp), L <L> ms, anchor <A> ms (ceil +<c> ms),
        lead_ms <L>, L from <node> <out_latency_ms> ms | L floor
    GO timing: command lock waited <w> ms, held <h> ms (<what>)
    wiring check at arm: <t> ms (ok|repaired|failed)
    wiring check at GO: <t> ms (ok|repaired|failed)
    setup under lock: <t> ms (<type>, cue <id8>[, <n> layers])
    follow commit: cue <id8> at mtc <m> ms, start <s> ms, F <F> ms
"""

import re
import threading
import time
import uuid
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cuemsutils.cues import AudioCue, VideoCue
from cuemsutils.tools.CTimecode import CTimecode

from cuemsengine.cues import go_lead
from cuemsengine.cues.arm_cue import arm_cue
from cuemsengine.cues.CueHandler import CueHandler, _SetupGuard
from cuemsengine.cues.run_cue import installed_guard, run_cue
from cuemsengine.players.AudioPlayer import AudioPlayer
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
from cuemsengine.players.StartGate import START_GATE

SELFGATE = frozenset({"loop", "varispeed", "dayalign", "selfgate"})
NUM = r"-?\d+\.\d"


def _infos(log):
    return [str(c.args[0]) for c in log.info.call_args_list if c.args]


def _player():
    p = AudioPlayer(port=0, path="cuems-audioplayer", args="", media="a.wav")
    p.caps = SELFGATE
    p.ready.set()
    p.p = SimpleNamespace(poll=lambda: None)
    return p


def _audio():
    cue = AudioCue(
        {
            "id": str(uuid.uuid4()),
            "name": "t",
            "loop": 1,
            "Media": {
                "file_name": "a.wav",
                "id": str(uuid.uuid4()),
                "duration": "00:00:01.000",
            },
        }
    )
    cue._local = True
    cue._stop_requested = False
    cue._go_generation = 1
    cue.outputs = [{"output_name": "n" * 36 + "_0"}]
    return cue


class TestGoLead:
    def _controller(self):
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
        c.mtc_listener.interpolated_ms.return_value = 79253.0
        return c

    def _line(self, c):
        with (
            patch("cuemsengine.ControllerEngine.Logger") as log,
            patch.object(c, "_forward_command_to_nodes"),
        ):
            c.go_script(None)
        lines = [s for s in _infos(log) if s.startswith("GO lead: ")]
        assert len(lines) == 1
        return lines[0]

    @staticmethod
    def _expected(lead, source):
        press = 79253.0
        anchor = go_lead.ceil_frame(press + lead)
        return (
            f"GO lead: press {press:.1f} ms (interp), L {lead:.1f} ms, anchor "
            f"{anchor:.1f} ms (ceil +{anchor - (press + lead):.1f} ms), "
            f"lead_ms {lead:.1f}, {source}"
        )

    def test_from_a_node(self):
        """A node above the floor (85.3 ms latency + a 1024-frame period)."""
        c = self._controller()
        c._required_nodes = {"node01"}
        out = 85.3 + 1024 / 48
        c._note_node_latency("node01", out)
        lead = out + go_lead.GO_LEAD_DELTA_MS + go_lead.GO_LEAD_MARGIN_MS
        assert lead > go_lead.GO_LEAD_FLOOR_MS
        assert self._line(c) == self._expected(lead, f"L from node01 {out:.1f} ms")

    def test_the_usual_rig_is_at_the_floor(self):
        """42.7 + 30 + 5 = 77.7 ms is under the 80 ms floor (step 3)."""
        c = self._controller()
        c._required_nodes = {"node01"}
        c._note_node_latency("node01", 32.0 + 512 / 48)
        assert self._line(c) == self._expected(go_lead.GO_LEAD_FLOOR_MS, "L floor")

    def test_at_the_floor(self):
        assert self._line(self._controller()) == self._expected(
            go_lead.GO_LEAD_FLOOR_MS, "L floor"
        )


class TestGoTiming:
    def _node(self, handler):
        import importlib

        NE = importlib.import_module("cuemsengine.NodeEngine")
        node = object.__new__(NE.NodeEngine)
        node._command_lock = threading.Lock()
        node._follow_relay = None
        node.commands_dict = {"go": handler, "gocue": handler}
        return node

    def test_the_line_names_what_held_the_lock(self):
        node = None

        def handler(value):
            node._go_note("rearm", 300.0)
            node._go_note("go+lookahead", 45.1)

        node = self._node(handler)
        with patch("cuemsengine.NodeEngine.Logger") as log:
            node.run_command("go", {}, arrived=time.monotonic())
        (line,) = [s for s in _infos(log) if s.startswith("GO timing: ")]
        assert re.fullmatch(
            rf"GO timing: command lock waited {NUM} ms, held {NUM} ms "
            r"\(rearm 300\.0 ms, go\+lookahead 45\.1 ms\)",
            line,
        )

    def test_the_wait_is_measured_from_the_arrival(self):
        node = self._node(lambda value: None)
        node._command_lock.acquire()
        threading.Timer(0.05, node._command_lock.release).start()
        with patch("cuemsengine.NodeEngine.Logger") as log:
            node.run_command("gocue", {}, arrived=time.monotonic())
        (line,) = [s for s in _infos(log) if s.startswith("GO timing: ")]
        waited = float(re.search(r"waited (\S+) ms", line).group(1))
        assert waited >= 40.0
        assert line.endswith("(go)")

    def test_no_line_for_other_commands(self):
        node = self._node(lambda value: None)
        node.commands_dict["stop"] = lambda value: None
        with patch("cuemsengine.NodeEngine.Logger") as log:
            node.run_command("stop", None, arrived=time.monotonic())
        assert not [s for s in _infos(log) if s.startswith("GO timing: ")]


def _mixer(diff=([], []), repair=(True, [])):
    mixer = MagicMock()
    mixer.conn_man.port_exists.return_value = True
    mixer.player_connection_diff.return_value = diff
    mixer.repair_player_connections.return_value = repair
    return mixer


class TestWiringCheck:
    def _arm(self, mixer):
        cue, player = _audio(), _player()
        with (
            patch.object(PLAYER_HANDLER, "new_audio_output"),
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: player),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: mixer),
            patch.object(PLAYER_HANDLER, "resolve_audio_port", lambda i: "in_1"),
            patch("cuemsengine.cues.run_cue.Logger") as log,
        ):
            arm_cue(cue)
        return cue, [s for s in _infos(log) if s.startswith("wiring check at ")]

    def test_ok_at_arm(self):
        _, lines = self._arm(_mixer())
        assert len(lines) == 1
        assert re.fullmatch(rf"wiring check at arm: {NUM} ms \(ok\)", lines[0])

    def test_repaired_at_arm(self):
        _, lines = self._arm(_mixer(diff=([("p:outport 0", "in_1")], [])))
        assert re.fullmatch(rf"wiring check at arm: {NUM} ms \(repaired\)", lines[0])

    def test_failed_at_arm_then_checked_at_go(self):
        cue, lines = self._arm(_mixer(diff=None))
        assert re.fullmatch(rf"wiring check at arm: {NUM} ms \(failed\)", lines[0])
        cue._osc = MagicMock()
        mtc = SimpleNamespace(main_tc=SimpleNamespace(framerate=25, frames=0))
        with (
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: _player()),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: _mixer()),
            patch.object(PLAYER_HANDLER, "resolve_audio_port", lambda i: "in_1"),
            patch("cuemsengine.cues.run_cue.Logger") as log,
        ):
            run_cue(cue, mtc, 2000.0)
        go = [s for s in _infos(log) if s.startswith("wiring check at ")]
        assert len(go) == 1
        assert re.fullmatch(rf"wiring check at GO: {NUM} ms \(ok\)", go[0])


class TestSetupUnderLock:
    def test_an_audio_setup(self):
        cue = _audio()
        cue._osc = MagicMock()
        mtc = SimpleNamespace(main_tc=SimpleNamespace(framerate=25, frames=0))
        guard = _SetupGuard(Lock(), cue, 1)
        with (
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: _player()),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: None),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
            installed_guard(guard),
        ):
            run_cue(cue, mtc, 2000.0)
        (line,) = [s for s in _infos(log) if s.startswith("setup under lock: ")]
        assert re.fullmatch(
            rf"setup under lock: {NUM} ms \(AudioCue, cue {str(cue.id)[:8]}\)", line
        )

    def test_a_video_setup_names_its_layers(self):
        cue = VideoCue(
            {
                "id": str(uuid.uuid4()),
                "name": "v",
                "Media": {
                    "file_name": "v.mov",
                    "id": str(uuid.uuid4()),
                    "duration": "00:00:01.000",
                },
            }
        )
        cue._stop_requested = False
        cue._go_generation = 1
        cue._layer_ids = [f"{cue.id}_0", f"{cue.id}_1"]
        cue._layer_outputs = {}
        cue._osc = MagicMock()
        mtc = SimpleNamespace(main_tc=SimpleNamespace(framerate=25, frames=0))
        guard = _SetupGuard(Lock(), cue, 1)
        with (
            patch.object(
                PLAYER_HANDLER, "cue_media_dimensions", lambda c: (None, None)
            ),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
            installed_guard(guard),
        ):
            run_cue(cue, mtc, 2000.0)
        (line,) = [s for s in _infos(log) if s.startswith("setup under lock: ")]
        assert re.fullmatch(
            rf"setup under lock: {NUM} ms \(VideoCue, cue {str(cue.id)[:8]}, "
            r"2 layers\)",
            line,
        )

    def test_a_refused_setup_logs_no_hold(self):
        cue = _audio()
        cue._osc = MagicMock()
        mtc = SimpleNamespace(main_tc=SimpleNamespace(framerate=25, frames=0))
        guard = _SetupGuard(Lock(), cue, 0)  # superseded
        with (
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: _player()),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: None),
            patch("cuemsengine.cues.CueHandler.Logger") as log,
            installed_guard(guard),
        ):
            run_cue(cue, mtc, 2000.0)
        assert not [s for s in _infos(log) if s.startswith("setup under lock: ")]


class TestFollowCommitLine:
    def test_the_line(self):
        START_GATE.autostart = False
        try:
            ch = object.__new__(CueHandler)
            ch._lock = Lock()
            cue = _audio()
            cue._osc = MagicMock()
            cue._reveal_ready = True
            cue._start_mtc = CTimecode(framerate=25, start_seconds=1.0)
            mtc = MagicMock()
            mtc.interpolated_ms.return_value = 880.0
            with (
                patch.object(PLAYER_HANDLER, "audio_player", lambda c: _player()),
                patch("cuemsengine.cues.CueHandler.Logger") as log,
            ):
                assert ch._commit_follow(cue, cue, 1, mtc)
            (line,) = [s for s in _infos(log) if s.startswith("follow commit: ")]
            assert line == (
                f"follow commit: cue {str(cue.id)[:8]} at mtc 880.0 ms, "
                "start 1000.0 ms, F 120.0 ms"
            )
        finally:
            START_GATE.reset_for_tests()
            START_GATE.autostart = True
