import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

# Patch the problematic import before importing cuemsengine
sys.modules['cuemsutils.tools.Osc_nodes_hub'] = Mock()

from cuemsengine.players.DmxPlayer import (
    DmxPlayer,
    DmxClient,
    start_dmx_player
)
from pyossia import ossia


class TestDmxPlayer:
    """Test cases for DmxPlayer class."""
    
    @pytest.fixture
    def dmx_player(self):
        """Create DmxPlayer instance for testing."""
        with patch('cuemsengine.players.DmxPlayer.sleep'), \
             patch.object(DmxPlayer, 'call_subprocess'), \
             patch.object(DmxPlayer, 'start'):  # Mock the start method to avoid thread issues
            player = DmxPlayer(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer'
            )
            return player
    
    def test_dmx_player_initialization(self):
        """Test DmxPlayer initialization."""
        with patch('cuemsengine.players.DmxPlayer.sleep'), \
             patch.object(DmxPlayer, 'call_subprocess'):
            
            player = DmxPlayer(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer'
            )
            
            assert player.node_uuid == 'test-node-123'
            assert player.port == 9000
            assert player.client_name == 'test-node-123_dmxplayer'
            assert player.path == '/usr/local/bin/dmxplayer'
            assert player.args is None
    
    def test_dmx_player_initialization_with_args(self):
        """Test DmxPlayer initialization with custom args."""
        with patch('cuemsengine.players.DmxPlayer.sleep'), \
             patch.object(DmxPlayer, 'call_subprocess'):
            
            player = DmxPlayer(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer',
                args='--debug --verbose'
            )
            
            assert player.args == '--debug --verbose'
    
    def test_run_method(self, dmx_player):
        """Test the run method starts dmxplayer subprocess."""
        with patch.object(dmx_player, 'call_subprocess') as mock_call:
            dmx_player.run()
            
            expected_args = [
                '/usr/local/bin/dmxplayer',
                '--port', '9000',
                '--uuid', 'test-node-123'
            ]
            mock_call.assert_called_once_with(expected_args)
    
    def test_run_method_with_args(self):
        """Test the run method with custom args."""
        with patch('cuemsengine.players.DmxPlayer.sleep'), \
             patch.object(DmxPlayer, 'call_subprocess') as mock_call, \
             patch.object(DmxPlayer, 'start'):  # Prevent thread from starting automatically
            
            player = DmxPlayer(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer',
                args='--debug --verbose'
            )
            
            # Call run() explicitly since we mocked start()
            player.run()
            
            expected_args = [
                '/usr/local/bin/dmxplayer',
                '--debug',
                '--verbose',
                '--port', '9000',
                '--uuid', 'test-node-123'
            ]
            mock_call.assert_called_once_with(expected_args)


