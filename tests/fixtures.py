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
    """Mock avahi-resolve-host-name to return a fixed IP address.

    Retained for backwards compatibility: CuemsDeploy no longer calls
    _avahi_resolve during __init__ when controller_ip is provided (the
    normal path now), but tests still apply this patch so the legacy
    hostname-fallback path also returns a usable value if exercised.
    """
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

@fixture
def mock_deploy_success():
    """Mock CuemsDeploy.sync_files to always succeed.

    Used by NodeEngine tests so they don't actually invoke rsync
    against localhost:873 (which isn't running in CI / dev envs).
    Without this, deploy_project would return False and the new
    fail-fast guard in _load_project_inner would abort every test.
    """
    with patch('cuemsengine.tools.CuemsDeploy.CuemsDeploy.sync_files',
               return_value=True):
        yield

@fixture
def mock_deploy_project_fail():
    """Mock CuemsDeploy.sync_files to fail only for project deploys.

    Lets tests exercise the abort-on-project-deploy-failure path
    without touching the network. tag='media' still returns True
    so we can also verify the asymmetric policy.
    """
    def selective(self, project, tag, file_names=None):
        return tag != 'project'
    with patch('cuemsengine.tools.CuemsDeploy.CuemsDeploy.sync_files',
               new=selective):
        yield

@fixture
def mock_deploy_media_fail():
    """Mock CuemsDeploy.sync_files to fail only for media deploys.

    project deploy still succeeds, so the load completes; media
    failure should log an error but not abort. Verifies the
    asymmetric policy.
    """
    def selective(self, project, tag, file_names=None):
        return tag != 'media'
    with patch('cuemsengine.tools.CuemsDeploy.CuemsDeploy.sync_files',
               new=selective):
        yield

@fixture
def suppress_logging(level:str ='info'):
    """Suppress all logging output to stdout/stderr"""
    import logging
    from os import environ
    level = level.upper()
    level_value = getattr(logging, level)
    
    # Set environment variable to CRITICAL level
    environ['CUEMS_LOG_LEVEL'] = level
    
    # Disable all logging below CRITICAL level
    logging.disable(level_value - 1)
    
    yield
    
    # Re-enable logging
    logging.disable(logging.NOTSET)

@fixture
def mock_player_subprocess():
    """Mock player subprocess calls to prevent actual player process startup"""
    from unittest.mock import MagicMock
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
    
    # Complete reset of PLAYER_HANDLER state before test
    PLAYER_HANDLER.reset_all()
    
    # Create a mock that records calls
    call_records = []
    
    def mock_call_subprocess(self, call_args):
        """Mock implementation that records the call without starting process"""
        call_records.append({
            'player': self.__class__.__name__,
            'args': call_args,
            'pid': id(self)  # Use object id as fake PID
        })
        # Set up mock process
        self.p = MagicMock()
        self.p.pid = id(self)
        self.p.poll = MagicMock(return_value=None)
        self.pid = id(self)
        self.status = 'running'
        self.error = None
    
    with patch('cuemsengine.players.Player.Player.call_subprocess', mock_call_subprocess):
        yield call_records
    
    # Complete cleanup after test
    PLAYER_HANDLER.reset_all()

@fixture
def mock_player_clients():
    """Mock PlayerClient creation to record commands without OSC communication"""
    from unittest.mock import MagicMock, Mock
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER
    
    # Complete reset before test
    PLAYER_HANDLER.reset_all()
    
    # Storage for all client instances and their commands
    client_records = {
        'clients': [],
        'commands': []
    }
    
    class MockPlayerClientBase:
        """Base mock for player clients that records set_value calls"""
        def __init__(self, player_port: int, name: str):
            self.player_port = player_port
            self.name = name
            self.nodes = {}
            self.endpoints = {}
            
            # Record this client creation
            client_records['clients'].append({
                'name': name,
                'port': player_port,
                'endpoints': list(self.endpoints.keys()) if self.endpoints else []
            })
            
            # Create mock device and nodes
            self.device = Mock()
            self.device.root_node = Mock()
        
        def set_value(self, node, value):
            """Record set_value calls"""
            # Get node path
            if isinstance(node, str):
                node_path = node
            else:
                node_path = str(node)
            
            # Record the command
            client_records['commands'].append({
                'client': self.name,
                'port': self.player_port,
                'node': node_path,
                'value': value
            })
            
            # Update mock node value if it exists
            if node_path in self.nodes:
                self.nodes[node_path].parameter.value = value
        
        def get_node(self, path: str):
            """Return mock node"""
            return self.nodes.get(path)
        
        def remove_device(self):
            """Mock cleanup"""
            pass
    
    class MockVideoClient(MockPlayerClientBase):
        """Mock VideoClient matching its signature"""
        def __init__(self, player_port: int, name: str = "videoplayer"):
            super().__init__(player_port, name)
    
    class MockAudioClient(MockPlayerClientBase):
        """Mock AudioClient matching its signature"""
        def __init__(self, player_port: int, name: str = "audioplayer"):
            super().__init__(player_port, name)
    
    class MockDmxClient(MockPlayerClientBase):
        """Mock DmxClient matching its signature"""
        def __init__(self, player_port: int, client_name: str, host: str = "127.0.0.1"):
            super().__init__(player_port, client_name)
            self.host = host
    
    class MockMixerClient(MockPlayerClientBase):
        """Mock MixerClient matching its signature"""
        def __init__(self, player_port: int, channel_number: int, mixer_id: str):
            super().__init__(player_port, f'mixer-{mixer_id}')
            self.channel_number = channel_number
            self.client_name = f'audiomixer-{mixer_id}'
    
    # Mock function to prevent Player subprocess from starting
    def mock_call_subprocess(self, call_args):
        """Mock implementation that prevents subprocess startup"""
        # Set up mock process
        self.p = MagicMock()
        self.p.pid = id(self)
        self.p.poll = MagicMock(return_value=None)
        self.pid = id(self)
        self.status = 'running'
        self.error = None
    
    # Patch all PlayerClient subclasses AND Player.call_subprocess
    with patch('cuemsengine.players.VideoPlayer.VideoClient', MockVideoClient), \
         patch('cuemsengine.players.AudioPlayer.AudioClient', MockAudioClient), \
         patch('cuemsengine.players.DmxPlayer.DmxClient', MockDmxClient), \
         patch('cuemsengine.players.AudioMixer.MixerClient', MockMixerClient), \
         patch('cuemsengine.players.Player.Player.call_subprocess', mock_call_subprocess):
        yield client_records
    
    # Cleanup
    PLAYER_HANDLER.reset_all()

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
