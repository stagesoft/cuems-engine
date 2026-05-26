# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from unittest.mock import MagicMock, Mock, patch

import jack
import pytest

from cuemsengine.players.JackConnectionManager import JackConnectionManager


class TestJackConnectionManager:
    """Test cases for JackConnectionManager class."""

    @pytest.fixture
    def mock_jack_client(self):
        """Mock JACK client for testing."""
        mock_client = Mock()

        # Create mock port objects with name attribute
        mock_port1 = Mock()
        mock_port1.name = "system:playback_1"
        mock_port2 = Mock()
        mock_port2.name = "system:playback_2"
        mock_port3 = Mock()
        mock_port3.name = "system:capture_1"
        mock_port4 = Mock()
        mock_port4.name = "test_client:output_1"

        mock_client.get_ports.return_value = [
            mock_port1,
            mock_port2,
            mock_port3,
            mock_port4,
        ]

        # Create mock connection objects with name attribute
        mock_conn1 = Mock()
        mock_conn1.name = "system:playback_1"
        mock_conn2 = Mock()
        mock_conn2.name = "system:playback_2"

        mock_client.get_all_connections.return_value = [mock_conn1, mock_conn2]
        return mock_client

    @pytest.fixture
    def jack_manager(self, mock_jack_client):
        """Create JackConnectionManager instance for testing."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.return_value = mock_jack_client
            manager = JackConnectionManager("test_client")
            return manager

    def test_jack_connection_manager_initialization(self, mock_jack_client):
        """Test JackConnectionManager initialization."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.return_value = mock_jack_client

            manager = JackConnectionManager("test_client")

            assert manager.client_name == "test_client"
            assert manager._client == mock_jack_client
            mock_client_class.assert_called_once_with(
                "test_client", no_start_server=True
            )

    def test_jack_connection_manager_initialization_with_jack_error(self):
        """Test JackConnectionManager initialization with JACK error."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.side_effect = jack.JackError("JACK server not running")

            manager = JackConnectionManager("test_client")

            assert manager.client_name == "test_client"
            assert manager._client is None

    def test_client_property_reinitializes_on_none(self, mock_jack_client):
        """Test that client property reinitializes when _client is None."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.return_value = mock_jack_client

            manager = JackConnectionManager("test_client")
            manager._client = None  # Simulate client becoming None

            client = manager.client

            assert client == mock_jack_client
            assert (
                mock_client_class.call_count == 2
            )  # Called twice: init and property access

    def test_get_ports_success(self, jack_manager, mock_jack_client):
        """Test getting JACK ports successfully."""
        ports = jack_manager.get_ports()

        expected_ports = [
            "system:playback_1",
            "system:playback_2",
            "system:capture_1",
            "test_client:output_1",
        ]
        assert ports == expected_ports
        mock_jack_client.get_ports.assert_called_once_with(
            name_pattern="", is_audio=True, is_output=None, is_input=None
        )

    def test_get_ports_with_pattern(self, jack_manager, mock_jack_client):
        """Test getting JACK ports with name pattern filter."""
        jack_manager.get_ports(pattern="system.*")

        mock_jack_client.get_ports.assert_called_once_with(
            name_pattern="system.*", is_audio=True, is_output=None, is_input=None
        )

    def test_get_ports_with_filters(self, jack_manager, mock_jack_client):
        """Test getting JACK ports with audio and direction filters."""
        jack_manager.get_ports(is_audio=True, is_output=True, is_input=False)

        mock_jack_client.get_ports.assert_called_once_with(
            name_pattern="", is_audio=True, is_output=True, is_input=False
        )

    def test_get_ports_jack_error(self, mock_jack_client):
        """Test getting JACK ports with JACK error."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_jack_client.get_ports.side_effect = jack.JackError("Connection lost")
            mock_client_class.return_value = mock_jack_client

            manager = JackConnectionManager("test_client")
            ports = manager.get_ports()

            assert ports == []

    def test_get_ports_unexpected_error(self, mock_jack_client):
        """Test getting JACK ports with unexpected error."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_jack_client.get_ports.side_effect = Exception("Unexpected error")
            mock_client_class.return_value = mock_jack_client

            manager = JackConnectionManager("test_client")
            ports = manager.get_ports()

            assert ports == []

    def test_get_ports_no_client(self):
        """Test getting JACK ports when client is not initialized."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.side_effect = jack.JackError("JACK server not running")

            manager = JackConnectionManager("test_client")
            ports = manager.get_ports()

            assert ports == []

    def test_connect_by_name_success(self, jack_manager, mock_jack_client):
        """Test connecting JACK ports successfully."""
        mock_jack_client.get_all_connections.return_value = []  # Not already connected

        result = jack_manager.connect_by_name("source:output", "dest:input")

        assert result is True
        mock_jack_client.connect.assert_called_once_with("source:output", "dest:input")

    def test_connect_by_name_already_connected(self, jack_manager, mock_jack_client):
        """Test connecting JACK ports that are already connected."""
        # Mock is_connected to return True
        with patch.object(jack_manager, "is_connected", return_value=True):
            result = jack_manager.connect_by_name("source:output", "dest:input")

            assert result is True
            mock_jack_client.connect.assert_not_called()

    def test_connect_by_name_jack_error(self, jack_manager, mock_jack_client):
        """Test connecting JACK ports with JACK error."""
        mock_jack_client.get_all_connections.return_value = []  # Not already connected
        mock_jack_client.connect.side_effect = jack.JackError("Port not found")

        result = jack_manager.connect_by_name("source:output", "dest:input")

        assert result is False

    def test_connect_by_name_unexpected_error(self, jack_manager, mock_jack_client):
        """Test connecting JACK ports with unexpected error."""
        mock_jack_client.get_all_connections.return_value = []  # Not already connected
        mock_jack_client.connect.side_effect = Exception("Unexpected error")

        result = jack_manager.connect_by_name("source:output", "dest:input")

        assert result is False

    def test_connect_by_name_no_client(self):
        """Test connecting JACK ports when client is not initialized."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.side_effect = jack.JackError("JACK server not running")

            manager = JackConnectionManager("test_client")
            result = manager.connect_by_name("source:output", "dest:input")

            assert result is False

    def test_disconnect_by_name_success(self, jack_manager, mock_jack_client):
        """Test disconnecting JACK ports successfully."""
        result = jack_manager.disconnect_by_name("source:output", "dest:input")

        assert result is True
        mock_jack_client.disconnect.assert_called_once_with(
            "source:output", "dest:input"
        )

    def test_disconnect_by_name_jack_error(self, jack_manager, mock_jack_client):
        """Test disconnecting JACK ports with JACK error."""
        mock_jack_client.disconnect.side_effect = jack.JackError("Port not found")

        result = jack_manager.disconnect_by_name("source:output", "dest:input")

        assert result is False

    def test_disconnect_by_name_unexpected_error(self, jack_manager, mock_jack_client):
        """Test disconnecting JACK ports with unexpected error."""
        mock_jack_client.disconnect.side_effect = Exception("Unexpected error")

        result = jack_manager.disconnect_by_name("source:output", "dest:input")

        assert result is False

    def test_disconnect_by_name_no_client(self):
        """Test disconnecting JACK ports when client is not initialized."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.side_effect = jack.JackError("JACK server not running")

            manager = JackConnectionManager("test_client")
            result = manager.disconnect_by_name("source:output", "dest:input")

            assert result is False

    def test_get_connections_success(self, jack_manager, mock_jack_client):
        """Test getting connections for a port successfully."""
        connections = jack_manager.get_connections("test_port")

        expected_connections = ["system:playback_1", "system:playback_2"]
        assert connections == expected_connections

        mock_jack_client.get_ports.assert_called_once_with(name_pattern="^test_port$")
        mock_jack_client.get_all_connections.assert_called_once()

    def test_get_connections_port_not_found(self, jack_manager, mock_jack_client):
        """Test getting connections for a port that doesn't exist."""
        mock_jack_client.get_ports.return_value = []  # No ports found

        connections = jack_manager.get_connections("nonexistent_port")

        assert connections == []

    def test_get_connections_jack_error(self, jack_manager, mock_jack_client):
        """Test getting connections with JACK error."""
        mock_jack_client.get_ports.side_effect = jack.JackError("Connection lost")

        connections = jack_manager.get_connections("test_port")

        assert connections == []

    def test_get_connections_unexpected_error(self, jack_manager, mock_jack_client):
        """Test getting connections with unexpected error."""
        mock_jack_client.get_ports.side_effect = Exception("Unexpected error")

        connections = jack_manager.get_connections("test_port")

        assert connections == []

    def test_get_connections_no_client(self):
        """Test getting connections when client is not initialized."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.side_effect = jack.JackError("JACK server not running")

            manager = JackConnectionManager("test_client")
            connections = manager.get_connections("test_port")

            assert connections == []

    def test_is_connected_true(self, jack_manager):
        """Test is_connected returns True when ports are connected."""
        with patch.object(
            jack_manager, "get_connections", return_value=["dest:input", "other:port"]
        ):
            result = jack_manager.is_connected("source:output", "dest:input")

            assert result is True

    def test_is_connected_false(self, jack_manager):
        """Test is_connected returns False when ports are not connected."""
        with patch.object(
            jack_manager, "get_connections", return_value=["other:port1", "other:port2"]
        ):
            result = jack_manager.is_connected("source:output", "dest:input")

            assert result is False

    def test_is_connected_no_connections(self, jack_manager):
        """Test is_connected returns False when no connections exist."""
        with patch.object(jack_manager, "get_connections", return_value=[]):
            result = jack_manager.is_connected("source:output", "dest:input")

            assert result is False

    def test_del_cleanup(self, mock_jack_client):
        """Test cleanup on deletion."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.return_value = mock_jack_client

            manager = JackConnectionManager("test_client")
            del manager

            mock_jack_client.close.assert_called_once()

    def test_del_cleanup_with_error(self, mock_jack_client):
        """Test cleanup on deletion with error."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_jack_client.close.side_effect = Exception("Close error")
            mock_client_class.return_value = mock_jack_client

            manager = JackConnectionManager("test_client")
            del manager  # Should not raise exception

            mock_jack_client.close.assert_called_once()

    def test_del_cleanup_no_client(self):
        """Test cleanup on deletion when client is None."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.side_effect = jack.JackError("JACK server not running")

            manager = JackConnectionManager("test_client")
            del manager  # Should not raise exception

    def test_integration_workflow(self, mock_jack_client):
        """Test a complete workflow: get ports, connect, check connection, disconnect."""
        with patch(
            "cuemsengine.players.JackConnectionManager.jack.Client"
        ) as mock_client_class:
            mock_client_class.return_value = mock_jack_client

            manager = JackConnectionManager("test_client")

            # Get available ports
            ports = manager.get_ports()
            assert len(ports) == 4

            # Connect two ports
            result = manager.connect_by_name(
                "test_client:output_1", "system:playback_1"
            )
            assert result is True

            # Check if connected
            is_connected = manager.is_connected(
                "test_client:output_1", "system:playback_1"
            )
            assert is_connected is True

            # Disconnect
            result = manager.disconnect_by_name(
                "test_client:output_1", "system:playback_1"
            )
            assert result is True
