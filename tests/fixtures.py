from pytest import fixture
from unittest.mock import patch
from cuemsengine.core.BaseEngine import MTC_PORT

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