class TestDmxClient:
    """Test cases for DmxClient class."""
    
    @pytest.fixture
    def dmx_client(self):
        """Create DmxClient instance for testing."""
        # Store the original method before patching
        original_create_bundle = DmxClient._create_bundle_parameters
        
        with patch('cuemsengine.players.DmxPlayer.PlayerClient.__init__'), \
             patch.object(DmxClient, '_create_bundle_parameters'):  # Patch during __init__
            client = DmxClient(
                player_port=9000,
                client_name='test-node-123_dmxplayer'
            )
            # Mock the device and parameters BEFORE calling _create_bundle_parameters
            mock_param = Mock()
            mock_node = Mock()
            mock_node.create_parameter.return_value = mock_param
            
            # Create a mock that returns the mock_node and tracks calls
            def create_mock_node(node_path):
                """Create a mock node for each add_node call"""
                return mock_node
            
            # Create device mock with root_node that has add_node
            client.device = Mock()
            client.device.root_node = Mock()
            add_node_mock = Mock(side_effect=create_mock_node)
            client.device.root_node.add_node = add_node_mock
            client.name = 'test-node-123_dmxplayer'
            
            # Restore and call the real _create_bundle_parameters() method
            client._create_bundle_parameters = original_create_bundle.__get__(client, DmxClient)
            client._create_bundle_parameters()
            
            # Store the mock for test access
            client._add_node_mock = add_node_mock
            
            return client
    
    def test_dmx_client_initialization(self):
        """Test DmxClient initialization."""
        with patch('cuemsengine.players.DmxPlayer.PlayerClient.__init__') as mock_init, \
             patch.object(DmxClient, '_create_bundle_parameters'):  # Skip bundle creation during init
            client = DmxClient(
                player_port=9000,
                client_name='test-node-123_dmxplayer'
            )
            
            # Set up device mock after initialization
            client.device = Mock()
            client.device.root_node = Mock()
            
            # Verify PlayerClient init was called
            mock_init.assert_called_once()
            assert client.player_port == 9000
            assert client.host == "127.0.0.1"
    
    def test_dmx_client_custom_host(self):
        """Test DmxClient initialization with custom host."""
        with patch('cuemsengine.players.DmxPlayer.PlayerClient.__init__'), \
             patch.object(DmxClient, '_create_bundle_parameters'):  # Skip bundle creation during init
            client = DmxClient(
                player_port=9000,
                client_name='test-node-123_dmxplayer',
                host='192.168.1.100'
            )
            
            # Set up device mock after initialization
            client.device = Mock()
            client.device.root_node = Mock()
            
            assert client.host == '192.168.1.100'
    
    def test_create_bundle_parameters(self, dmx_client):
        """Test bundle parameters are created correctly."""
        # Verify add_node was called for each parameter
        expected_nodes = ['/frame', '/mtc_time', '/start_offset', '/fade_time']
        
        # Get all calls made to add_node (stored in fixture)
        add_node_mock = dmx_client._add_node_mock
        assert add_node_mock.called, "add_node should have been called"
        call_args_list = add_node_mock.call_args_list
        
        # Extract the first argument (node path) from each call
        actual_calls = [call[0][0] for call in call_args_list if call[0]]
        
        # Verify each expected node was created
        assert len(actual_calls) == len(expected_nodes), \
            f"Expected {len(expected_nodes)} nodes, got {len(actual_calls)}: {actual_calls}"
        
        for node in expected_nodes:
            assert node in actual_calls, f"Expected node {node} not found in calls: {actual_calls}"
    
    def test_send_dmx_scene_with_integer_mtc(self, dmx_client):
        """Test sending DMX scene with integer MTC time."""
        # Setup
        universe_frames = {
            1: {0: 255, 1: 128, 2: 64}
        }
        
        # Mock bundle
        mock_bundle = Mock(spec=ossia.Bundle)
        
        with patch('cuemsengine.players.DmxPlayer.ossia.Bundle', return_value=mock_bundle):
            dmx_client.send_dmx_scene(
                universe_frames=universe_frames,
                mtc_time=1000,  # milliseconds
                fade_time=2.0
            )
            
            # Verify bundle.append was called for frame, start_offset, and fade_time
            assert mock_bundle.append.call_count == 3
            
            # Verify device.push_bundle was called
            dmx_client.device.push_bundle.assert_called_once_with(mock_bundle)
    
    def test_send_dmx_scene_with_string_mtc(self, dmx_client):
        """Test sending DMX scene with string MTC time."""
        universe_frames = {
            1: {0: 255, 1: 128}
        }
        
        mock_bundle = Mock(spec=ossia.Bundle)
        
        with patch('cuemsengine.players.DmxPlayer.ossia.Bundle', return_value=mock_bundle):
            dmx_client.send_dmx_scene(
                universe_frames=universe_frames,
                mtc_time="now",
                fade_time=1.5
            )
            
            # Verify bundle.append was called for frame, mtc_time, and fade_time
            assert mock_bundle.append.call_count == 3
            
            # Verify device.push_bundle was called
            dmx_client.device.push_bundle.assert_called_once_with(mock_bundle)
    
    def test_send_dmx_scene_multiple_universes(self, dmx_client):
        """Test sending DMX scene with multiple universes."""
        universe_frames = {
            1: {0: 255, 1: 128, 2: 64},
            2: {0: 100, 1: 200},
            3: {0: 50}
        }
        
        mock_bundle = Mock(spec=ossia.Bundle)
        
        with patch('cuemsengine.players.DmxPlayer.ossia.Bundle', return_value=mock_bundle):
            dmx_client.send_dmx_scene(
                universe_frames=universe_frames,
                mtc_time=5000,
                fade_time=3.0
            )
            
            # Should append 3 frames + 1 start_offset + 1 fade_time = 5 calls
            assert mock_bundle.append.call_count == 5
            
            dmx_client.device.push_bundle.assert_called_once()
    
    def test_send_dmx_scene_empty_universe(self, dmx_client):
        """Test sending DMX scene with empty universe (should be skipped)."""
        universe_frames = {
            1: {0: 255},
            2: {}  # Empty universe should be skipped
        }
        
        mock_bundle = Mock(spec=ossia.Bundle)
        
        with patch('cuemsengine.players.DmxPlayer.ossia.Bundle', return_value=mock_bundle):
            dmx_client.send_dmx_scene(
                universe_frames=universe_frames,
                mtc_time=1000,
                fade_time=1.0
            )
            
            # Should append 1 frame (universe 2 skipped) + 1 start_offset + 1 fade_time = 3 calls
            assert mock_bundle.append.call_count == 3
    
    def test_send_dmx_scene_error_handling(self, dmx_client):
        """Test error handling in send_dmx_scene."""
        universe_frames = {1: {0: 255}}
        
        # Mock bundle to raise exception
        with patch('cuemsengine.players.DmxPlayer.ossia.Bundle', side_effect=Exception("Test error")):
            with pytest.raises(Exception, match="Test error"):
                dmx_client.send_dmx_scene(
                    universe_frames=universe_frames,
                    mtc_time=1000,
                    fade_time=1.0
                )
    
    def test_send_dmx_scene_sorted_channels(self, dmx_client):
        """Test that channels are sorted when building frame data."""
        universe_frames = {
            1: {5: 100, 1: 200, 3: 150}  # Unsorted channels
        }
        
        mock_bundle = Mock(spec=ossia.Bundle)
        
        with patch('cuemsengine.players.DmxPlayer.ossia.Bundle', return_value=mock_bundle):
            dmx_client.send_dmx_scene(
                universe_frames=universe_frames,
                mtc_time=1000,
                fade_time=1.0
            )
            
            # Verify bundle.append was called
            # The first call should be for the frame with sorted channels
            frame_call = mock_bundle.append.call_args_list[0]
            frame_data = frame_call[0][1]
            
            # Frame data should be: [universe_id, ch1, val1, ch3, val3, ch5, val5]
            # Channels should be in order: 1, 3, 5
            assert frame_data[0] == 1  # universe_id
            assert frame_data[1] == 1  # first channel
            assert frame_data[2] == 200  # first value
            assert frame_data[3] == 3  # second channel
            assert frame_data[4] == 150  # second value
            assert frame_data[5] == 5  # third channel
            assert frame_data[6] == 100  # third value


