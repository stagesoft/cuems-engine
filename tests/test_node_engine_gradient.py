# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Unit tests for NodeEngine gradient-motiond wiring — Phase 4 / T008 + T011.

Covers (T008):
- set_gradient_client() invoked from set_players() alongside
  - set_video_players/set_dmx_players
- node_uuid passed correctly into PLAYER_HANDLER.set_gradient_client
- cancel_all fires before stop_all_cues on STOP
- cancel_all fires before stop_all_cues on project load
- None guard: when gradient_client is None, logs DEBUG and doesn't crash

Covers (T011):
- Custom gradient_osc_port value in node_conf flows through to
  - PLAYER_HANDLER.set_gradient_client
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node_engine(gradient_osc_port="7100", node_uuid="node-001"):
    """
    Build a NodeEngine shell via __new__ — skips full __init__ and real config.
    """
    from cuemsengine.NodeEngine import NodeEngine

    ne = NodeEngine.__new__(NodeEngine)
    ne._command_lock = __import__("threading").Lock()
    ne._loading_lock = __import__("threading").Lock()
    ne._loading = False
    ne.cm = MagicMock()
    ne.cm.node_uuid = node_uuid
    ne.cm.node_conf = {
        "gradient_osc_port": gradient_osc_port,
        "nng_hub_port": "5555",
    }
    return ne


# ---------------------------------------------------------------------------
# Setup wiring tests (T008)
# ---------------------------------------------------------------------------


class TestSetGradientClientWiring:
    def test_set_gradient_client_called_from_set_players(self):
        """
        set_players() must call set_gradient_client() to wire the OSC client.
        """
        ne = _make_node_engine()
        with (
            patch.object(ne, "set_video_players"),
            patch.object(ne, "set_audio_players"),
            patch.object(ne, "set_dmx_players"),
            patch.object(ne, "set_gradient_client") as mock_sgc,
        ):
            ne.set_players()
        mock_sgc.assert_called_once()

    def test_set_gradient_client_node_uuid_passed(self):
        """
        set_gradient_client() must propagate cm.node_uuid to PLAYER_HANDLER.
        """
        ne = _make_node_engine(node_uuid="node-007")
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

        with patch.object(PLAYER_HANDLER, "set_gradient_client") as mock_ph_sgc:
            ne.set_gradient_client()

        mock_ph_sgc.assert_called_once()
        _, kwargs = mock_ph_sgc.call_args
        assert (
            kwargs.get("node_uuid") == "node-007"
            or mock_ph_sgc.call_args[0][1] == "node-007"
        )

    def test_set_gradient_client_port_from_node_conf(self):
        """
        set_gradient_client() must read gradient_osc_port from cm.node_conf.
        """
        ne = _make_node_engine(gradient_osc_port="7100")
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

        with patch.object(PLAYER_HANDLER, "set_gradient_client") as mock_ph_sgc:
            ne.set_gradient_client()

        mock_ph_sgc.assert_called_once()
        _, kwargs = mock_ph_sgc.call_args
        port_arg = kwargs.get("port") or mock_ph_sgc.call_args[0][0]
        assert port_arg == 7100


# ---------------------------------------------------------------------------
# stop_playback cancel-all ordering (T008)
# ---------------------------------------------------------------------------


class TestStopPlaybackCancelAll:
    def _make_ne_for_stop(self):
        ne = _make_node_engine()
        ne._project_generation = 0
        ne.script = MagicMock()
        ne.script.unix_name = "test-project"
        return ne

    def _stop_patches(self, ne, mock_gc=None):
        """
        Return a list of context managers that fully stub stop_playback
        dependencies.
        """
        from cuemsengine.cues.CueHandler import CUE_HANDLER
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

        return [
            patch.object(PLAYER_HANDLER, "get_gradient_client", return_value=mock_gc),
            patch.object(PLAYER_HANDLER, "get_dmx_player_client", return_value=None),
            patch.object(PLAYER_HANDLER, "kill_all_audio_players"),
            patch.object(PLAYER_HANDLER, "cleanup_zombie_jack_clients"),
            patch.object(ne, "unload_video_devs"),
            patch.object(ne, "set_status"),
            patch.object(ne, "ready_script"),
            patch.object(ne, "_broadcast_nextcue"),
        ]

    def test_cancel_all_fires_before_stop_all_cues(self):
        """
        stop_playback must cancel all in-flight fades BEFORE stopping cues.
        """
        ne = self._make_ne_for_stop()
        mock_gc = MagicMock()
        call_order = []

        from cuemsengine.cues.CueHandler import CUE_HANDLER
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

        patchers = self._stop_patches(ne, mock_gc=mock_gc)
        patchers.extend(
            [
                patch.object(
                    CUE_HANDLER,
                    "stop_all_cues",
                    side_effect=lambda: call_order.append("stop_all_cues"),
                ),
            ]
        )
        mock_gc.send_cancel_all.side_effect = lambda: call_order.append("cancel_all")

        import contextlib

        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            ne.stop_playback()

        assert "cancel_all" in call_order, "send_cancel_all must be called on stop"
        assert "stop_all_cues" in call_order, "stop_all_cues must be called on stop"
        assert call_order.index("cancel_all") < call_order.index(
            "stop_all_cues"
        ), "send_cancel_all must fire before stop_all_cues"

    def test_cancel_all_none_guard_on_stop_logs_debug(self, caplog):
        """
        When gradient_client is None, stop_playback logs DEBUG and does not
        crash.
        """
        ne = self._make_ne_for_stop()

        from cuemsengine.cues.CueHandler import CUE_HANDLER

        patchers = self._stop_patches(ne, mock_gc=None)
        patchers.append(patch.object(CUE_HANDLER, "stop_all_cues"))

        import contextlib

        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            with caplog.at_level(logging.DEBUG):
                ne.stop_playback()

        assert any(
            "gradient" in r.message.lower() and r.levelno == logging.DEBUG
            for r in caplog.records
        ), "must log DEBUG when gradient_client is None"


