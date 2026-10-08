# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Orphan sweeps never abort their caller, and match only our own players
(869evtdf7).

kill_orphaned_audio_processes runs in the middle of a node's project load,
kill_orphaned_mixer_processes right before the mixer starts. An exception
from either one used to escape: an orphan owned by another user (EPERM) sank
the whole load after the old project was torn down, or left the node without
a mixer. The sweeps are hygiene, not a precondition: every failure is logged
and the sweep goes on.

They also used to match any command line that merely contained the binary
name, owned by anyone (an operator's `tail -f …/cuems-audioplayer.log`, another
user's process). Now they list only processes of the engine's own user whose
argv[0] is the player binary.

The sweeps are called unbound on lightweight stand-ins, like
test_player_handler_mixer_orphan.py does.
"""

import importlib
import logging
import os
import re
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from cuemsengine.players.PlayerHandler import PlayerHandler

# The module, not the class of the same name.
ph = importlib.import_module("cuemsengine.players.PlayerHandler")

RUN = "cuemsengine.players.PlayerHandler.subprocess.run"


def _audio_self(tracked=()):
    players = {
        f"cue-{pid}": SimpleNamespace(p=SimpleNamespace(pid=pid)) for pid in tracked
    }
    return SimpleNamespace(_lock=threading.RLock(), _audio_players_by_id=players)


def _mixer_self():
    return SimpleNamespace(_audio_mixer=None)


def _proc(stdout="", returncode=0, stderr=""):
    return Mock(returncode=returncode, stdout=stdout, stderr=stderr)


def _sweep_audio(fake, run_kw, kill_kw):
    with patch(RUN, **run_kw) as run, patch("os.kill", **kill_kw) as kill:
        PlayerHandler.kill_orphaned_audio_processes(fake)
    return run, kill


def _sweep_mixer(fake, run_kw, kill_kw):
    with patch(RUN, **run_kw) as run, patch("os.kill", **kill_kw) as kill:
        PlayerHandler.kill_orphaned_mixer_processes(fake)
    return run, kill


SWEEPS = [
    pytest.param(_audio_self, _sweep_audio, "audioplayer", id="audio"),
    pytest.param(_mixer_self, _sweep_mixer, "jack-volume mixer", id="mixer"),
]


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


# ---------------------------------------------------------------------------
# What pgrep is asked for
# ---------------------------------------------------------------------------


def test_audio_sweep_lists_own_user_cuems_audioplayer_only():
    run, _kill = _sweep_audio(_audio_self(), {"return_value": _proc(returncode=1)}, {})
    run.assert_called_once_with(
        ["pgrep", "-u", str(os.geteuid()), "-f", ph.AUDIOPLAYER_ORPHAN_PATTERN],
        capture_output=True,
        text=True,
    )


def test_mixer_sweep_lists_own_user_only():
    run, _kill = _sweep_mixer(_mixer_self(), {"return_value": _proc(returncode=1)}, {})
    run.assert_called_once_with(
        ["pgrep", "-u", str(os.geteuid()), "-f", "jack-volume -c"],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "cmdline, matches",
    [
        (
            "/usr/bin/cuems-audioplayer --port 7001 --uuid ab12 "
            "/opt/cuems_library/media/x.wav",
            True,
        ),
        ("/usr/local/bin/cuems-audioplayer --port 7001 x.wav", True),
        ("cuems-audioplayer", True),
        ("tail -f /var/log/cuems-audioplayer.log", False),
        ("grep cuems-audioplayer", False),
        ('/bin/sh -c /usr/bin/pkill -u cuems -f "cuems-audioplayer"', False),
        ("/usr/local/bin/cuems-audioplayer-slow --port 7001 x.wav", False),
        ("/usr/bin/cuems-audioplayer.bak --port 1", False),
    ],
)
def test_audioplayer_pattern(cmdline, matches):
    # pgrep matches a POSIX ERE against the space-joined cmdline; Python's re
    # agrees with ERE on this pattern.
    assert bool(re.search(ph.AUDIOPLAYER_ORPHAN_PATTERN, cmdline)) is matches


# ---------------------------------------------------------------------------
# A kill that fails never escapes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("make_self, sweep, label", SWEEPS)
def test_eperm_is_logged_and_the_sweep_goes_on(make_self, sweep, label, caplog):
    def kill(pid, _sig):
        if pid == 111:
            raise PermissionError(1, "Operation not permitted")

    with (
        caplog.at_level(logging.WARNING),
        patch.object(ph, "_pid_owner", return_value="stagelab(1000)"),
    ):
        _run, killer = sweep(
            make_self(), {"return_value": _proc("111\n222\n")}, {"side_effect": kill}
        )

    # The second orphan is still killed.
    assert [c.args[0] for c in killer.call_args_list] == [111, 222]
    eperm = [m for m in _warnings(caplog) if "Cannot kill" in m]
    assert len(eperm) == 1
    assert "111" in eperm[0]
    assert label in eperm[0]
    assert "stagelab(1000)" in eperm[0]


@pytest.mark.parametrize("make_self, sweep, label", SWEEPS)
def test_esrch_is_silent(make_self, sweep, label, caplog):
    with caplog.at_level(logging.WARNING):
        sweep(
            make_self(),
            {"return_value": _proc("111\n")},
            {"side_effect": ProcessLookupError},
        )
    assert not [m for m in _warnings(caplog) if "Cannot kill" in m]


@pytest.mark.parametrize("make_self, sweep, label", SWEEPS)
def test_any_other_kill_error_is_logged_and_the_sweep_goes_on(
    make_self, sweep, label, caplog
):
    with caplog.at_level(logging.WARNING):
        _run, killer = sweep(
            make_self(),
            {"return_value": _proc("111\n222\n")},
            {"side_effect": RuntimeError("boom")},
        )
    assert [c.args[0] for c in killer.call_args_list] == [111, 222]
    assert len([m for m in _warnings(caplog) if "Cannot kill" in m]) == 2


# ---------------------------------------------------------------------------
# pgrep itself failing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("make_self, sweep, label", SWEEPS)
def test_pgrep_no_match_is_silent(make_self, sweep, label, caplog):
    with caplog.at_level(logging.WARNING):
        _run, killer = sweep(make_self(), {"return_value": _proc(returncode=1)}, {})
    killer.assert_not_called()
    assert _warnings(caplog) == []


@pytest.mark.parametrize("rc", [2, 3])
@pytest.mark.parametrize("make_self, sweep, label", SWEEPS)
def test_pgrep_error_is_logged_not_silent(make_self, sweep, label, rc, caplog):
    proc = _proc(returncode=rc, stderr="pgrep: invalid user name: x")
    with caplog.at_level(logging.WARNING):
        _run, killer = sweep(make_self(), {"return_value": proc}, {})
    killer.assert_not_called()
    msgs = _warnings(caplog)
    assert any(f"rc {rc}" in m and "invalid user name" in m for m in msgs), msgs


@pytest.mark.parametrize("make_self, sweep, label", SWEEPS)
def test_pgrep_that_cannot_run_is_logged(make_self, sweep, label, caplog):
    with caplog.at_level(logging.WARNING):
        _run, killer = sweep(
            make_self(), {"side_effect": FileNotFoundError("pgrep")}, {}
        )
    killer.assert_not_called()
    assert _warnings(caplog)


@pytest.mark.parametrize("make_self, sweep, label", SWEEPS)
def test_a_bad_pgrep_line_is_skipped_not_fatal(make_self, sweep, label, caplog):
    with caplog.at_level(logging.WARNING):
        _run, killer = sweep(make_self(), {"return_value": _proc("abc\n222\n")}, {})
    assert [c.args[0] for c in killer.call_args_list] == [222]
    assert any("abc" in m for m in _warnings(caplog))


def test_audio_sweep_spares_tracked_players():
    _run, killer = _sweep_audio(
        _audio_self(tracked=[222]), {"return_value": _proc("111\n222\n")}, {}
    )
    assert [c.args[0] for c in killer.call_args_list] == [111]


# ---------------------------------------------------------------------------
# The owner named in the EPERM warning
# ---------------------------------------------------------------------------


def test_pid_owner_of_this_process_names_its_uid():
    assert f"({os.getuid()})" in ph._pid_owner(os.getpid())


def test_pid_owner_names_a_differing_effective_uid():
    status = "Name:\tx\nUid:\t0\t4242\t0\t4242\nGid:\t0\t0\t0\t0\n"
    users = {0: "root", 4242: "cuems"}
    with (
        patch("builtins.open", Mock(return_value=_FakeFile(status))),
        patch.object(
            ph.pwd, "getpwuid", side_effect=lambda u: SimpleNamespace(pw_name=users[u])
        ),
    ):
        owner = ph._pid_owner(1234)
    assert owner == "root(0), euid cuems(4242)"


def test_pid_owner_of_a_vanished_process_is_unknown():
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert ph._pid_owner(999999) == "?"


class _FakeFile:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._text

    def __iter__(self):
        return iter(self._text.splitlines(keepends=True))


# ---------------------------------------------------------------------------
# The binary names the cleanup relies on (G4b)
# ---------------------------------------------------------------------------

CANONICAL = {
    "audioplayer": {"path": "/usr/bin/cuems-audioplayer", "args": ""},
    "audiomixer": {"path": "/usr/bin/jack-volume", "args": ""},
    "dmxplayer": {"path": "/usr/bin/cuems-dmxplayer", "args": ""},
}


def test_canonical_binary_names_pass_silently(caplog):
    with caplog.at_level(logging.WARNING):
        assert ph.check_orphan_binary_names(CANONICAL) == []
    assert _warnings(caplog) == []


def test_cuems_jack_volume_is_a_known_mixer_name():
    conf = dict(CANONICAL, audiomixer={"path": "/usr/local/bin/cuems-jack-volume"})
    assert ph.check_orphan_binary_names(conf) == []


def test_an_unknown_binary_name_is_warned(caplog):
    conf = dict(CANONICAL, audioplayer={"path": "/opt/x/audioplayer-cuems"})
    with caplog.at_level(logging.WARNING):
        assert ph.check_orphan_binary_names(conf) == ["audioplayer"]
    msgs = _warnings(caplog)
    assert len(msgs) == 1
    assert "audioplayer-cuems" in msgs[0]
    assert "cuems-audioplayer" in msgs[0]


def test_missing_keys_are_skipped(caplog):
    with caplog.at_level(logging.WARNING):
        assert ph.check_orphan_binary_names({"gradient_osc_port": "7100"}) == []
    assert _warnings(caplog) == []


# ---------------------------------------------------------------------------
# The zombie JACK client cleanup never aborts a load either (G7)
# ---------------------------------------------------------------------------


def test_zombie_cleanup_survives_a_jack_error(caplog):
    conn_man = Mock()
    conn_man.get_ports.side_effect = RuntimeError("JACK server not running")
    fake = SimpleNamespace(
        _audio_mixer=SimpleNamespace(conn_man=conn_man),
        _lock=threading.RLock(),
        _audio_players_by_id={},
    )
    with caplog.at_level(logging.WARNING):
        assert PlayerHandler.cleanup_zombie_jack_clients(fake) == 0
    assert any("zombie" in m.lower() for m in _warnings(caplog))
