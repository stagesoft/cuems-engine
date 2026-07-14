# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from unittest.mock import MagicMock, Mock, call, patch

import pytest

from cuemsengine.players.AudioMixer import (
    AudioMixer,
    MixerClient,
    build_mixer_osc_endpoints,
    start_audio_mixer,
)
from cuemsengine.players.JackConnectionManager import JackConnectionManager


class TestAudioMixer:
    """Test cases for AudioMixer class."""

    @pytest.fixture
    def mock_audio_outputs(self):
        """Audio outputs: list of JACK playback port names (current contract)."""
        return ['system:playback_1', 'system:playback_2']
    
    @pytest.fixture
    def mock_conn_manager(self):
        """Mock JackConnectionManager."""
        with patch(
            "cuemsengine.players.AudioMixer.JackConnectionManager"
        ) as mock_conn:
            mock_instance = Mock()
            mock_instance.get_ports.return_value = [
                "system:playback_1",
                "system:playback_2",
            ]
            mock_instance.connect_by_name.return_value = True
            mock_conn.return_value = mock_instance
            yield mock_instance

    @pytest.fixture
    def audio_mixer(self, mock_audio_outputs, mock_conn_manager):
        """Create AudioMixer instance for testing."""
        with (
            patch("cuemsengine.players.AudioMixer.sleep"),
            patch.object(AudioMixer, "call_subprocess"),
            patch.object(AudioMixer, "start"),
        ):  # Mock the start method to avoid thread issues
            mixer = AudioMixer(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path="/usr/local/bin/jack-volume"
            )
            return mixer

    def test_audio_mixer_initialization(
        self, mock_audio_outputs, mock_conn_manager
    ):
        """Test AudioMixer initialization."""
        with (
            patch("cuemsengine.players.AudioMixer.sleep"),
            patch.object(AudioMixer, "call_subprocess")
        ):

            mixer = AudioMixer(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123"
            )

            assert mixer.port == 8000
            assert mixer.channel_number == 2
            assert mixer.client_name == "test-node-123_mixer"
            assert mixer.path == "/usr/local/bin/jack-volume"
            assert mixer.args == [
                "-c",
                "test-node-123_mixer",
                "-p",
                "8000",
                "-n",
                "2"
            ]

    def test_audio_mixer_initialization_with_custom_path(
        self, mock_audio_outputs, mock_conn_manager
    ):
        """Test AudioMixer initialization with custom jack-volume path."""
        with (
            patch("cuemsengine.players.AudioMixer.sleep"),
            patch.object(AudioMixer, "call_subprocess")
        ):

            mixer = AudioMixer(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path="/custom/path/jack-volume"
            )

            assert mixer.path == "/custom/path/jack-volume"

    def test_run_method(self, audio_mixer):
        """Test the run method starts jack-volume subprocess."""
        with patch.object(audio_mixer, "call_subprocess") as mock_call:
            audio_mixer.run()

            expected_args = [
                "/usr/local/bin/jack-volume",
                "-c",
                "test-node-123_mixer",
                "-p",
                "8000",
                "-n",
                "2",
            ]
            mock_call.assert_called_once_with(expected_args)

    def test_connect_to_jack(self, audio_mixer, mock_conn_manager):
        """Test JACK port connections."""
        audio_mixer.connect_to_jack()

        # Should connect 2 channels to system playback ports
        expected_calls = [
            (("test-node-123_mixer:output_1", "system:playback_1"),),
            (("test-node-123_mixer:output_2", "system:playback_2"),),
        ]
        mock_conn_manager.connect_by_name.assert_has_calls(expected_calls)
    
    # NOTE: connect_player_to_mixer tests moved to TestConnectPlayerToMixer
    # below (built with AudioMixer.__new__, matching the actual current
    # implementation — no mixer_channel validation exists in the code).


def _build_bare_mixer(audio_outputs, conn_man, client_name='test_mixer'):
    """Minimal AudioMixer via __new__ — bypasses AudioMixer.__init__ (no
    subprocess, no real JACK). Thread.__init__ IS called so @logged's
    repr(self) doesn't trip Thread's _initialized assertion."""
    import threading
    m = AudioMixer.__new__(AudioMixer)
    threading.Thread.__init__(m)
    m.conn_man = conn_man
    m.audio_outputs = audio_outputs
    m.channel_number = len(audio_outputs)
    m.client_name = client_name
    return m


