import pytest
from unittest.mock import Mock, patch
from cuemsengine.core.BaseEngine import BaseEngine, MTC_PORT

@pytest.fixture
def mock_config_path():
    from pathlib import Path
    """Mock ConfigManager to use test XML files"""
    test_conf_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
    def mock_conf_path(file):
        return test_conf_path / file
        
    with patch('cuemsengine.tools.ConfigManager.ConfigManager.conf_path', 
            side_effect=mock_conf_path):
        yield test_conf_path


class TestBaseEngine:
    @pytest.fixture
    def mock_config_manager(self):
        with patch('cuemsengine.core.BaseEngine.ConfigManager') as mock_cm:
            mock_cm.return_value.node_conf = {
                'uuid': 'test_node',
                'mtc_port': MTC_PORT
            }
            mock_cm.return_value.tmp_path = '/tmp'
            mock_cm.return_value.library_path = '/library'
            yield mock_cm

    @pytest.fixture
    def mock_mtc_listener(self):
        with patch('cuemsengine.core.BaseEngine.MtcListener') as mock_mtc:
            yield mock_mtc

    def test_base_engine_initialization_with_all_components(self, mock_config_manager, mock_mtc_listener):
        """Test BaseEngine initialization with both ConfigManager and MTC listener"""
        from functools import partial
        from cuemsutils.CTimecode import CTimecode
        engine = BaseEngine(with_cm=True, with_mtc=True)
        
        # Check basic attributes
        assert engine.node_name == 'test_node'
        assert engine.mtc_port == MTC_PORT
        assert engine._timecode is None
        assert engine.go_offset == 0
        assert engine.node_host == 'http://test_node.local'
        assert engine.script is None
        assert engine.stop_requested is False
        assert engine.ongoing_cue is None
        assert engine.next_cue_pointer is None

        # Verify ConfigManager was initialized
        mock_config_manager.assert_called_once()
        
        # Verify MTC listener was initialized
        mock_mtc_listener.assert_called_once()

    def test_base_engine_initialization_without_mtc(self, mock_config_manager):
        """Test BaseEngine initialization without MTC listener"""
        engine = BaseEngine(with_cm=True, with_mtc=False)
        
        # Check basic attributes
        assert engine.node_name == 'test_node'
        assert engine.mtc_port == MTC_PORT
        assert engine._timecode is None
        
        # Verify ConfigManager was initialized
        mock_config_manager.assert_called_once()
        
        # Verify MTC listener was not initialized
        assert not hasattr(engine, 'mtc_listener')

    def test_timecode_property(self):
        """Test timecode property getter and setter"""
        engine = BaseEngine(with_cm=False, with_mtc=False)
        
        # Test initial value
        assert engine.timecode is None
        
        # Test setting timecode
        engine.timecode = "01:00:00:00"
        assert engine.timecode == "01:00:00:00"
        
        # Test timecode change callback
        mock_callback = Mock()
        engine.on_timecode_change = mock_callback
        engine.timecode = "02:00:00:00"
        mock_callback.assert_called_once_with("02:00:00:00")

    def test_stop_all(self, mock_config_path):
        """Test stop_all method"""
        engine = BaseEngine(with_cm=True, with_mtc=True)
        
        # Mock the stop methods
        engine.cm.join = Mock()
        
        engine.stop_all()
        
        # Verify ConfigManager was joined
        engine.cm.join.assert_called_once()