# ---------------------------------------------------------------------------
# _load_project_inner cancel-all ordering (T008)
# ---------------------------------------------------------------------------


class TestLoadProjectCancelAll:
    def _make_ne_for_load(self):
        ne = _make_node_engine()
        ne._project_generation = 0
        ne.script = MagicMock()
        ne.script.unix_name = "old-project"
        return ne

    def _load_patches(self, ne, mock_gc=None):
        """
        Return a list of context managers that fully stub _load_project_inner
        dependencies.
        """
        from cuemsengine.cues.CueHandler import CUE_HANDLER
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

        return [
            patch.object(PLAYER_HANDLER, "get_gradient_client", return_value=mock_gc),
            patch.object(PLAYER_HANDLER, "get_dmx_player_client", return_value=None),
            patch.object(PLAYER_HANDLER, "get_audio_mixer_client", return_value=None),
            patch.object(PLAYER_HANDLER, "kill_all_audio_players"),
            patch.object(PLAYER_HANDLER, "kill_orphaned_audio_processes"),
            patch.object(PLAYER_HANDLER, "cleanup_zombie_jack_clients"),
            patch.object(ne, "unload_video_devs"),
            patch.object(ne, "get_status", return_value="no"),
            patch.object(ne, "set_status"),
            patch.object(ne, "ready_project"),
            patch.object(ne, "ready_script"),
            patch.object(ne, "set_show_lock_file"),
            patch.object(ne, "_broadcast_nextcue"),
            patch.object(CUE_HANDLER, "disarm_all"),
        ]

    def test_cancel_all_fires_on_project_load(self):
        """_load_project_inner must send cancel_all before stopping cues."""
        ne = self._make_ne_for_load()
        mock_gc = MagicMock()
        call_order = []

        from cuemsengine.cues.CueHandler import CUE_HANDLER

        patchers = self._load_patches(ne, mock_gc=mock_gc)
        patchers.append(
            patch.object(
                CUE_HANDLER,
                "stop_all_cues",
                side_effect=lambda: call_order.append("stop_all_cues"),
            )
        )
        mock_gc.send_cancel_all.side_effect = lambda: call_order.append("cancel_all")

        import contextlib

        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            ne._load_project_inner("new-project")

        assert "cancel_all" in call_order, "send_cancel_all must be called on load"
        assert "stop_all_cues" in call_order, "stop_all_cues must be called on load"
        assert call_order.index("cancel_all") < call_order.index(
            "stop_all_cues"
        ), "send_cancel_all must fire before stop_all_cues on project load"

    def test_cancel_all_none_guard_on_load_logs_debug(self, caplog):
        """
        When gradient_client is None, _load_project_inner logs DEBUG and does
        not crash.
        """
        ne = self._make_ne_for_load()

        from cuemsengine.cues.CueHandler import CUE_HANDLER

        patchers = self._load_patches(ne, mock_gc=None)
        patchers.append(patch.object(CUE_HANDLER, "stop_all_cues"))

        import contextlib

        with contextlib.ExitStack() as stack:
            for p in patchers:
                stack.enter_context(p)
            with caplog.at_level(logging.DEBUG):
                ne._load_project_inner("new-project")

        assert any(
            "gradient" in r.message.lower() and r.levelno == logging.DEBUG
            for r in caplog.records
        ), "must log DEBUG when gradient_client is None on load"


# ---------------------------------------------------------------------------
# Port-binding test — US3 (T011)
# ---------------------------------------------------------------------------


class TestGradientOscPortBinding:
    def test_custom_port_flows_to_player_handler(self):
        """
        Custom gradient_osc_port in node_conf is forwarded as int to
        PLAYER_HANDLER.
        """
        ne = _make_node_engine(gradient_osc_port="7200", node_uuid="node-002")
        from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

        with patch.object(PLAYER_HANDLER, "set_gradient_client") as mock_sgc:
            ne.set_gradient_client()

        mock_sgc.assert_called_once()
        _, kwargs = mock_sgc.call_args
        port_arg = kwargs.get("port") or mock_sgc.call_args[0][0]
        assert port_arg == 7200, f"Expected port 7200, got {port_arg}"
        uuid_arg = kwargs.get("node_uuid") or mock_sgc.call_args[0][1]
        assert uuid_arg == "node-002"
