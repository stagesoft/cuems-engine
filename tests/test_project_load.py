# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import pytest
from unittest.mock import patch
from logging import INFO
from time import sleep
from cuemsengine import ControllerEngine, NodeEngine

from .conftest import engine_cleanup # type: ignore[import-untyped]
from .fixtures import (
    mock_config_path,
    mock_avahi_resolve,
    mock_library_path,
    mock_controller_ip,
    mock_deploy_success,
    mock_deploy_project_fail,
    mock_deploy_media_fail,
    suppress_logging,
    mock_player_subprocess,
)

def test_engine_instantiation(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, engine_cleanup):
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

def test_project_load_on_controller(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, engine_cleanup, caplog):
    """Test the project load on the controller"""
    # ARRANGE
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    # ACT
    controller_engine.load_project('empty_test')

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == 'empty_test'
    assert 'Project empty_test loaded' in caplog.text
    # assert 'Project empty_test already loaded' in caplog.text
    assert controller_engine.get_status('load') == 'empty_test'
    
    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(controller_engine)

def test_complex_project_load_on_controller(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, engine_cleanup, caplog):
    """Test the project load on the controller"""
    # ARRANGE
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    # ACT
    controller_engine.load_project('complex_test')

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == 'complex_test'
    assert 'Project complex_test loaded' in caplog.text
    # assert 'Project complex_test already loaded' in caplog.text
    assert controller_engine.get_status('load') == 'complex_test'
    
    # CLEANUP - now handled automatically by engine_cleanup fixture
    controller_engine.stop()
    engine_cleanup(controller_engine)

def test_project_load_on_node(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, mock_deploy_success, engine_cleanup, caplog, capfd):
    """Test the project load on the node"""
    # ARRANGE
    caplog.set_level(INFO)
    node_engine = NodeEngine(with_mtc=False)
    # node_engine.set_communications()

    # ACT
    node_engine.load_project('empty_test')

    # ASSERT
    assert node_engine.script is not None
    assert node_engine.script.unix_name == 'empty_test'
    assert 'Project empty_test loaded' in caplog.text
    assert 'No media files to deploy' in caplog.text
    out, err = capfd.readouterr()
    # assert "/engine/status/running" in out
    # assert "/engine/command/go" in out
    assert node_engine.get_status('load') == 'empty_test'

    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(node_engine)

def test_project_load_from_controller(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, mock_deploy_success, engine_cleanup, caplog):
    """Test the project load from the controller"""
    # ARRANGE
    caplog.set_level(INFO)
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    sleep(0.5)
    node_engine = NodeEngine(with_mtc=False)
    node_engine.set_communications()
    sleep(0.5)
    # ACT
    controller_engine.load_project('empty_test')
    sleep(1)

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == 'empty_test'
    assert node_engine.script is not None
    assert node_engine.script.unix_name == 'empty_test'
    assert 'Project empty_test loaded' in caplog.text
    assert 'No media files to deploy' in caplog.text
    assert node_engine.get_status('load') == 'empty_test'

    # CLEANUP
    engine_cleanup(controller_engine)
    engine_cleanup(node_engine)

def test_two_projects_load_on_controller(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, engine_cleanup, caplog):
    """Test the project load on the controller"""
    # ARRANGE
    caplog.set_level(INFO)
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    # ACT
    controller_engine.load_project('empty_test')
    sleep(1)
    controller_engine.load_project('complex_test')
    sleep(1)

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == 'complex_test'
    assert 'Project empty_test loaded' in caplog.text
    # assert 'Project empty_test already loaded' in caplog.text
    assert 'Project complex_test loaded' in caplog.text
    # assert 'Project complex_test already loaded' in caplog.text
    assert controller_engine.get_status('load') == 'complex_test'
    
    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(controller_engine)


def test_two_projects_load_from_controller(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, mock_deploy_success, mock_player_subprocess, engine_cleanup):
    """Test the project load from the controller"""
    # ARRANGE
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    sleep(0.5)
    node_engine = NodeEngine(with_mtc=False)
    node_engine.set_communications()
    node_engine.set_players()
    sleep(0.5)

    # ACT
    controller_engine.load_project('empty_test')
    sleep(2)
    controller_engine.load_project('complex_test')
    sleep(2)
    
    # ASSERT
    assert controller_engine.script is not None
    assert node_engine.script is not None
    assert controller_engine.script.name == 'Test Main Script'
    assert node_engine.script.name == 'Test Main Script'
    assert controller_engine.get_status('load') == 'complex_test'
    assert node_engine.get_status('load') == 'complex_test'
    
    # Assert player subprocess calls were mocked and recorded
    assert len(mock_player_subprocess) > 0, "Expected player subprocess calls to be recorded"
    player_types = {call['player'] for call in mock_player_subprocess}
    assert 'VideoPlayer' in player_types, "Expected VideoPlayer to be called"
    # Verify each call has required fields
    for call in mock_player_subprocess:
        assert 'player' in call
        assert 'args' in call
        assert 'pid' in call
        assert isinstance(call['args'], list), "Call args should be a list"

    # CLEANUP
    engine_cleanup(controller_engine)
    engine_cleanup(node_engine)


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
        'cuemsengine.tools.CuemsDeploy.CuemsDeploy.sync_files',
        return_value=True,
    ):
        node_engine.load_project('empty_test')
        assert node_engine.get_status('load') == 'empty_test'

    # Now make project deploy fail (media succeeds, but we won't reach it).
    def selective(self, project, tag, file_names=None):
        return tag != 'project'

    with patch(
        'cuemsengine.tools.CuemsDeploy.CuemsDeploy.sync_files',
        new=selective,
    ):
        result = node_engine.load_project('complex_test')

    assert result is False, "load_project should return False on deploy_project failure"
    assert 'Project deploy FAILED' in caplog.text
    assert 'aborting load' in caplog.text
    # Previous project survives — load status unchanged
    assert node_engine.get_status('load') == 'empty_test'

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
        'cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip',
        return_value=None,
    ):
        node_engine = NodeEngine(with_mtc=False)

        result = node_engine.load_project('empty_test')

        assert result is False
        assert 'CuemsDeploy disabled' in caplog.text
        assert 'Project deploy FAILED' in caplog.text

        engine_cleanup(node_engine)