class TestStartDmxPlayer:
    """Test cases for start_dmx_player function."""
    
    def test_start_dmx_player(self):
        """Test starting DMX player and client."""
        with patch('cuemsengine.players.DmxPlayer.DmxPlayer') as mock_player_class, \
             patch('cuemsengine.players.DmxPlayer.DmxClient') as mock_client_class, \
             patch('cuemsengine.players.DmxPlayer.sleep'):
            
            # Mock player instance
            mock_player = Mock()
            mock_player.pid = 12345
            mock_player_class.return_value = mock_player
            
            # Mock client instance
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            
            player, client = start_dmx_player(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer'
            )
            
            # Verify player was created with correct parameters
            mock_player_class.assert_called_once_with(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer',
                args=None
            )
            
            # Verify client was created with correct parameters
            mock_client_class.assert_called_once_with(
                player_port=9000,
                client_name='test-node-123_dmxplayer'
            )
            
            assert player == mock_player
            assert client == mock_client
    
    def test_start_dmx_player_with_args(self):
        """Test starting DMX player with custom args."""
        with patch('cuemsengine.players.DmxPlayer.DmxPlayer') as mock_player_class, \
             patch('cuemsengine.players.DmxPlayer.DmxClient') as mock_client_class, \
             patch('cuemsengine.players.DmxPlayer.sleep'):
            
            mock_player = Mock()
            mock_player.pid = 12345
            mock_player_class.return_value = mock_player
            mock_client_class.return_value = Mock()
            
            start_dmx_player(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer',
                args='--debug'
            )
            
            mock_player_class.assert_called_once_with(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer',
                args='--debug'
            )
    
    def test_start_dmx_player_waits_for_pid(self):
        """Test that start_dmx_player waits for player process to start."""
        with patch('cuemsengine.players.DmxPlayer.DmxPlayer') as mock_player_class, \
             patch('cuemsengine.players.DmxPlayer.DmxClient') as mock_client_class, \
             patch('cuemsengine.players.DmxPlayer.sleep') as mock_sleep:
            
            # Mock player with pid initially None, then set
            mock_player = Mock()
            mock_player.pid = None
            mock_player_class.return_value = mock_player
            
            mock_client_class.return_value = Mock()
            
            # Set pid after first check
            # sleep() passes the sleep duration as an argument, so accept it
            def set_pid_after_check(*args, **kwargs):
                if mock_sleep.call_count == 1:
                    mock_player.pid = 12345
            
            mock_sleep.side_effect = set_pid_after_check
            
            start_dmx_player(
                port=9000,
                node_uuid='test-node-123',
                path='/usr/local/bin/dmxplayer'
            )
            
            # Verify sleep was called (waiting for pid)
            assert mock_sleep.call_count >= 1

