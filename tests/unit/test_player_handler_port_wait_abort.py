# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""PlayerHandler.new_audio_output tells the JACK port wait when to give up
(869f9wqpn).

A STOP or a load kills every audio player. One that was still waiting for its
JACK ports will never get them, yet the arm kept waiting the full ~15 s --
holding that cue's arm, so a GO for it in the meantime waited 5 s and failed.
The wait now ends as soon as the player PROCESS has exited. A live process
keeps the whole wait: the ceiling itself is not touched.
"""

from threading import RLock
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from cuemsutils.cues import AudioCue

from cuemsengine.players.PlayerHandler import PlayerHandler

NODE = "a3811d78-0000-0000-0000-000000000000"


def _handler(player):
    ph = object.__new__(PlayerHandler)
    ph._lock = RLock()
    ph._cue_players = {}
    ph._audio_players_by_id = {}
    ph._audio_output_generator = Mock(return_value=(player, MagicMock()))
    ph._player_endpoints_generator = Mock()
    ph._audio_mixer = Mock()
    ph._audio_mixer.connect_player_to_outputs.return_value = True
    ph._audio_outputs = {"6": {"mapped_to": "system:playback_1"}}
    ph._media_folder = "/tmp"
    return ph


def _cue():
    cue = AudioCue()
    cue.media = {"file_name": "a.wav"}
    cue.outputs = [{"output_name": f"{NODE}_6"}]
    return cue


def _should_abort(player):
    ph = _handler(player)
    with patch("cuemsengine.players.PlayerHandler.PORT_HANDLER") as ports:
        ports.assign_ports.return_value = {"audio_output": 9999}
        ph.new_audio_output(_cue())
    return ph._audio_mixer.connect_player_to_outputs.call_args.kwargs["should_abort"]


def test_a_running_process_does_not_abort_the_wait():
    player = SimpleNamespace(p=Mock())
    player.p.poll.return_value = None
    assert _should_abort(player)() is False


def test_an_exited_process_aborts_the_wait():
    player = SimpleNamespace(p=Mock())
    player.p.poll.return_value = -9  # killed by the STOP
    assert _should_abort(player)() is True


def test_a_player_without_a_process_yet_does_not_abort_the_wait():
    assert _should_abort(SimpleNamespace(p=None))() is False


# 869fbyjzx: the wiring waits for the player's own readiness event. The whole
# fix hangs on this one argument, so it has its own tests.


def _wire(player):
    ph = _handler(player)
    with patch("cuemsengine.players.PlayerHandler.PORT_HANDLER") as ports:
        ports.assign_ports.return_value = {"audio_output": 9999}
        ph.new_audio_output(_cue())
    return ph._audio_mixer.connect_player_to_outputs.call_args.kwargs


def test_the_players_ready_event_reaches_the_wiring():
    from threading import Event

    player = SimpleNamespace(p=None, ready=Event())
    assert _wire(player)["ready"] is player.ready


def test_a_player_without_a_ready_event_warns_and_is_wired_on_the_port(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        kwargs = _wire(SimpleNamespace(p=None))
    assert kwargs["ready"] is None
    assert "has no ready event" in caplog.text
