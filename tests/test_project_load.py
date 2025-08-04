from unittest.mock import patch, PropertyMock
import pytest
from pathlib import Path

from cuemsengine import ControllerEngine, NodeEngine

@pytest.fixture
def mock_config_path():
    """Mock ConfigManager to use test XML files"""
    test_conf_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    from os import environ
    environ['CUEMS_CONF_PATH'] = str(test_conf_path)

@pytest.fixture
def mock_avahi_resolve():
    """Mock avahi-resolve-host-name to return a fixed IP address"""
    def mock_avahi_resolve(hostname):
        return '192.168.1.1'
    with patch('cuemsengine.tools.CuemsDeploy.CuemsDeploy._avahi_resolve', 
               side_effect=mock_avahi_resolve):
        yield

# @pytest.fixture
# def mock_library_path():
#     """Mock library path to use test XML files"""
#     test_library_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
#     # Patch the library_path attribute after ConfigManager instantiation
#     with patch('cuemsutils.tools.ConfigManager.ConfigManager.library_path', 
#                new_callable=PropertyMock, return_value=str(test_library_path)):
#         yield test_library_path

# Alternative approach using monkeypatch (uncomment if preferred):
@pytest.fixture
def mock_library_path(monkeypatch):
    """Mock library path using monkeypatch"""
    test_library_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
    def mock_library_path_getter(self):
        return str(test_library_path)
    
    monkeypatch.setattr('cuemsutils.tools.ConfigManager.ConfigManager.library_path', 
                       property(mock_library_path_getter))
    yield test_library_path

# Most direct approach - patch the attribute value (uncomment if preferred):
# @pytest.fixture
# def mock_library_path():
#     """Mock library path by patching the attribute value directly"""
#     test_library_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
#     with patch('cuemsutils.tools.ConfigManager.ConfigManager.library_path'):
#         yield test_library_path

def test_engine_instantiation(mock_config_path, mock_avahi_resolve, mock_library_path):
    """Test the project load"""
    # ACT
    cuems_engine = ControllerEngine(with_mtc=False)
    node_engine = NodeEngine(with_mtc=False)

    # ASSERT
    assert cuems_engine.cm is not None
    assert node_engine.cm is not None
    assert cuems_engine.script is None
    assert node_engine.script is None

def test_project_load(mock_config_path, mock_avahi_resolve, mock_library_path):
    """Test the project load"""
    # ARRANGE
    cuems_engine = ControllerEngine(with_mtc=False)
    node_engine = NodeEngine(with_mtc=False)

    # ACT
    cuems_engine.load_project('empty_test')
    node_engine.load_project('empty_test')

    # ASSERT
    assert cuems_engine.script is not None
    assert node_engine.script is not None
    assert cuems_engine.script.unix_name == 'empty_test'
    assert node_engine.script.unix_name == 'empty_test'
