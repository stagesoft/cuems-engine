from unittest.mock import patch
from logging import INFO
from time import sleep
from cuemsengine import ControllerEngine, NodeEngine

from .conftest import engine_cleanup # type: ignore[import-untyped]
from .fixtures import mock_config_path, mock_avahi_resolve, mock_library_path

def test_engine_instantiation(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup):
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

def test_project_load_on_controller(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog):
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

def test_complex_project_load_on_controller(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog):
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

@patch('cuemsengine.NodeEngine.NodeEngine.set_oscquery_values', print)
def test_project_load_on_node(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog, capfd):
    """Test the project load on the node"""
    # ARRANGE
    caplog.set_level(INFO)
    node_engine = NodeEngine(with_mtc=False)
    node_engine.set_oscquery()

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

@patch('cuemsengine.NodeEngine.NodeEngine.set_oscquery_values', print)
def test_project_load_on_node_from_oscquery(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog, capfd):
    """Test the project load on the node from OSCQuery"""
    # ARRANGE
    caplog.set_level(INFO)
    node_engine = NodeEngine(with_mtc=False)
    node_engine.set_oscquery()

    # ACT
    node_engine.oscquery_client.set_value('/engine/command/load', 'empty_test')

    # ASSERT
    assert node_engine.script is not None
    assert node_engine.script.unix_name == 'empty_test'
    assert 'Project empty_test loaded' in caplog.text
    assert 'No media files to deploy' in caplog.text
    assert node_engine.get_status('load') == 'empty_test'
    out, err = capfd.readouterr()
    # assert "/engine/status/running" in out
    # assert "/engine/command/go" in out
    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(node_engine)

def test_project_load_from_controller(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog):
    """Test the project load from the controller"""
    # ARRANGE
    caplog.set_level(INFO)
    controller_engine = ControllerEngine(with_mtc=False)
    controller_engine.set_oscquery()
    sleep(0.5)
    node_engine = NodeEngine(with_mtc=False)
    node_engine.set_oscquery()
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

def test_two_projects_load_on_controller(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog):
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


def test_two_projects_load_from_controller(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog):
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
    assert 'Project empty_test loaded' in caplog.text
    assert 'Project complex_test loaded' in caplog.text
    assert 'No media files to deploy' in caplog.text
    assert controller_engine.get_status('load') == 'complex_test'
    assert node_engine.get_status('load') == 'complex_test'

    # CLEANUP
    engine_cleanup(controller_engine)
    engine_cleanup(node_engine)
