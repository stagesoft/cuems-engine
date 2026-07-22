# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import inspect
from logging import DEBUG, INFO
from time import sleep
from unittest.mock import MagicMock, patch

import pytest

from cuemsengine import ControllerEngine, NodeEngine
from cuemsengine.cues.CueHandler import CUE_HANDLER
from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

from .conftest import engine_cleanup  # type: ignore[import-untyped]
from .fixtures import (
    mock_avahi_resolve,
    mock_config_path,
    mock_controller_ip,
    mock_deploy_media_fail,
    mock_deploy_project_fail,
    mock_deploy_success,
    mock_library_path,
    mock_player_subprocess,
    suppress_logging,
)

# All tests in this module are integration-class
# (excluded from fast unit tests runs).
pytestmark = pytest.mark.integration


def test_engine_instantiation(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    engine_cleanup,
):
    """Test the project load"""
    # ACT
    controller_engine = ControllerEngine(with_mtc=False)
    node_engine = NodeEngine(with_mtc=False)

    # ASSERT
    assert controller_engine.cm is not None
    assert node_engine.cm is not None
    assert controller_engine.script is None
    assert node_engine.script is None

    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(controller_engine)
    engine_cleanup(node_engine)


def test_project_load_on_controller(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    engine_cleanup,
    caplog,
):
    """Test the project load on the controller"""
    # ARRANGE
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery_server()
    # ACT
    controller_engine.load_project("empty_test")

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == "empty_test"
    assert "Project empty_test loaded" in caplog.text
    # assert 'Project empty_test already loaded' in caplog.text
    assert controller_engine.get_status("load") == "empty_test"

    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(controller_engine)


def test_complex_project_load_on_controller(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    engine_cleanup,
    caplog,
):
    """Test the project load on the controller"""
    # ARRANGE
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery_server()
    # ACT
    controller_engine.load_project("complex_test")

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == "complex_test"
    assert "Project complex_test loaded" in caplog.text
    # assert 'Project complex_test already loaded' in caplog.text
    assert controller_engine.get_status("load") == "complex_test"

    # CLEANUP - now handled automatically by engine_cleanup fixture
    controller_engine.stop()
    engine_cleanup(controller_engine)


def test_project_load_on_node(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    mock_deploy_success,
    engine_cleanup,
    caplog,
    capfd,
):
    """Test the project load on the node"""
    # ARRANGE
    caplog.set_level(INFO)
    node_engine = NodeEngine(with_mtc=False)
    # node_engine.set_communications()

    # ACT
    node_engine.load_project("empty_test")

    # ASSERT
    assert node_engine.script is not None
    assert node_engine.script.unix_name == "empty_test"
    assert "Project empty_test loaded" in caplog.text
    assert "No media files to deploy" in caplog.text
    out, err = capfd.readouterr()
    # assert "/engine/status/running" in out
    # assert "/engine/command/go" in out
    assert node_engine.get_status("load") == "empty_test"

    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(node_engine)


def test_two_projects_load_on_controller(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    engine_cleanup,
    caplog,
):
    """Test the project load on the controller"""
    # ARRANGE
    caplog.set_level(INFO)
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_comms()
    # ACT
    controller_engine.load_project("empty_test")
    sleep(1)
    controller_engine.load_project("complex_test")
    sleep(1)

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == "complex_test"
    assert "Project empty_test loaded" in caplog.text
    # assert 'Project empty_test already loaded' in caplog.text
    assert "Project complex_test loaded" in caplog.text
    # assert 'Project complex_test already loaded' in caplog.text
    assert controller_engine.get_status("load") == "complex_test"

    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(controller_engine)


def test_project_deploy_failure_aborts_load_preserves_previous(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    engine_cleanup,
    caplog,
):
    """Deploy of project files fails → load aborts, previous project intact.

    The whole point of moving deploy_project before the teardown in
    _load_project_inner: if rsync of script/mappings/settings can't reach
    the controller, we must NOT destroy whatever was running before.
    """
    caplog.set_level(INFO)
    node_engine = NodeEngine(with_mtc=False)

    # Load once successfully so there is a "previous project" to preserve.
    with patch(
        "cuemsengine.tools.CuemsDeploy.CuemsDeploy.sync_files",
        return_value=True,
    ):
        node_engine.load_project("empty_test")
        assert node_engine.get_status("load") == "empty_test"

    # Now make project deploy fail (media succeeds, but we won't reach it).
    def selective(self, project, tag, file_names=None):
        return tag != "project"

    with patch(
        "cuemsengine.tools.CuemsDeploy.CuemsDeploy.sync_files",
        new=selective,
    ):
        result = node_engine.load_project("complex_test")

    assert result is False, "load_project should return False on deploy_project failure"
    assert "Project deploy FAILED" in caplog.text
    assert "aborting load" in caplog.text
    # Previous project survives — load status unchanged
    assert node_engine.get_status("load") == "empty_test"

    engine_cleanup(node_engine)


