from unittest.mock import patch
from logging import INFO
from time import sleep
from cuemsengine import ControllerEngine, NodeEngine

from .conftest import engine_cleanup # type: ignore[import-untyped]
from .fixtures import mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, suppress_logging, mock_player_subprocess


def test_project_go_from_controller(mock_config_path, mock_avahi_resolve, mock_library_path, mock_controller_ip, mock_player_subprocess, suppress_logging, engine_cleanup):
    # ARRANGE
    caplog.set_level(INFO)
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    sleep(0.5)
    node_engine.set_players()
    controller_engine.load_project('complex_test')
    controller_engine.start()
    sleep(2)
    node_engine.start()
    # ACT
    node_engine.go_script('')

    sleep(2)
    
    # ASSERT
    assert controller_engine.script is not None
    assert node_engine.script is not None
    assert controller_engine.script.name == 'Test Main Script'
    assert node_engine.script.name == 'Test Main Script'
    assert 'Project complex_test loaded' in caplog.text
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

