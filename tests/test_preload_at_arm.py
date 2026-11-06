# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""869feynrj §4.5a + S0-15 (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-
head-869feynrj.md, §7.1 "Engine"): preload at arm, gated on CAPS selfgate.

- after a successful arm of a selfgate player the mixer wiring check runs
  (once, at arm); a GO then only checks outport 0 and sends what depends on
  the start (plus /loop and /volmaster, which stay at GO by S0-15) and the
  follow commit -- per cue, on the wire;
- an older player: no check at arm, the GO-time diff and edge-by-edge repair
  as before, and its OSC byte-identical to today's: the start, /loop,
  /volmaster at setup, then the start again and /mtcfollow 1 at the reveal.
"""

import socket
import struct
import uuid
from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pyossia
import pytest
from cuemsutils.cues import AudioCue

from cuemsengine.cues.arm_cue import arm_cue
from cuemsengine.cues.CueHandler import CueHandler
from cuemsengine.cues.run_cue import reveal_cue, run_cue
from cuemsengine.players.AudioPlayer import AudioClient, AudioPlayer
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
from cuemsengine.players.StartGate import START_GATE
from cuemsengine.tools.PortHandler import PORT_HANDLER

SELFGATE = frozenset({"loop", "varispeed", "dayalign", "selfgate"})
OLD = frozenset({"loop", "varispeed", "dayalign"})


def _player(caps):
    p = AudioPlayer(port=0, path="cuems-audioplayer", args="", media="a.wav")
    p.caps = caps
    p.ready.set()
    p.p = SimpleNamespace(poll=lambda: None)
    return p


def _cue(master_vol=None):
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
    if master_vol is not None:
        cue.master_vol = master_vol
    cue._local = True
    cue.outputs = [{"output_name": "n" * 36 + "_0"}]
    return cue


def _mixer():
    mixer = MagicMock()
    mixer.conn_man.port_exists.return_value = True
    mixer.player_connection_diff.return_value = ([], [])
    return mixer


@pytest.fixture(autouse=True)
def quiet_gate():
    START_GATE.autostart = False
    yield
    START_GATE.reset_for_tests()
    START_GATE.autostart = True


class TestArm:
    def _arm(self, caps):
        cue, mixer, player = _cue(), _mixer(), _player(caps)
        with (
            patch.object(PLAYER_HANDLER, "new_audio_output"),
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: player),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: mixer),
            patch.object(
                PLAYER_HANDLER, "resolve_audio_port", lambda i: "0_mixer:in_1"
            ),
        ):
            arm_cue(cue)
        return mixer

    def test_a_selfgate_arm_checks_the_wiring_once(self):
        mixer = self._arm(SELFGATE)
        mixer.player_connection_diff.assert_called_once()

    def test_an_older_player_is_not_checked_at_arm(self):
        mixer = self._arm(OLD)
        mixer.player_connection_diff.assert_not_called()


class TestGo:
    def _run(self, caps):
        cue, mixer, player = _cue(), _mixer(), _player(caps)
        cue._osc = MagicMock()
        mtc = SimpleNamespace(main_tc=SimpleNamespace(framerate=25, frames=0))
        with (
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: player),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: mixer),
            patch.object(
                PLAYER_HANDLER, "resolve_audio_port", lambda i: "0_mixer:in_1"
            ),
        ):
            run_cue(cue, mtc, 2000.0)
        return mixer

    def test_a_selfgate_go_only_checks_outport_0(self):
        mixer = self._run(SELFGATE)
        mixer.conn_man.port_exists.assert_called_once()
        mixer.player_connection_diff.assert_not_called()

    def test_an_older_player_keeps_the_go_time_repair(self):
        mixer = self._run(OLD)
        mixer.player_connection_diff.assert_called_once()


# ---- on the wire ------------------------------------------------------------

pytestmark_wire = pytest.mark.skipif(
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
    for t in tt[1:].decode():
        if t == "i":
            args.append(struct.unpack(">i", d[j : j + 4])[0])
        elif t == "f":
            args.append(round(struct.unpack(">f", d[j : j + 4])[0], 6))
        j += 4
    return a.decode(), args


@pytest.fixture
def wire(monkeypatch):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(0.3)
    monkeypatch.setattr(PORT_HANDLER, "new_random_port", _free_port)
    client = AudioClient(player_port=rx.getsockname()[1], name="wire-preload")

    def drain():
        out = []
        while True:
            try:
                out.append(_parse(rx.recv(2048)))
            except socket.timeout:
                return out

    yield client, drain
    client.remove_device()
    rx.close()


@pytestmark_wire
class TestGoOnTheWire:
    """A GO per cue: setup (start, /loop, /volmaster), then the follow."""

    def _go(self, caps, wire, master_vol=None):
        client, drain = wire
        cue, mixer, player = _cue(master_vol), _mixer(), _player(caps)
        cue._osc = client
        cue._go_generation = 1
        cue._stop_requested = False
        mtc = SimpleNamespace(main_tc=SimpleNamespace(framerate=25, frames=0))
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        with (
            patch.object(PLAYER_HANDLER, "audio_player", lambda c: player),
            patch.object(PLAYER_HANDLER, "get_audio_mixer", lambda: mixer),
            patch.object(
                PLAYER_HANDLER, "resolve_audio_port", lambda i: "0_mixer:in_1"
            ),
        ):
            run_cue(cue, mtc, 600080.0)
            setup = drain()
            target = ch._follow_commit_target(cue)
            if target is not None:
                assert ch._commit_follow(cue, target, 1)
            commit = drain()
            reveal_cue(cue, mtc, 600080.0)
            reveal = drain()
        return setup, commit, reveal

    def test_selfgate(self, wire):
        setup, commit, reveal = self._go(SELFGATE, wire, master_vol=0)
        assert setup == [
            ("/start_tod", [600080]),
            ("/loop", [1]),
            ("/volmaster", [0.0]),  # D7: a first 0.0 reaches the player
        ]
        assert commit == [("/mtcfollow", [1])]
        assert reveal == []

    def test_older_player_byte_identical_to_today(self, wire):
        """(D7 aside: a first /volmaster 0.0 now reaches an older player too,
        the repetition filter is off for every player, §4.4.)"""
        setup, commit, reveal = self._go(OLD, wire)
        assert setup == [
            ("/start_tod", [600080]),
            ("/loop", [1]),
            ("/volmaster", [1.0]),
        ]
        assert commit == []
        assert reveal == [("/start_tod", [600080]), ("/mtcfollow", [1])]
