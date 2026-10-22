# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""A node load goes on when an orphan cannot be killed (869evtdf7).

On 2026-09-04 a hand-launched test player owned by another user made every
load on a node fail: kill_orphaned_audio_processes got EPERM, the exception
left _load_project_inner after the old project was torn down and before the
new one was armed, and the only trace was "Error executing command callback
for load: [Errno 1] Operation not permitted".

Here the sweep runs for real (only pgrep and os.kill are faked) and the rest
of the load is stubbed as in test_node_engine_gradient.py.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from unittest.mock import MagicMock, Mock, patch


def _make_ne_for_load():
    from cuemsengine.NodeEngine import NodeEngine

    ne = NodeEngine.__new__(NodeEngine)
    ne._command_lock = threading.Lock()
    ne._loading_lock = threading.Lock()
    ne._loading = False
    ne.cm = MagicMock()
    ne.cm.node_uuid = "node-001"
    ne.cm.node_conf = {"gradient_osc_port": "7100", "nng_hub_port": "5555"}
    ne.cm.node_network_map = {}
    ne._project_generation = 0
    ne.script = MagicMock()
    ne.script.unix_name = "old-project"
    ne.mtc_listener = None
    return ne


def _load_patches(ne):
    from cuemsengine.cues.CueHandler import CUE_HANDLER
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    return {
        "deploy": patch.object(ne, "deploy_project", return_value=True),
        "gc": patch.object(PLAYER_HANDLER, "get_gradient_client", return_value=None),
        "dmx": patch.object(PLAYER_HANDLER, "get_dmx_player_client", return_value=None),
        "mixer": patch.object(
            PLAYER_HANDLER, "get_audio_mixer_client", return_value=None
        ),
        "kill_all": patch.object(PLAYER_HANDLER, "kill_all_audio_players"),
        "zombies": patch.object(PLAYER_HANDLER, "cleanup_zombie_jack_clients"),
        "video": patch.object(ne, "unload_video_devs"),
        "get_status": patch.object(ne, "get_status", return_value="no"),
        "set_status": patch.object(ne, "set_status"),
        "ready_project": patch.object(ne, "ready_project"),
        "ready_script": patch.object(ne, "ready_script"),
        "lock_file": patch.object(ne, "set_show_lock_file"),
        "nextcue": patch.object(ne, "_broadcast_nextcue"),
        "disarm": patch.object(CUE_HANDLER, "disarm_all"),
        "stop": patch.object(CUE_HANDLER, "stop_all_cues"),
        # Only the OS is faked under the sweep: pgrep lists one untracked
        # player, and killing it is not permitted.
        "pgrep": patch(
            "cuemsengine.players.PlayerHandler.subprocess.run",
            return_value=Mock(returncode=0, stdout="4432\n", stderr=""),
        ),
        "kill": patch(
            "os.kill", side_effect=PermissionError(1, "Operation not permitted")
        ),
    }


def test_load_reaches_the_new_project_when_an_orphan_kill_is_not_permitted(caplog):
    ne = _make_ne_for_load()
    with contextlib.ExitStack() as stack:
        mocks = {k: stack.enter_context(p) for k, p in _load_patches(ne).items()}
        with caplog.at_level(logging.WARNING):
            ne._load_project_inner("new-project")

    mocks["kill"].assert_called_once()
    mocks["disarm"].assert_called_once()
    mocks["ready_project"].assert_called_once_with("new-project")
    mocks["ready_script"].assert_called_once()
    mocks["lock_file"].assert_called_once()
    assert any(
        "Cannot kill" in r.getMessage() and "4432" in r.getMessage()
        for r in caplog.records
    )


def test_set_players_checks_the_binary_names_the_cleanup_relies_on():
    # G4b: a configured player binary with another name escapes every orphan
    # cleanup; the node says so at start.
    ne = _make_ne_for_load()
    with (
        patch.object(ne, "set_video_players"),
        patch.object(ne, "set_audio_players"),
        patch.object(ne, "set_dmx_players"),
        patch.object(ne, "set_gradient_client"),
        patch("cuemsengine.NodeEngine.check_orphan_binary_names") as check,
    ):
        ne.set_players()
    check.assert_called_once_with(ne.cm.node_conf)