def test_disabled_deploy_manager_aborts_load_cleanly(
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    engine_cleanup,
    caplog,
):
    """controller_ip=None → CuemsDeploy disabled → load aborts cleanly.

    Simulates network_map.xml without a controller IP. Should NOT crash;
    should fail-fast at deploy_project, log the disabled state, and leave
    the engine usable.
    """
    caplog.set_level(INFO)
    with patch(
        "cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip",
        return_value=None,
    ):
        node_engine = NodeEngine(with_mtc=False)

        result = node_engine.load_project("empty_test")

        assert result is False
        assert "CuemsDeploy disabled" in caplog.text
        assert "Project deploy FAILED" in caplog.text

        engine_cleanup(node_engine)


class TestSharedTeardownRearmHelpers:
    """_load_project_inner and stop_playback used to duplicate three teardown/
    rearm steps verbatim: gradient cancel-all, DMX reset (disable_mtcfollow +
    blackout), and notifying the Controller that (re)arming is complete.

    These are now factored into NodeEngine._gradient_cancel_all / _dmx_reset /
    _notify_armed_ready. This class covers the extracted helpers directly and
    verifies both call sites actually delegate to them, so the duplication
    can't silently creep back in.
    """

    # ---- _gradient_cancel_all ---------------------------------------------

    def test_gradient_cancel_all_sends_cancel_when_client_present(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
    ):
        node_engine = NodeEngine(with_mtc=False)
        mock_gc = MagicMock()

        with patch.object(PLAYER_HANDLER, "get_gradient_client", return_value=mock_gc):
            node_engine._gradient_cancel_all("test-context")

        mock_gc.send_cancel_all.assert_called_once()
        engine_cleanup(node_engine)

    def test_gradient_cancel_all_exception_logs_error_with_context(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
        caplog,
    ):
        caplog.set_level(INFO)
        node_engine = NodeEngine(with_mtc=False)
        mock_gc = MagicMock()
        mock_gc.send_cancel_all.side_effect = RuntimeError("boom")

        with patch.object(PLAYER_HANDLER, "get_gradient_client", return_value=mock_gc):
            node_engine._gradient_cancel_all("test-context")  # must not raise

        assert "gradient send_cancel_all failed on test-context" in caplog.text
        assert "boom" in caplog.text
        engine_cleanup(node_engine)

    def test_gradient_cancel_all_none_client_logs_debug_with_context(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
        caplog,
    ):
        caplog.set_level(DEBUG)
        node_engine = NodeEngine(with_mtc=False)

        with patch.object(PLAYER_HANDLER, "get_gradient_client", return_value=None):
            node_engine._gradient_cancel_all("test-context")  # must not raise

        assert "skipping cancel_all on test-context" in caplog.text
        engine_cleanup(node_engine)

    # ---- _dmx_reset ---------------------------------------------------------

    def test_dmx_reset_disables_mtcfollow_then_blackout_in_order(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
    ):
        node_engine = NodeEngine(with_mtc=False)
        mock_dmx = MagicMock()
        order = []
        mock_dmx.disable_mtcfollow.side_effect = lambda: order.append("disable")
        mock_dmx.send_blackout.side_effect = lambda: order.append("blackout")

        with patch.object(
            PLAYER_HANDLER, "get_dmx_player_client", return_value=mock_dmx
        ):
            node_engine._dmx_reset()

        assert order == ["disable", "blackout"]
        engine_cleanup(node_engine)

    def test_dmx_reset_disable_failure_still_calls_blackout(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
        caplog,
    ):
        caplog.set_level(INFO)
        node_engine = NodeEngine(with_mtc=False)
        mock_dmx = MagicMock()
        mock_dmx.disable_mtcfollow.side_effect = RuntimeError("nope")

        with patch.object(
            PLAYER_HANDLER, "get_dmx_player_client", return_value=mock_dmx
        ):
            node_engine._dmx_reset()  # must not raise

        mock_dmx.send_blackout.assert_called_once()
        assert "DMX disable mtcfollow failed" in caplog.text
        engine_cleanup(node_engine)

    def test_dmx_reset_blackout_failure_is_logged_independently(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
        caplog,
    ):
        caplog.set_level(INFO)
        node_engine = NodeEngine(with_mtc=False)
        mock_dmx = MagicMock()
        mock_dmx.send_blackout.side_effect = RuntimeError("nope")

        with patch.object(
            PLAYER_HANDLER, "get_dmx_player_client", return_value=mock_dmx
        ):
            node_engine._dmx_reset()  # must not raise

        assert "DMX blackout failed" in caplog.text
        engine_cleanup(node_engine)

    def test_dmx_reset_none_client_is_noop(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
    ):
        node_engine = NodeEngine(with_mtc=False)

        with patch.object(PLAYER_HANDLER, "get_dmx_player_client", return_value=None):
            node_engine._dmx_reset()  # must not raise

        engine_cleanup(node_engine)

    # ---- _notify_armed_ready -------------------------------------------------

    def test_notify_armed_ready_sends_operation_with_context(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
    ):
        node_engine = NodeEngine(with_mtc=False)
        mock_comms = MagicMock()

        with patch.object(
            CUE_HANDLER, "communications_thread", mock_comms, create=True
        ):
            node_engine._notify_armed_ready("test-context")

        mock_comms.send_operation.assert_called_once()
        operation = mock_comms.send_operation.call_args.args[0]
        assert operation.target == "armed_ready"
        assert operation.data == {"armed": "yes"}
        assert operation.sender == node_engine.cm.node_uuid
        assert mock_comms.send_operation.call_args.kwargs.get("timeout") == 0.1
        engine_cleanup(node_engine)

    def test_notify_armed_ready_logs_debug_with_context(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
        caplog,
    ):
        caplog.set_level(DEBUG)
        node_engine = NodeEngine(with_mtc=False)

        with patch.object(
            CUE_HANDLER, "communications_thread", MagicMock(), create=True
        ):
            node_engine._notify_armed_ready("test-context")

        assert "Notified Controller that test-context is complete" in caplog.text
        engine_cleanup(node_engine)

    def test_notify_armed_ready_exception_logs_warning_not_raised(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
        caplog,
    ):
        caplog.set_level(INFO)
        node_engine = NodeEngine(with_mtc=False)
        mock_comms = MagicMock()
        mock_comms.send_operation.side_effect = RuntimeError("nng down")

        with patch.object(
            CUE_HANDLER, "communications_thread", mock_comms, create=True
        ):
            node_engine._notify_armed_ready("test-context")  # must not raise

        assert "Could not notify Controller of armed_ready" in caplog.text
        engine_cleanup(node_engine)

    # ---- delegation: both call sites use the shared helpers -----------------

    def test_load_project_delegates_to_shared_helpers(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        mock_deploy_success,
        engine_cleanup,
    ):
        node_engine = NodeEngine(with_mtc=False)

        with (
            patch.object(node_engine, "_gradient_cancel_all") as mock_gradient,
            patch.object(node_engine, "_dmx_reset") as mock_dmx,
            patch.object(node_engine, "_notify_armed_ready") as mock_notify,
        ):
            node_engine.load_project("empty_test")

        mock_gradient.assert_called_once_with("project load")
        mock_dmx.assert_called_once_with()
        mock_notify.assert_called_once_with("arming after load")
        engine_cleanup(node_engine)

    def test_stop_playback_delegates_to_shared_helpers(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        mock_deploy_success,
        engine_cleanup,
    ):
        node_engine = NodeEngine(with_mtc=False)
        node_engine.load_project("empty_test")

        with (
            patch.object(node_engine, "_gradient_cancel_all") as mock_gradient,
            patch.object(node_engine, "_dmx_reset") as mock_dmx,
            patch.object(node_engine, "_notify_armed_ready") as mock_notify,
        ):
            node_engine.stop_playback()

        mock_gradient.assert_called_once_with("stop")
        mock_dmx.assert_called_once_with()
        mock_notify.assert_called_once_with("re-arm")
        engine_cleanup(node_engine)

    def test_load_and_stop_both_call_the_shared_helper_methods(
        self,
        mock_config_path,
        mock_avahi_resolve,
        mock_library_path,
        mock_controller_ip,
        engine_cleanup,
    ):
        """Regression guard against the duplication creeping back in: both
        call sites must reference the shared helper methods by name, not
        reimplement the logic inline."""
        node_engine = NodeEngine(with_mtc=False)

        load_src = inspect.getsource(node_engine._load_project_inner)
        stop_src = inspect.getsource(node_engine.stop_playback)
        for helper in ("_gradient_cancel_all", "_dmx_reset", "_notify_armed_ready"):
            assert f"self.{helper}(" in load_src, f"{helper} missing from load path"
            assert f"self.{helper}(" in stop_src, f"{helper} missing from stop path"

        engine_cleanup(node_engine)
