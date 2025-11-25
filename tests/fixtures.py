from pytest import fixture
from unittest.mock import patch, PropertyMock
from cuemsengine.core.BaseEngine import MTC_PORT
from pathlib import Path

@fixture
def mock_config_manager():
    with patch('cuemsutils.tools.ConfigManager.ConfigManager') as mock_cm:
        mock_cm.node_conf = {
            'uuid': 'test_node',
            'mtc_port': MTC_PORT
        }
        mock_cm.return_value.tmp_path = '/tmp'
        mock_cm.return_value.library_path = '/library'
        yield mock_cm

@fixture
def mock_project_mappings():
    with patch('cuemsutils.xml.ProjectMappings.get_node') as mock_pm:
        mock_pm.return_value = mock_pm.get_dict()['nodes'][0]['node']
        yield mock_pm

@fixture
def env_config_path():
    """Mock ConfigManager to use test XML files"""
    from pathlib import Path
    from os import environ
    test_conf_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'

    environ['CUEMS_CONF_PATH'] = str(test_conf_path)

@fixture
def mock_mtc_listener():
    with patch('cuemsengine.tools.MtcListener.MtcListener') as mock_mtc:
        yield mock_mtc

@fixture
def ossia_client_factory():
    from cuemsengine.osc.OssiaClient import OssiaClient
    from contextlib import contextmanager
    
    @contextmanager
    def create_client(**kwargs):
        client = OssiaClient(**kwargs)

        try:
            yield client
        finally:
            del client
    yield create_client

@fixture
def ossia_server_factory():
    from cuemsengine.osc.OssiaServer import OssiaServer
    from contextlib import contextmanager
    
    @contextmanager
    def create_server(**kwargs):
        try:
            server = OssiaServer(**kwargs)
        except Exception as e:
            print(e)
            print(type(e))
            raise e
        try:
            yield server
        finally:
            del server
    yield create_server


@fixture
def mock_config_path():
    """Mock ConfigManager to use test XML files"""
    test_conf_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    from os import environ
    environ['CUEMS_CONF_PATH'] = str(test_conf_path)

@fixture
def mock_avahi_resolve():
    """Mock avahi-resolve-host-name to return a fixed IP address"""
    def mock_avahi_resolve(hostname):
        return 'localhost'
    with patch('cuemsengine.tools.CuemsDeploy.CuemsDeploy._avahi_resolve', 
               side_effect=mock_avahi_resolve):
        yield

@fixture
def mock_controller_ip():
    """Mock BaseEngine.get_controller_ip to return localhost"""
    with patch('cuemsengine.core.BaseEngine.BaseEngine.get_controller_ip', 
               return_value='localhost'):
        yield

# @fixture
# def mock_library_path():
#     """Mock library path to use test XML files"""
#     test_library_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
#     # Patch the library_path attribute after ConfigManager instantiation
#     with patch('cuemsutils.tools.ConfigManager.ConfigManager.library_path', 
#                new_callable=PropertyMock, return_value=str(test_library_path)):
#         yield test_library_path

# Alternative approach using monkeypatch (uncomment if preferred):
@fixture
def mock_library_path(monkeypatch):
    """Mock library path using monkeypatch"""
    test_library_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
    def mock_library_path_getter(self):
        return str(test_library_path)
    
    monkeypatch.setattr('cuemsutils.tools.ConfigManager.ConfigManager.library_path', 
                       property(mock_library_path_getter))
    yield test_library_path

# Most direct approach - patch the attribute value (uncomment if preferred):
# @fixture
# def mock_library_path():
#     """Mock library path by patching the attribute value directly"""
#     test_library_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
#     with patch('cuemsutils.tools.ConfigManager.ConfigManager.library_path'):
#         yield test_library_path
