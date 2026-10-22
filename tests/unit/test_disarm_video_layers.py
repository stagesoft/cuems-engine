# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""CueHandler.disarm on a VideoCue (869f8hfra).

- A layer that /videocomposer/reset already removed (no longer registered in
  PLAYER_HANDLER) gets no writes: STOP resets first on purpose (instant
  blackout), so disarm_all used to hit endpoints that were gone and log
  "Node not found".
- Every disarm, the automatic one at cue end included, logs what it did and
  why. A silent disarm is not acceptable (Ion, 2026-09-28).
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import VideoCue


@pytest.fixture
def handler():
    from cuemsengine.cues.CueHandler import CueHandler

    h = object.__new__(CueHandler)
    h._armed_cues = []
    h._armed_cues_set = set()
    h._video_players = {}
    h._front_video_player = None
    h._lock = threading.Lock()
    h.communications_thread = MagicMock()
    return h


@pytest.fixture
def player_handler():
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    with PLAYER_HANDLER._lock:
        saved = set(PLAYER_HANDLER._loaded_layer_ids)
        PLAYER_HANDLER._loaded_layer_ids.clear()
    with patch.object(PLAYER_HANDLER, "remove_cue_player"):
        yield PLAYER_HANDLER
    with PLAYER_HANDLER._lock:
        PLAYER_HANDLER._loaded_layer_ids.clear()
        PLAYER_HANDLER._loaded_layer_ids.update(saved)


def _armed_video_cue(layer_ids=("cue_0",)) -> VideoCue:
    cue = VideoCue()
    cue.loaded = True
    cue._layer_ids = list(layer_ids)
    cue._osc = MagicMock()
    return cue


def _layer_writes(client, layer_id):
    return [
        c
        for c in client.set_value.call_args_list
        if layer_id in c.args[0] or (len(c.args) > 1 and c.args[1] == layer_id)
    ]


def _debug_messages(logger):
    return [str(c.args[0]) for c in logger.debug.call_args_list]


def test_registered_layer_is_hidden_unloaded_and_logged(handler, player_handler):
    cue = _armed_video_cue()
    player_handler.register_layer("cue_0")
    client = cue._osc
    with patch("cuemsengine.cues.CueHandler.Logger") as logger:
        assert handler.disarm(cue, reason="cue_end") is True

    client.set_value.assert_any_call("/videocomposer/layer/cue_0/visible", 0)
    client.set_value.assert_any_call("/videocomposer/layer/unload", "cue_0")
    client.remove_layer_endpoints.assert_called_once_with("cue_0")
    assert not player_handler.is_layer_registered("cue_0")
    lines = [m for m in _debug_messages(logger) if "Disarmed video cue" in m]
    assert len(lines) == 1
    assert str(cue.id) in lines[0]
    assert "cue_end" in lines[0]
    assert "cue_0" in lines[0]
    assert cue._layer_ids == []
    assert cue.loaded is False


def test_layer_already_removed_by_reset_gets_no_writes(handler, player_handler):
    cue = _armed_video_cue()  # never registered: /reset already cleared it
    client = cue._osc
    with patch("cuemsengine.cues.CueHandler.Logger") as logger:
        handler.disarm(cue, reason="ready_script")

    assert _layer_writes(client, "cue_0") == []
    client.remove_layer_endpoints.assert_not_called()
    lines = [m for m in _debug_messages(logger) if "Disarmed video cue" in m]
    assert len(lines) == 1
    assert "skipped" in lines[0]
    assert "cue_0" in lines[0]
    assert "ready_script" in lines[0]
    logger.warning.assert_not_called()
    assert cue._layer_ids == []
    assert cue.loaded is False


def test_only_the_removed_layer_is_skipped(handler, player_handler):
    cue = _armed_video_cue(layer_ids=("cue_0", "cue_1"))
    player_handler.register_layer("cue_1")
    client = cue._osc
    with patch("cuemsengine.cues.CueHandler.Logger"):
        handler.disarm(cue, reason="stop_action")

    assert _layer_writes(client, "cue_0") == []
    client.set_value.assert_any_call("/videocomposer/layer/cue_1/visible", 0)
    client.remove_layer_endpoints.assert_called_once_with("cue_1")


def test_a_failing_layer_write_is_a_warning_not_debug(handler, player_handler):
    cue = _armed_video_cue()
    player_handler.register_layer("cue_0")
    cue._osc.set_value.side_effect = ValueError("Node not found")
    with patch("cuemsengine.cues.CueHandler.Logger") as logger:
        handler.disarm(cue, reason="cue_end")

    warnings = [str(c.args[0]) for c in logger.warning.call_args_list]
    assert any("cue_0" in w and "Node not found" in w for w in warnings)
    assert cue._layer_ids == []


def test_reason_defaults_to_unspecified(handler, player_handler):
    cue = _armed_video_cue()
    with patch("cuemsengine.cues.CueHandler.Logger") as logger:
        handler.disarm(cue)
    lines = [m for m in _debug_messages(logger) if "Disarmed video cue" in m]
    assert len(lines) == 1
    assert "unspecified" in lines[0]


def test_disarm_all_passes_its_reason_to_every_cue(handler, player_handler):
    cues = [_armed_video_cue(layer_ids=(f"c{i}_0",)) for i in range(2)]
    handler._armed_cues = list(cues)
    with (
        patch.object(handler, "stop_all_cues"),
        patch.object(handler, "disarm", wraps=handler.disarm) as disarm,
        patch("cuemsengine.cues.CueHandler.Logger"),
    ):
        handler.disarm_all(reason="load")
    assert [c.kwargs.get("reason") for c in disarm.call_args_list] == ["load", "load"]


def test_a_failing_hide_still_unloads_the_layer(handler, player_handler):
    """visible 0 is cosmetic; a failure there must not skip the unload,
    or the layer stays loaded and the cue has already forgotten it."""
    cue = _armed_video_cue()
    player_handler.register_layer("cue_0")
    client = cue._osc

    def set_value(path, value):
        if path.endswith("/visible"):
            raise ValueError("Node not found")

    client.set_value.side_effect = set_value
    with patch("cuemsengine.cues.CueHandler.Logger") as logger:
        handler.disarm(cue, reason="cue_end")

    client.set_value.assert_any_call("/videocomposer/layer/unload", "cue_0")
    client.remove_layer_endpoints.assert_called_once_with("cue_0")
    assert not player_handler.is_layer_registered("cue_0")
    warnings = [str(c.args[0]) for c in logger.warning.call_args_list]
    assert any("cue_0" in w and "visible" in w for w in warnings)


def test_ready_script_disarms_with_its_callers_reason():
    """STOP reaches disarm_all through ready_script; its log must say stop."""
    from cuemsengine.NodeEngine import NodeEngine

    ne = object.__new__(NodeEngine)
    ne.script = MagicMock()
    ne._project_generation = 0
    with (
        patch.object(ne, "unload_video_devs"),
        patch("cuemsengine.NodeEngine.CUE_HANDLER") as ch,
        patch("cuemsengine.NodeEngine.PLAYER_HANDLER") as ph,
    ):
        ph.get_audio_mixer_client.return_value = None
        try:
            ne.ready_script(reason="stop")
        except Exception:
            pass  # only the disarm_all call matters here
    ch.disarm_all.assert_called_once_with(reason="stop")
