# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""A project unload reaches the nodes as an unload (869fh8kef).

The controller used to forward an unload as a plain STOP. A node's
stop_playback re-arms the script it still holds, so after an unload every node
killed its players and spawned new ones for the project that was no longer
loaded (test, 2026-10-19: node01 4 players killed, 4 new ones), kept
load=<project> and kept /tmp/cuems.show.lock.

The node now tears the project down the way a load does and arms nothing.
"""

from __future__ import annotations

import contextlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_ne():
    from cuemsengine.core.EngineStatus import EngineStatus
    from cuemsengine.NodeEngine import NodeEngine

    ne = NodeEngine.__new__(NodeEngine)
    ne._command_lock = threading.Lock()
    ne.cm = MagicMock()
    ne.cm.node_uuid = "node-001"
    ne.status = EngineStatus()
    ne.set_status("load", "old-project")
    ne.set_status("running", "no")
    ne._project_generation = 3
    ne.script = MagicMock()
    ne.script.name = "old project"
    ne.ongoing_cue = None
    ne.next_cue_pointer = MagicMock()
    ne.go_offset = 0
    ne._follow_relay = None
    ne._stop_project_watchdog = None
    return ne


def _teardown_patches(ne):
    from cuemsengine.cues.CueHandler import CUE_HANDLER
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    return {
        "gradient": patch.object(ne, "_gradient_cancel_all"),
        "dmx": patch.object(ne, "_dmx_reset"),
        "video": patch.object(ne, "unload_video_devs"),
        "mixer": patch.object(
            PLAYER_HANDLER, "get_audio_mixer_client", return_value=None
        ),
        "kill_all": patch.object(PLAYER_HANDLER, "kill_all_audio_players"),
        "orphans": patch.object(PLAYER_HANDLER, "kill_orphaned_audio_processes"),
        "zombies": patch.object(PLAYER_HANDLER, "cleanup_zombie_jack_clients"),
        "stop_cues": patch.object(CUE_HANDLER, "stop_all_cues"),
        "disarm": patch.object(CUE_HANDLER, "disarm_all"),
        "ready_script": patch.object(ne, "ready_script"),
        "armed_ready": patch.object(ne, "_notify_armed_ready"),
        "nextcue": patch.object(ne, "_broadcast_nextcue"),
        "rm_lock": patch.object(ne, "remove_show_lock_file"),
    }


@contextlib.contextmanager
def _patched(ne):
    with contextlib.ExitStack() as stack:
        yield {k: stack.enter_context(p) for k, p in _teardown_patches(ne).items()}


def test_unload_is_routed_to_a_handler():
    ne = _make_ne()
    ne.set_oscquery_comms()
    assert ne.commands_dict["unload"] == ne.unload_project


def test_unload_tears_down_and_arms_nothing():
    ne = _make_ne()
    with _patched(ne) as m:
        assert ne.unload_project("") is True

    m["stop_cues"].assert_called_once()
    m["dmx"].assert_called_once()
    m["video"].assert_called_once()
    m["kill_all"].assert_called_once()
    m["disarm"].assert_called_once_with(reason="unload")
    m["ready_script"].assert_not_called()
    m["armed_ready"].assert_not_called()


def test_unload_forgets_the_project():
    ne = _make_ne()
    with _patched(ne) as m:
        ne.unload_project("")

    assert ne.script is None
    assert ne.next_cue_pointer is None
    assert ne.get_status("load") == ""
    m["rm_lock"].assert_called_once()
    m["nextcue"].assert_called_once()


def test_unload_aborts_in_flight_arm_threads():
    """ReArm/PreArm threads check the generation; ready_script is what bumps
    it on a STOP or a load, and an unload does not call ready_script."""
    ne = _make_ne()
    with _patched(ne):
        ne.unload_project("")
    assert ne._project_generation == 4


def test_unload_is_refused_while_running():
    """The controller already refuses it; a node that is still running does
    not tear down under the show either."""
    ne = _make_ne()
    ne.set_status("running", "yes")
    with _patched(ne) as m:
        assert ne.unload_project("") is False

    m["kill_all"].assert_not_called()
    m["disarm"].assert_not_called()
    assert ne.get_status("load") == "old-project"


def test_unload_with_nothing_loaded_still_clears_state():
    ne = _make_ne()
    ne.script = None
    ne.set_status("load", "")
    with _patched(ne) as m:
        assert ne.unload_project("") is True
    m["kill_all"].assert_called_once()
    m["rm_lock"].assert_called_once()


@pytest.mark.parametrize("command", ["unload"])
def test_receive_hook_ends_the_run(command):
    ne = _make_ne()
    relay = SimpleNamespace(end_run=MagicMock(), begin_run=MagicMock())
    ne._follow_relay = relay
    with patch.object(ne, "_cancel_stop_project_watchdog") as wd:
        assert ne._on_command_received(command, "") is False
    relay.end_run.assert_called_once_with(command)
    wd.assert_called_once()


def test_run_command_marks_the_unload_applied():
    ne = _make_ne()
    relay = SimpleNamespace(stop_applied=MagicMock())
    ne._follow_relay = relay
    ne.commands_dict = {"unload": MagicMock()}
    assert ne.run_command("unload", "") is True
    relay.stop_applied.assert_called_once()
