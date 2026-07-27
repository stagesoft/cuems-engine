# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Tests for PlayerHandler.kill_orphaned_mixer_processes (869cwpkz4).

On a node-engine restart a surviving jack-volume keeps the "0_mixer" JACK
client name; a new jack-volume then hits JackNameNotUnique and is renamed,
becoming a disconnected zombie the engine never actually talks to. The
orphan-kill (mirroring kill_orphaned_audio_processes) clears any survivor before
the new mixer spawns. Called on `self`, it only reads `self._audio_mixer` and
shells out to pgrep / os.kill, so a lightweight stand-in is enough.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from cuemsengine.players.PlayerHandler import PlayerHandler


def _run_kill(fake_self, stdout, returncode=0):
    proc = Mock(returncode=returncode, stdout=stdout)
    with (
        patch(
            "cuemsengine.players.PlayerHandler.subprocess.run", return_value=proc
        ) as run,
        patch("os.kill") as kill,
    ):
        PlayerHandler.kill_orphaned_mixer_processes(fake_self)
    return run, kill


def test_kills_all_untracked_when_no_mixer():
    fake = SimpleNamespace(_audio_mixer=None)
    run, kill = _run_kill(fake, "111\n222\n")
    run.assert_called_once_with(
        ["pgrep", "-f", "jack-volume -c"], capture_output=True, text=True
    )
    assert sorted(c.args[0] for c in kill.call_args_list) == [111, 222]


def test_spares_the_tracked_mixer_pid():
    fake = SimpleNamespace(_audio_mixer=SimpleNamespace(p=SimpleNamespace(pid=222)))
    _run, kill = _run_kill(fake, "111\n222\n")
    # 222 is the live mixer; only the 111 orphan is killed.
    assert [c.args[0] for c in kill.call_args_list] == [111]


def test_noop_when_pgrep_finds_nothing():
    fake = SimpleNamespace(_audio_mixer=None)
    _run, kill = _run_kill(fake, "", returncode=1)
    kill.assert_not_called()


def test_process_lookup_error_is_swallowed():
    fake = SimpleNamespace(_audio_mixer=None)
    proc = Mock(returncode=0, stdout="111\n")
    with (
        patch("cuemsengine.players.PlayerHandler.subprocess.run", return_value=proc),
        patch("os.kill", side_effect=ProcessLookupError),
    ):
        # Must not raise even if the pid vanished between pgrep and kill.
        PlayerHandler.kill_orphaned_mixer_processes(fake)
