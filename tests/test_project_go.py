from unittest.mock import patch
from logging import INFO
from time import sleep
from cuemsengine import ControllerEngine, NodeEngine

from .conftest import engine_cleanup # type: ignore[import-untyped]
from .fixtures import mock_config_path, mock_avahi_resolve, mock_library_path


def test_project_go_from_controller(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog):
    """Test the project load from the controller"""
    from os import environ
    environ['CUEMS_LOG_LEVEL'] = 'info'
    # ARRANGE
    caplog.set_level(INFO)
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    sleep(0.5)
    node_engine = NodeEngine(with_mtc=False)
    node_engine.set_oscquery()
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
    assert 'GO command received. Starting cue' in caplog.text


    # CLEANUP
    engine_cleanup(controller_engine)
    engine_cleanup(node_engine)
