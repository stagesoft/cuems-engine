import pytest
from unittest.mock import patch

from cuemsengine.core.BaseEngine import BaseEngine

@pytest.fixture
def daemon(with_signals: bool = True):
    return BaseEngine(with_signals=with_signals)

@pytest.fixture
def mock_signal():
    with patch('signal.signal') as mock_signal_obj:
        yield mock_signal_obj

@pytest.fixture
def mock_config_path():
    from pathlib import Path
    """Mock ConfigManager to use test XML files"""
    test_conf_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
    def mock_conf_path(file):
        return test_conf_path / file
        
    with patch('cuemsutils.tools.ConfigManager.ConfigManager.conf_path', 
            side_effect=mock_conf_path):
        yield test_conf_path

def test_engine_can_start_and_stop(mock_config_path):
    from time import sleep
    from os import path
    from cuemsengine.core.BaseEngine import SHOW_LOCK_PATH
    
    engine = BaseEngine(with_signals=False)
    engine.set_show_lock_file()
    sleep(0.05)

    assert engine.show_locked == True
    assert path.isfile(SHOW_LOCK_PATH)

    engine.stop()
    assert engine.show_locked == False
    assert engine.running == False

def test_engine_status(daemon, mock_config_path):
    assert daemon.status.load is None
    assert daemon.status.loadcue is None
    assert daemon.status.go is None
    assert daemon.status.gocue is None
    assert daemon.status.pause is None
    assert daemon.status.stop is None
    assert daemon.status.resetall is None
    assert daemon.status.preload is None
    assert daemon.status.unload is None
    assert daemon.status.hwdiscovery is None
    assert daemon.status.deploy is None
    assert daemon.status.test is None
    assert daemon.status.timecode is None
    assert daemon.status.currentcue is None
    assert daemon.status.nextcue is None
    assert daemon.status.running is None

def test_set_status(daemon):
    daemon.set_status('load', 'test')
    assert daemon.status.load == 'test'

def test_get_status(daemon):
    daemon.set_status('load', 'test')
    assert daemon.get_status('load') == 'test'

def test_recieved_test(daemon):
    assert daemon.status.test_recieved == 0
    daemon.set_status('test', 'test')
    assert daemon.status.test == 'test'
    assert daemon.status.test_recieved == 1
    daemon.set_status('test', 'test2')
    assert daemon.status.test == 'test2'
    assert daemon.status.test_recieved == 2

def test_get_status_none(daemon, caplog):
    assert daemon.get_status('none') == "NotFound"
    assert "Property none not found in EngineStatus" in caplog.text

    try:
        daemon.get_status('none', strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"

def test_set_status_none(daemon, caplog):
    daemon.set_status('none', 'test')
    assert "Property none not found in EngineStatus" in caplog.text
    try:
        daemon.set_status('none', 'test', strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"
