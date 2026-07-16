# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Tests for ControllerEngine cleanup consolidation and new commands.

Tests _clear_playback_state(), refactored load_project/stop_script,
and new get_project_status/unload_project/handle_editor_command dict returns.
"""
from os import environ
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest


@pytest.fixture(autouse=True)
def set_config_path():
    """Point CUEMS_CONF_PATH at test XML files."""
    test_conf_path = Path(__file__).parent / ".." / "dev" / "test_xml_files"
    environ["CUEMS_CONF_PATH"] = str(test_conf_path)


@pytest.fixture
def controller():
    """Create a minimal ControllerEngine with all heavy deps mocked out."""
    with (
        patch("cuemsengine.core.BaseEngine.ConfigManager") as MockCM,
        patch(
            "cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip",
            return_value="localhost",
        ),
    ):

        mock_cm_instance = MockCM.return_value
        mock_cm_instance.node_conf = {
            "uuid": "test-controller-uuid",
            "mtc_port": "MTC_MIDI_PORT",
        }
        mock_cm_instance.library_path = str(
            Path(__file__).parent / ".." / "dev" / "test_xml_files"
        )
        mock_cm_instance.tmp_path = "/tmp"

        from cuemsengine.ControllerEngine import ControllerEngine

        engine = ControllerEngine(with_mtc=False)

        # Mock communications_thread for _broadcast_status and
        # _forward_command_to_nodes
        engine.communications_thread = Mock()
        engine.communications_thread.broadcast_osc = Mock()
        engine.communications_thread.nng_hub = Mock()

        yield engine

        engine.stop()


# ─── _clear_playback_state ───────────────────────────────────────────────


class TestClearPlaybackState:
    def test_clears_broadcast_timestamps(self, controller):
        controller._cue_broadcast_timestamps = {"cue1": 1.0, "cue2": 2.0}
        controller._clear_playback_state()
        assert controller._cue_broadcast_timestamps == {}

    def test_resets_last_timecode_second(self, controller):
        controller._last_timecode_second = 42
        controller._clear_playback_state()
        assert controller._last_timecode_second == -1

    def test_broadcasts_timecode_zero(self, controller):
        controller._clear_playback_state()
        controller.communications_thread.broadcast_osc.assert_any_call(
            "/engine/status/timecode", 0
        )

    def test_sets_armed_no(self, controller):
        controller.set_status("armed", "yes")
        controller._clear_playback_state()
        assert controller.get_status("armed") == "no"

    def test_clears_nextcue(self, controller):
        controller.set_status("nextcue", "some-cue-id")
        controller._clear_playback_state()
        assert controller.get_status("nextcue") == ""

    def test_stops_timecode(self, controller):
        with patch.object(controller, "stop_timecode") as mock_stop_tc:
            controller._clear_playback_state()
            mock_stop_tc.assert_called_once()


# ─── stop_script refactored ─────────────────────────────────────────────


class TestStopScriptRefactored:
    def test_stop_when_not_running_returns_none(self, controller):
        controller.set_status("running", "no")
        result = controller.stop_script("stop")
        assert result is None

    def test_stop_calls_clear_playback_state(self, controller):
        controller.set_status("running", "yes")
        with (
            patch.object(controller, "_clear_playback_state") as mock_clear,
            patch.object(controller, "_forward_command_to_nodes"),
        ):
            controller.stop_script("stop")
            mock_clear.assert_called_once()

    def test_stop_sets_running_no(self, controller):
        controller.set_status("running", "yes")
        with patch.object(controller, "_forward_command_to_nodes"):
            controller.stop_script("stop")
        assert controller.get_status("running") == "no"

    def test_stop_nulls_go_offset(self, controller):
        controller.set_status("running", "yes")
        controller.go_offset = 12345
        with patch.object(controller, "_forward_command_to_nodes"):
            controller.stop_script("stop")
        assert controller.go_offset is None

    def test_stop_resets_cue_status_values_to_zero(self, controller):
        controller.set_status("running", "yes")
        controller.cue_status = {"cue1": 50, "cue2": 100, "cue3": 1}
        with patch.object(controller, "_forward_command_to_nodes"):
            controller.stop_script("stop")
        assert all(v == 0 for v in controller.cue_status.values())
        # Keys must be preserved
        assert set(controller.cue_status.keys()) == {"cue1", "cue2", "cue3"}

    def test_stop_forwards_stop_to_nodes(self, controller):
        controller.set_status("running", "yes")
        with patch.object(controller, "_forward_command_to_nodes") as mock_fwd:
            controller.stop_script("stop")
            mock_fwd.assert_called_once_with("/engine/command/stop", "stop")

    def test_stop_returns_true(self, controller):
        controller.set_status("running", "yes")
        with patch.object(controller, "_forward_command_to_nodes"):
            result = controller.stop_script("stop")
        assert result is True


# ─── get_project_status ──────────────────────────────────────────────────


class TestGetProjectStatus:
    def test_returns_none_when_not_running(self, controller):
        controller.set_status("running", "no")
        result = controller.get_project_status(None)
        assert result == {"status": "none", "project_uuid": ""}

    def test_returns_none_when_no_script(self, controller):
        controller.set_status("running", "no")
        controller.script = None
        result = controller.get_project_status(None)
        assert result == {"status": "none", "project_uuid": ""}

    def test_returns_running_with_uuid(self, controller):
        controller.set_status("running", "yes")
        mock_script = Mock()
        mock_script.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        controller.script = mock_script
        result = controller.get_project_status(None)
        assert result == {
            "status": "running",
            "project_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        }

    def test_loaded_but_not_playing_returns_none(self, controller):
        """A loaded but not playing project should report status 'none'."""
        controller.set_status("running", "no")
        mock_script = Mock()
        mock_script.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        controller.script = mock_script
        result = controller.get_project_status(None)
        assert result == {"status": "none", "project_uuid": ""}


# ─── unload_project ─────────────────────────────────────────────────────


class TestUnloadProject:
    def test_rejects_when_running(self, controller):
        controller.set_status("running", "yes")
        with pytest.raises(RuntimeError, match="Cannot unload while running"):
            controller.unload_project(None)

    def test_calls_clear_playback_state(self, controller):
        controller.set_status("running", "no")
        with (
            patch.object(controller, "_clear_playback_state") as mock_clear,
            patch.object(controller, "_forward_command_to_nodes"),
        ):
            controller.unload_project(None)
            mock_clear.assert_called_once()

    def test_calls_reset_script(self, controller):
        controller.set_status("running", "no")
        with (
            patch.object(controller, "reset_script") as mock_reset,
            patch.object(controller, "_forward_command_to_nodes"),
        ):
            controller.unload_project(None)
            mock_reset.assert_called_once()

    def test_clears_cue_status(self, controller):
        controller.set_status("running", "no")
        controller.cue_status = {"cue1": 0, "cue2": 100}
        with patch.object(controller, "_forward_command_to_nodes"):
            controller.unload_project(None)
        assert controller.cue_status == {}

    def test_clears_load_status(self, controller):
        controller.set_status("running", "no")
        controller.set_status("load", "my_project")
        with patch.object(controller, "_forward_command_to_nodes"):
            controller.unload_project(None)
        assert controller.get_status("load") == ""

    def test_forwards_stop_to_nodes(self, controller):
        controller.set_status("running", "no")
        with patch.object(controller, "_forward_command_to_nodes") as mock_fwd:
            controller.unload_project(None)
            mock_fwd.assert_called_once_with("/engine/command/stop", None)

    def test_returns_true(self, controller):
        controller.set_status("running", "no")
        with patch.object(controller, "_forward_command_to_nodes"):
            result = controller.unload_project(None)
        assert result is True


# ─── handle_editor_command dict returns ──────────────────────────────────


class TestHandleEditorCommandDictReturn:
    def test_dict_return_passed_as_value(self, controller):
        """
        When command returns a dict, confirm_to_editor gets that dict as value.
        """
        with (
            patch.object(controller, "confirm_to_editor") as mock_confirm,
            patch.object(controller, "set_editor_request"),
        ):
            controller.handle_editor_command("project_status", None, context="ctx")
            mock_confirm.assert_called_once()
            call_kwargs = mock_confirm.call_args
            # value should be a dict, not 'OK'
            assert isinstance(call_kwargs[1]["value"], dict)
            assert call_kwargs[1]["type"] == "project_status"

    def test_bool_return_sends_ok(self, controller):
        """When command returns True (bool), confirm_to_editor gets 'OK'."""
        controller.set_status("running", "no")
        with (
            patch.object(controller, "confirm_to_editor") as mock_confirm,
            patch.object(controller, "set_editor_request"),
            patch.object(controller, "_forward_command_to_nodes"),
        ):
            controller.handle_editor_command("project_unload", None, context="ctx")
            mock_confirm.assert_called_once()
            assert mock_confirm.call_args[1]["value"] == "OK"

    def test_unknown_command_raises(self, controller):
        with pytest.raises(ValueError, match="not recognized"):
            controller.handle_editor_command("nonexistent_command", None)

    def test_project_status_in_command_dict(self, controller):
        """project_status must be in command_dict and callable."""
        with (
            patch.object(controller, "confirm_to_editor"),
            patch.object(controller, "set_editor_request"),
        ):
            # Should not raise
            controller.handle_editor_command("project_status", None)

    def test_project_unload_in_command_dict(self, controller):
        """project_unload must be in command_dict and callable."""
        controller.set_status("running", "no")
        with (
            patch.object(controller, "confirm_to_editor"),
            patch.object(controller, "set_editor_request"),
            patch.object(controller, "_forward_command_to_nodes"),
        ):
            controller.handle_editor_command("project_unload", None)
