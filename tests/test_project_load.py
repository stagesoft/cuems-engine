from logging import INFO
from .conftest import engine_cleanup # type: ignore[import-untyped]
from .fixtures import mock_config_path, mock_avahi_resolve, mock_library_path

from cuemsengine import ControllerEngine, NodeEngine

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
    # ACT
    controller_engine.load_project('empty_test')

    # ASSERT
    assert controller_engine.script is not None
    assert controller_engine.script.unix_name == 'empty_test'
    assert 'Project empty_test loaded' in caplog.text
    assert 'Project empty_test already loaded' in caplog.text
    assert controller_engine.get_status('load') == 'empty_test'
    
    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(controller_engine)

def test_project_load_on_node(mock_config_path, mock_avahi_resolve, mock_library_path, engine_cleanup, caplog):
    """Test the project load on the node"""
    # ARRANGE
    caplog.set_level(INFO)
    node_engine = NodeEngine(with_mtc=False)

    # ACT
    node_engine.load_project('empty_test')

    # ASSERT
    assert node_engine.script is not None
    assert node_engine.script.unix_name == 'empty_test'
    assert 'Project empty_test loaded' in caplog.text
    assert 'No media files to deploy' in caplog.text
    assert node_engine.get_status('load') == 'empty_test'

    # CLEANUP - now handled automatically by engine_cleanup fixture
    engine_cleanup(node_engine)