def _fake_conn_man(ports, edges=None, connect_result=True):
    """Fake JackConnectionManager over a mutable `ports` set.

    ports: set of existing JACK port names (mutable — tests may grow it from
    a patched sleep side effect to simulate late registration).
    edges: dict[source] -> list of currently-connected destinations.
    connect_result: return value (or side_effect list) for connect_by_name.
    """
    edges = edges or {}
    cm = Mock()
    cm.port_exists.side_effect = lambda p: p in ports
    cm.get_connections.side_effect = lambda p: list(edges.get(p, []))
    cm.is_connected.side_effect = lambda src, dst: dst in edges.get(src, [])
    if isinstance(connect_result, list):
        cm.connect_by_name.side_effect = connect_result
    else:
        cm.connect_by_name.return_value = connect_result
    cm.disconnect_by_name.return_value = True
    return cm


class TestConnectPlayerToMixer:
    """Dead-twin coverage (no production callers — hygiene only): the
    timeout path must early-return False, mirroring connect_player_to_outputs."""

    PLAYER = 'test_player'
    CH0 = 'test_player:output 0'
    CH1 = 'test_player:output 1'

    def test_invalid_channel_makes_no_connections(self):
        ports = {self.CH0, self.CH1, 'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(['system:playback_1', 'system:playback_2'], cm)
        with patch('time.sleep'):
            m.connect_player_to_mixer(self.PLAYER, 'output', 5)  # >= channel_number
        cm.connect_by_name.assert_not_called()

    def test_channel_0_maps_to_inputs_1_2(self):
        ports = {self.CH0, self.CH1, 'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(['system:playback_1', 'system:playback_2'], cm)
        with patch('time.sleep'):
            m.connect_player_to_mixer(self.PLAYER, 'output', 0)
        cm.connect_by_name.assert_any_call(self.CH0, 'test_mixer:input_1')
        cm.connect_by_name.assert_any_call(self.CH1, 'test_mixer:input_2')

    def test_channel_1_maps_to_inputs_3_4(self):
        ports = {self.CH0, self.CH1, 'test_mixer:input_3', 'test_mixer:input_4'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(['system:playback_1', 'system:playback_2'], cm)
        with patch('time.sleep'):
            m.connect_player_to_mixer(self.PLAYER, 'output', 1)
        cm.connect_by_name.assert_any_call(self.CH0, 'test_mixer:input_3')
        cm.connect_by_name.assert_any_call(self.CH1, 'test_mixer:input_4')

    def test_disconnects_existing_connections_first(self):
        ports = {self.CH0, self.CH1, 'test_mixer:input_1', 'test_mixer:input_2'}
        edges = {
            self.CH0: ['system:playback_1', 'other:input'],
            self.CH1: ['system:playback_2'],
        }
        cm = _fake_conn_man(ports, edges)
        m = _build_bare_mixer(['system:playback_1', 'system:playback_2'], cm)
        with patch('time.sleep'):
            m.connect_player_to_mixer(self.PLAYER, 'output', 0)
        assert cm.disconnect_by_name.call_count == 3  # 2 from ch0, 1 from ch1

    def test_timeout_returns_false_without_connecting(self):
        # Player ports never register → early return False, nothing wired.
        ports = {'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(['system:playback_1', 'system:playback_2'], cm)
        with patch('time.sleep'):
            result = m.connect_player_to_mixer(self.PLAYER, 'output', 0)
        assert result is False
        cm.connect_by_name.assert_not_called()


class TestConnectPlayerToOutputs:
    """Direct coverage for the 2026-07 silent-but-green fix: the port-wait
    loop must actually wait, and the bool return contract must hold."""

    PLAYER = 'Audio_Player-X'
    CH0 = 'Audio_Player-X:outport 0'
    CH1 = 'Audio_Player-X:outport 1'
    OUTS = ['system:playback_1', 'system:playback_2']

    def test_port_never_registers_returns_false_no_connect(self):
        ports = {'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch('time.sleep') as mock_sleep:
            result = m.connect_player_to_outputs(self.PLAYER, 'outport', self.OUTS)
        assert result is False
        cm.connect_by_name.assert_not_called()
        # The wait loop must actually have waited (the old defeated guard
        # broke on attempt 0 without a single sleep).
        assert mock_sleep.call_count >= 29

    def test_port_registers_late_waits_then_connects(self):
        ports = {'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)

        def register_ports(_delay):
            ports.update({self.CH0, self.CH1})

        with patch('time.sleep', side_effect=register_ports):
            result = m.connect_player_to_outputs(self.PLAYER, 'outport', self.OUTS)
        assert result is True
        cm.connect_by_name.assert_any_call(self.CH0, 'test_mixer:input_1')
        cm.connect_by_name.assert_any_call(self.CH1, 'test_mixer:input_2')

    def test_stereo_routing(self):
        ports = {self.CH0, self.CH1, 'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch('time.sleep'):
            result = m.connect_player_to_outputs(self.PLAYER, 'outport', self.OUTS)
        assert result is True
        cm.connect_by_name.assert_any_call(self.CH0, 'test_mixer:input_1')
        cm.connect_by_name.assert_any_call(self.CH1, 'test_mixer:input_2')

    def test_mono_fans_outport_0_to_both_inputs(self):
        # No outport 1 → after the grace window the player is mono and
        # outport 0 feeds both mixer inputs (centred mono).
        ports = {self.CH0, 'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch('time.sleep'):
            result = m.connect_player_to_outputs(self.PLAYER, 'outport', self.OUTS)
        assert result is True
        cm.connect_by_name.assert_any_call(self.CH0, 'test_mixer:input_1')
        cm.connect_by_name.assert_any_call(self.CH0, 'test_mixer:input_2')
        for c in cm.connect_by_name.call_args_list:
            assert c.args[0] != self.CH1

    def test_one_connect_failure_returns_false(self):
        ports = {self.CH0, self.CH1, 'test_mixer:input_1', 'test_mixer:input_2'}
        cm = _fake_conn_man(ports, connect_result=[True, False])
        m = _build_bare_mixer(self.OUTS, cm)
        with patch('time.sleep'):
            result = m.connect_player_to_outputs(self.PLAYER, 'outport', self.OUTS)
        assert result is False
        assert cm.connect_by_name.call_count == 2  # both attempted

    def test_no_mixer_inputs_returns_false(self):
        ports = {self.CH0, self.CH1}  # mixer inputs missing
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch('time.sleep'):
            result = m.connect_player_to_outputs(self.PLAYER, 'outport', self.OUTS)
        assert result is False
        cm.connect_by_name.assert_not_called()


class TestPlayerConnectionsCorrect:
    """Pin the routing equivalence between player_connections_correct and
    connect_player_to_outputs. If connect_player_to_outputs is refactored
    and these diverge, run_audioCue will silently choose the wrong branch
    on every GO."""

    @staticmethod
    def _build_mixer(audio_outputs, conn_man):
        """Create a minimal AudioMixer with only the attributes that
        player_connections_correct touches. Bypasses __init__ to avoid
        the broken legacy test fixtures and any subprocess wiring."""
        m = AudioMixer.__new__(AudioMixer)
        m.conn_man = conn_man
        m.audio_outputs = audio_outputs
        m.client_name = "test_mixer"
        return m

    @staticmethod
    def _make_conn_man(existing_ports, edges):
        """edges: dict[source_port] -> list[destination_port]."""
        cm = Mock()
        cm.port_exists.side_effect = lambda p: p in existing_ports
        cm.is_connected.side_effect = lambda src, dst: dst in edges.get(
            src, []
        )
        return cm

    def test_stereo_all_edges_correct_returns_true(self):
        cm = self._make_conn_man(
            existing_ports={
                "Audio_Player-X:outport 0",
                "Audio_Player-X:outport 1",
                "test_mixer:input_1",
                "test_mixer:input_2",
            },
            edges={
                "Audio_Player-X:outport 0": ["test_mixer:input_1"],
                "Audio_Player-X:outport 1": ["test_mixer:input_2"],
            },
        )
        m = self._build_mixer(["system:playback_1", "system:playback_2"], cm)
        assert (
            m.player_connections_correct(
                "Audio_Player-X",
                "outport",
                ["system:playback_1", "system:playback_2"],
            )
            is True
        )

    def test_stereo_one_edge_missing_returns_false(self):
        cm = self._make_conn_man(
            existing_ports={
                "Audio_Player-X:outport 0",
                "Audio_Player-X:outport 1",
                "test_mixer:input_1",
                "test_mixer:input_2",
            },
            edges={
                "Audio_Player-X:outport 0": ["test_mixer:input_1"],
                # outport 1 not connected
            },
        )
        m = self._build_mixer(["system:playback_1", "system:playback_2"], cm)
        assert (
            m.player_connections_correct(
                "Audio_Player-X",
                "outport",
                ["system:playback_1", "system:playback_2"],
            )
            is False
        )

    def test_stereo_wrong_destination_returns_false(self):
        cm = self._make_conn_man(
            existing_ports={
                "Audio_Player-X:outport 0",
                "Audio_Player-X:outport 1",
                "test_mixer:input_1",
                "test_mixer:input_2",
            },
            edges={
                "Audio_Player-X:outport 0": ["test_mixer:input_1"],
                "Audio_Player-X:outport 1": ["test_mixer:input_3"],  # wrong
            },
        )
        m = self._build_mixer(["system:playback_1", "system:playback_2"], cm)
        assert (
            m.player_connections_correct(
                "Audio_Player-X",
                "outport",
                ["system:playback_1", "system:playback_2"],
            )
            is False
        )

    def test_mono_uses_outport_0_for_both_pair_members(self):
        # Mono player: outport 1 absent. connect_player_to_outputs wires
        # outport 0 to both input_1 and input_2 (centred mono). The check
        # must agree.
        cm = self._make_conn_man(
            existing_ports={
                "Audio_Player-X:outport 0",
                # NOTE: no 'outport 1' → is_stereo=False
                "test_mixer:input_1",
                "test_mixer:input_2",
            },
            edges={
                "Audio_Player-X:outport 0": [
                    "test_mixer:input_1",
                    "test_mixer:input_2",
                ],
            },
        )
        m = self._build_mixer(["system:playback_1", "system:playback_2"], cm)
        assert (
            m.player_connections_correct(
                "Audio_Player-X",
                "outport",
                ["system:playback_1", "system:playback_2"],
            )
            is True
        )

    def test_mono_does_not_check_outport_1(self):
        # Regression guard: a naive impl that always probes outport 1 for
        # odd-indexed targets would return False here even though the graph
        # is wired exactly as connect_player_to_outputs left it.
        cm = self._make_conn_man(
            existing_ports={
                "Audio_Player-X:outport 0",
                "test_mixer:input_1",
                "test_mixer:input_2",
            },
            edges={
                "Audio_Player-X:outport 0": [
                    "test_mixer:input_1",
                    "test_mixer:input_2",
                ],
            },
        )
        m = self._build_mixer(["system:playback_1", "system:playback_2"], cm)
        m.player_connections_correct(
            "Audio_Player-X",
            "outport",
            ["system:playback_1", "system:playback_2"],
        )
        # is_connected must never be called with outport 1 as source on a mono
        # player.
        for c in cm.is_connected.call_args_list:
            assert (
                c.args[0] != "Audio_Player-X:outport 1"
            ), f"mono check leaked an outport 1 probe: {c}"

    def test_mono_with_4_outputs(self):
        # 4 fan-out targets, mono player: outport 0 → all 4 inputs.
        cm = self._make_conn_man(
            existing_ports={
                "Audio_Player-X:outport 0",
                "test_mixer:input_1",
                "test_mixer:input_2",
                "test_mixer:input_3",
                "test_mixer:input_4",
            },
            edges={
                "Audio_Player-X:outport 0": [
                    "test_mixer:input_1",
                    "test_mixer:input_2",
                    "test_mixer:input_3",
                    "test_mixer:input_4",
                ],
            },
        )
        audio_outputs = [
            "system:playback_1",
            "system:playback_2",
            "system:playback_3",
            "system:playback_4",
        ]
        m = self._build_mixer(audio_outputs, cm)
        assert (
            m.player_connections_correct(
                "Audio_Player-X",
                "outport",
                audio_outputs,
            )
            is True
        )

    def test_subprocess_crashed_returns_false_immediately(self):
        # outport 0 missing → return False without probing edges.
        cm = self._make_conn_man(
            existing_ports={
                "test_mixer:input_1",
                "test_mixer:input_2",
            },
            edges={},
        )
        m = self._build_mixer(["system:playback_1", "system:playback_2"], cm)
        assert (
            m.player_connections_correct(
                "Audio_Player-X",
                "outport",
                ["system:playback_1", "system:playback_2"],
            )
            is False
        )
        # No edge probes when port is gone.
        cm.is_connected.assert_not_called()

    def test_query_count_is_linear_in_selected_outputs(self):
        # 8 outputs → at most 8 is_connected calls. Quadratic blowup
        # under refactor would push this over the bound.
        n = 8
        audio_outputs = [f"system:playback_{i+1}" for i in range(n)]
        existing_ports = {f"test_mixer:input_{i+1}" for i in range(n)}
        existing_ports.update(
            {
                "Audio_Player-X:outport 0",
                "Audio_Player-X:outport 1",
            }
        )
        edges = {
            "Audio_Player-X:outport 0": [
                f"test_mixer:input_{i+1}" for i in range(0, n, 2)
            ],
            "Audio_Player-X:outport 1": [
                f"test_mixer:input_{i+1}" for i in range(1, n, 2)
            ],
        }
        cm = self._make_conn_man(existing_ports, edges)
        m = self._build_mixer(audio_outputs, cm)
        assert (
            m.player_connections_correct(
                "Audio_Player-X",
                "outport",
                audio_outputs,
            )
            is True
        )
        assert cm.is_connected.call_count == n


class TestMixerClient:
    """Test cases for MixerClient class."""

    @pytest.fixture
    def mixer_client(self):
        """Create MixerClient instance for testing.

        mixer_id='test' → client_name 'test_mixer' (get_mixer_client_name)."""
        with patch("cuemsengine.players.AudioMixer.PlayerClient.__init__"):
            client = MixerClient(
                player_port=8000, channel_number=4, mixer_id="test"
            )
            return client

    def test_mixer_client_initialization(self, mixer_client):
        """Test MixerClient initialization."""
        assert mixer_client.client_name == "test_mixer"
        assert mixer_client.channel_number == 4

    def test_set_master_volume_valid(self, mixer_client):
        """Test setting master volume with valid gain."""
        with patch.object(mixer_client, "set_value") as mock_set_value:
            mixer_client.set_master_volume(0.5)

            mock_set_value.assert_called_once_with(
                "/audiomixer/test_mixer/master", 0.5
            )

    def test_set_master_volume_invalid(self, mixer_client):
        """Test setting master volume with invalid gain."""
        with patch.object(mixer_client, "set_value") as mock_set_value:
            mixer_client.set_master_volume(1.5)  # Invalid gain > 1.0
            mixer_client.set_master_volume(-0.1)  # Invalid gain < 0.0

            # Should not call set_value for invalid gains
            mock_set_value.assert_not_called()

    def test_set_channel_volume_valid(self, mixer_client):
        """Test setting channel volume with valid parameters."""
        with patch.object(mixer_client, "set_value") as mock_set_value:
            mixer_client.set_channel_volume(2, 0.7)

            mock_set_value.assert_called_once_with(
                "/audiomixer/test_mixer/2", 0.7
            )

    def test_set_channel_volume_invalid_channel(self, mixer_client):
        """Test setting channel volume with invalid channel number."""
        with patch.object(mixer_client, "set_value") as mock_set_value:
            # Invalid channel >= channel_number
            mixer_client.set_channel_volume(5, 0.7)

            mock_set_value.assert_not_called()

    def test_set_channel_volume_invalid_gain(self, mixer_client):
        """Test setting channel volume with invalid gain."""
        with patch.object(mixer_client, "set_value") as mock_set_value:
            mixer_client.set_channel_volume(2, 1.5)  # Invalid gain > 1.0

            mock_set_value.assert_not_called()

    def test_set_all_channels_volume(self, mixer_client):
        """Test setting volume for all channels."""
        with patch.object(
            mixer_client, "set_channel_volume"
        ) as mock_set_channel:
            mixer_client.set_all_channels_volume(0.8)

            # Should call set_channel_volume for each channel (0, 1, 2, 3)
            expected_calls = [(0, 0.8), (1, 0.8), (2, 0.8), (3, 0.8)]
            mock_set_channel.assert_has_calls(
                [call(*expected_call) for expected_call in expected_calls]
            )

    def test_mute_channel(self, mixer_client):
        """Test muting a channel."""
        with patch.object(
            mixer_client, "set_channel_volume"
        ) as mock_set_channel:
            mixer_client.mute_channel(1)

            mock_set_channel.assert_called_once_with(1, 0.0)

    def test_unmute_channel(self, mixer_client):
        """Test unmuting a channel."""
        with patch.object(
            mixer_client, "set_channel_volume"
        ) as mock_set_channel:
            mixer_client.unmute_channel(1, 0.9)

            mock_set_channel.assert_called_once_with(1, 0.9)

    def test_unmute_channel_default_gain(self, mixer_client):
        """Test unmuting a channel with default gain."""
        with patch.object(
            mixer_client, "set_channel_volume"
        ) as mock_set_channel:
            mixer_client.unmute_channel(1)

            mock_set_channel.assert_called_once_with(1, 1.0)

    def test_mute_master(self, mixer_client):
        """Test muting master volume."""
        with patch.object(
            mixer_client, "set_master_volume"
        ) as mock_set_master:
            mixer_client.mute_master()

            mock_set_master.assert_called_once_with(0.0)

    def test_unmute_master(self, mixer_client):
        """Test unmuting master volume."""
        with patch.object(
            mixer_client, "set_master_volume"
        ) as mock_set_master:
            mixer_client.unmute_master(0.8)

            mock_set_master.assert_called_once_with(0.8)

    def test_unmute_master_default_gain(self, mixer_client):
        """Test unmuting master volume with default gain."""
        with patch.object(
            mixer_client, "set_master_volume"
        ) as mock_set_master:
            mixer_client.unmute_master()

            mock_set_master.assert_called_once_with(1.0)

    def test_add_to_oscquery_server(self, mixer_client):
        """Test adding mixer to OSCQuery server."""
        mock_server = Mock()
        mock_endpoints = {
            "/audiomixer/test_mixer/master": [None, None, 1.0],
            "/audiomixer/test_mixer/0": [None, None, 1.0],
            "/audiomixer/test_mixer/1": [None, None, 1.0],
        }

        with (
            patch.object(
                mixer_client, "get_endpoints", return_value=mock_endpoints
            ),
            patch(
                "cuemsengine.players.AudioMixer.add_callback_to_all"
            ) as mock_add_callback,
        ):

            mixer_client.add_to_oscquery_server(mock_server)

            mock_add_callback.assert_called_once()
            mock_server.add_endpoints.assert_called_once()


class TestBuildMixerOscEndpoints:
    """Test cases for build_mixer_osc_endpoints function."""

    def test_build_mixer_osc_endpoints(self):
        """Test building OSC endpoints for mixer."""
        endpoints = build_mixer_osc_endpoints("test_mixer", 3)

        expected_keys = [
            "/audiomixer/test_mixer/master",
            "/audiomixer/test_mixer/0",
            "/audiomixer/test_mixer/1",
            "/audiomixer/test_mixer/2",
        ]

        for key in expected_keys:
            assert key in endpoints
            # [ValueType, callback, default_value]
            assert len(endpoints[key]) == 3
            assert endpoints[key][2] == 1.0  # Default value should be 1.0

    def test_build_mixer_osc_endpoints_zero_channels(self):
        """Test building OSC endpoints with zero channels."""
        endpoints = build_mixer_osc_endpoints("test_mixer", 0)

        # Should only have master volume
        assert "/audiomixer/test_mixer/master" in endpoints
        assert len(endpoints) == 1


class TestStartAudioMixer:
    """Test cases for start_audio_mixer function."""

    def test_start_audio_mixer(self):
        """Test starting audio mixer and client."""
        mock_audio_outputs = [{"name": "output_1"}, {"name": "output_2"}]

        with (
            patch(
                "cuemsengine.players.AudioMixer.AudioMixer"
            ) as mock_mixer_class,
            patch(
                "cuemsengine.players.AudioMixer.MixerClient"
            ) as mock_client_class,
            patch("cuemsengine.players.AudioMixer.sleep"),
        ):

            # Mock mixer instance
            mock_mixer = Mock()
            mock_mixer.pid = 12345
            mock_mixer_class.return_value = mock_mixer

            # Mock client instance
            mock_client = Mock()
            mock_client_class.return_value = mock_client

            mixer, client = start_audio_mixer(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123"
            )

            # Verify mixer was created with correct parameters
            mock_mixer_class.assert_called_once_with(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path=None,
                args=None
            )

            # Verify client was created with correct parameters
            mock_client_class.assert_called_once_with(
                player_port=8000,
                channel_number=2,
                mixer_id="test-node-123"
            )

            assert mixer == mock_mixer
            assert client == mock_client

    def test_start_audio_mixer_with_custom_path(self):
        """Test starting audio mixer with custom jack-volume path."""
        mock_audio_outputs = [{"name": "output_1"}]

        with (
            patch(
                "cuemsengine.players.AudioMixer.AudioMixer"
            ) as mock_mixer_class,
            patch(
                "cuemsengine.players.AudioMixer.MixerClient"
            ) as mock_client_class,
            patch("cuemsengine.players.AudioMixer.sleep")
        ):

            mock_mixer = Mock()
            mock_mixer.pid = 12345
            mock_mixer_class.return_value = mock_mixer
            mock_client_class.return_value = Mock()

            start_audio_mixer(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path="/custom/jack-volume"
            )

            mock_mixer_class.assert_called_once_with(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path="/custom/jack-volume",
                args=None
            )
