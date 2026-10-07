# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

import logging
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
        return ["system:playback_1", "system:playback_2"]

    @pytest.fixture
    def mock_conn_manager(self):
        """Mock JackConnectionManager."""
        with patch("cuemsengine.players.AudioMixer.JackConnectionManager") as mock_conn:
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
                path="/usr/local/bin/jack-volume",
            )
            return mixer

    def test_audio_mixer_initialization(self, mock_audio_outputs, mock_conn_manager):
        """Test AudioMixer initialization."""
        with (
            patch("cuemsengine.players.AudioMixer.sleep"),
            patch.object(AudioMixer, "call_subprocess"),
        ):
            mixer = AudioMixer(
                audio_outputs=mock_audio_outputs, port=8000, mixer_id="test-node-123"
            )

            assert mixer.port == 8000
            assert mixer.channel_number == 2
            assert mixer.client_name == "test-node-123_mixer"
            assert mixer.path == "/usr/local/bin/jack-volume"
            assert mixer.args == ["-c", "test-node-123_mixer", "-p", "8000", "-n", "2"]

    def test_audio_mixer_initialization_with_custom_path(
        self, mock_audio_outputs, mock_conn_manager
    ):
        """Test AudioMixer initialization with custom jack-volume path."""
        with (
            patch("cuemsengine.players.AudioMixer.sleep"),
            patch.object(AudioMixer, "call_subprocess"),
        ):
            mixer = AudioMixer(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path="/custom/path/jack-volume",
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


def _build_bare_mixer(audio_outputs, conn_man, client_name="test_mixer"):
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

    PLAYER = "test_player"
    CH0 = "test_player:output 0"
    CH1 = "test_player:output 1"

    def test_invalid_channel_makes_no_connections(self):
        ports = {self.CH0, self.CH1, "test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(["system:playback_1", "system:playback_2"], cm)
        with patch("time.sleep"):
            m.connect_player_to_mixer(self.PLAYER, "output", 5)  # >= channel_number
        cm.connect_by_name.assert_not_called()

    def test_channel_0_maps_to_inputs_1_2(self):
        ports = {self.CH0, self.CH1, "test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(["system:playback_1", "system:playback_2"], cm)
        with patch("time.sleep"):
            m.connect_player_to_mixer(self.PLAYER, "output", 0)
        cm.connect_by_name.assert_any_call(self.CH0, "test_mixer:input_1")
        cm.connect_by_name.assert_any_call(self.CH1, "test_mixer:input_2")

    def test_channel_1_maps_to_inputs_3_4(self):
        ports = {self.CH0, self.CH1, "test_mixer:input_3", "test_mixer:input_4"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(["system:playback_1", "system:playback_2"], cm)
        with patch("time.sleep"):
            m.connect_player_to_mixer(self.PLAYER, "output", 1)
        cm.connect_by_name.assert_any_call(self.CH0, "test_mixer:input_3")
        cm.connect_by_name.assert_any_call(self.CH1, "test_mixer:input_4")

    def test_disconnects_existing_connections_first(self):
        ports = {self.CH0, self.CH1, "test_mixer:input_1", "test_mixer:input_2"}
        edges = {
            self.CH0: ["system:playback_1", "other:input"],
            self.CH1: ["system:playback_2"],
        }
        cm = _fake_conn_man(ports, edges)
        m = _build_bare_mixer(["system:playback_1", "system:playback_2"], cm)
        with patch("time.sleep"):
            m.connect_player_to_mixer(self.PLAYER, "output", 0)
        assert cm.disconnect_by_name.call_count == 3  # 2 from ch0, 1 from ch1

    def test_timeout_returns_false_without_connecting(self):
        # Player ports never register → early return False, nothing wired.
        ports = {"test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(["system:playback_1", "system:playback_2"], cm)
        with patch("time.sleep"):
            result = m.connect_player_to_mixer(self.PLAYER, "output", 0)
        assert result is False
        cm.connect_by_name.assert_not_called()


class TestConnectPlayerToOutputs:
    """Direct coverage for the 2026-07 silent-but-green fix: the port-wait
    loop must actually wait, and the bool return contract must hold."""

    PLAYER = "Audio_Player-X"
    CH0 = "Audio_Player-X:outport 0"
    CH1 = "Audio_Player-X:outport 1"
    OUTS = ["system:playback_1", "system:playback_2"]

    def test_port_never_registers_returns_false_no_connect(self):
        ports = {"test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch("time.sleep") as mock_sleep:
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)
        assert result is False
        cm.connect_by_name.assert_not_called()
        # The wait loop must actually have waited (the old defeated guard
        # broke on attempt 0 without a single sleep).
        assert mock_sleep.call_count >= 29

    def test_a_dead_player_process_ends_the_wait(self, caplog):
        """869f9wqpn: a STOP (or a load) kills the player while the engine
        is still waiting for its JACK ports. They can never register now,
        but the wait ran its full ~15 s, holding that cue's arm all along."""
        ports = {"test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        polls = []

        def process_gone():
            polls.append(1)
            return len(polls) > 2  # alive twice, then dead

        with caplog.at_level("WARNING"), patch("time.sleep") as mock_sleep:
            result = m.connect_player_to_outputs(
                self.PLAYER, "outport", self.OUTS, should_abort=process_gone
            )
        assert result is False
        cm.connect_by_name.assert_not_called()
        assert mock_sleep.call_count == 2, "kept waiting for a dead process"
        assert "exited before registering" in caplog.text

    def test_a_live_player_still_gets_the_whole_wait(self):
        ports = {"test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch("time.sleep") as mock_sleep:
            result = m.connect_player_to_outputs(
                self.PLAYER, "outport", self.OUTS, should_abort=lambda: False
            )
        assert result is False
        assert mock_sleep.call_count >= 29

    def test_registered_ports_win_over_the_abort_check(self):
        ports = {"test_mixer:input_1", "test_mixer:input_2", self.CH0, self.CH1}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch("time.sleep"):
            result = m.connect_player_to_outputs(
                self.PLAYER, "outport", self.OUTS, should_abort=lambda: True
            )
        assert result is True

    def test_port_registers_late_waits_then_connects(self):
        ports = {"test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)

        def register_ports(_delay):
            ports.update({self.CH0, self.CH1})

        with patch("time.sleep", side_effect=register_ports):
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)
        assert result is True
        cm.connect_by_name.assert_any_call(self.CH0, "test_mixer:input_1")
        cm.connect_by_name.assert_any_call(self.CH1, "test_mixer:input_2")

    def test_stereo_routing(self):
        ports = {self.CH0, self.CH1, "test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch("time.sleep"):
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)
        assert result is True
        cm.connect_by_name.assert_any_call(self.CH0, "test_mixer:input_1")
        cm.connect_by_name.assert_any_call(self.CH1, "test_mixer:input_2")

    def test_mono_fans_outport_0_to_both_inputs(self):
        # No outport 1 → after the grace window the player is mono and
        # outport 0 feeds both mixer inputs (centred mono).
        ports = {self.CH0, "test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch("time.sleep"):
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)
        assert result is True
        cm.connect_by_name.assert_any_call(self.CH0, "test_mixer:input_1")
        cm.connect_by_name.assert_any_call(self.CH0, "test_mixer:input_2")
        for c in cm.connect_by_name.call_args_list:
            assert c.args[0] != self.CH1

    def test_one_connect_failure_returns_false(self):
        ports = {self.CH0, self.CH1, "test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports, connect_result=[True, False])
        m = _build_bare_mixer(self.OUTS, cm)
        with patch("time.sleep"):
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)
        assert result is False
        assert cm.connect_by_name.call_count == 2  # both attempted

    def test_no_mixer_inputs_returns_false(self):
        ports = {self.CH0, self.CH1}  # mixer inputs missing
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with patch("time.sleep"):
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)
        assert result is False
        cm.connect_by_name.assert_not_called()

    def test_success_logs_elapsed_time_and_attempts(self, caplog):
        """869f79ecc: the success path left no trace before this -- only
        failure was logged (DEBUG per retry, WARNING on giving up). Right-
        sizing the retry ceiling (currently an unmeasured ~15s, CLAUDE.md:91)
        against arm()'s wait timeout needs real registration-latency data
        from test2/the fleet, not another guess; this is step 1, pure
        logging, no behaviour change."""
        ports = {"test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)

        def register_ports(_delay):
            ports.update({self.CH0, self.CH1})

        with (
            patch("time.sleep", side_effect=register_ports),
            caplog.at_level(logging.INFO),
        ):
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)

        assert result is True
        matches = [
            r
            for r in caplog.records
            if self.PLAYER in r.getMessage() and "registered" in r.getMessage()
        ]
        assert len(matches) == 1, caplog.records
        assert "attempt" in matches[0].getMessage()

    def test_immediate_registration_still_logs(self, caplog):
        """attempt 0 (no wait at all) must log too, not just the retried case."""
        ports = {self.CH0, self.CH1, "test_mixer:input_1", "test_mixer:input_2"}
        cm = _fake_conn_man(ports)
        m = _build_bare_mixer(self.OUTS, cm)
        with (
            patch("time.sleep"),
            caplog.at_level(logging.INFO),
        ):
            result = m.connect_player_to_outputs(self.PLAYER, "outport", self.OUTS)
        assert result is True
        assert any(
            self.PLAYER in r.getMessage() and "registered" in r.getMessage()
            for r in caplog.records
        )


class TestPlayerConnectionsCorrect:
    """Pin the routing equivalence between player_connections_correct and
    connect_player_to_outputs. If connect_player_to_outputs is refactored
    and these diverge, run_audioCue will silently choose the wrong branch
    on every GO.

    869fbyjzx: the check is now a diff built on one get_connections per
    outport (both share _expected_edges), so the mock answers
    get_connections; every case and its intent is unchanged."""

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
        cm.is_connected.side_effect = lambda src, dst: dst in edges.get(src, [])
        cm.get_connections.side_effect = lambda p: list(edges.get(p, []))
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
        # Outport 1 must never be read on a mono player.
        for c in cm.get_connections.call_args_list + cm.is_connected.call_args_list:
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
        cm.get_connections.assert_not_called()

    def test_query_count_is_linear_in_selected_outputs(self):
        # 8 outputs → one get_connections per outport (2), whatever the
        # number of outputs; it runs on the GO path before /offset.
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
        assert cm.get_connections.call_count == 2
        cm.is_connected.assert_not_called()


class TestMixerClient:
    """Test cases for MixerClient class."""

    @pytest.fixture
    def mixer_client(self):
        """Create MixerClient instance for testing.

        mixer_id='test' → client_name 'test_mixer' (get_mixer_client_name).

        PlayerClient.__init__ is patched (no real OSC device); seed the
        OssiaNodes fields that __init__ would have set so GC/__del__ is safe.
        """
        with patch("cuemsengine.players.AudioMixer.PlayerClient.__init__"):
            client = MixerClient(player_port=8000, channel_number=4, mixer_id="test")
            client.nodes = {}
            client.device = None
            return client

    def test_mixer_client_initialization(self, mixer_client):
        """Test MixerClient initialization."""
        assert mixer_client.client_name == "test_mixer"
        assert mixer_client.channel_number == 4

    def test_set_master_volume_valid(self, mixer_client):
        """Test setting master volume with valid gain."""
        with patch.object(mixer_client, "set_value") as mock_set_value:
            mixer_client.set_master_volume(0.5)

            mock_set_value.assert_called_once_with("/audiomixer/test_mixer/master", 0.5)

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

            mock_set_value.assert_called_once_with("/audiomixer/test_mixer/2", 0.7)

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
        with patch.object(mixer_client, "set_channel_volume") as mock_set_channel:
            mixer_client.set_all_channels_volume(0.8)

            # Should call set_channel_volume for each channel (0, 1, 2, 3)
            expected_calls = [(0, 0.8), (1, 0.8), (2, 0.8), (3, 0.8)]
            mock_set_channel.assert_has_calls(
                [call(*expected_call) for expected_call in expected_calls]
            )

    def test_mute_channel(self, mixer_client):
        """Test muting a channel."""
        with patch.object(mixer_client, "set_channel_volume") as mock_set_channel:
            mixer_client.mute_channel(1)

            mock_set_channel.assert_called_once_with(1, 0.0)

    def test_unmute_channel(self, mixer_client):
        """Test unmuting a channel."""
        with patch.object(mixer_client, "set_channel_volume") as mock_set_channel:
            mixer_client.unmute_channel(1, 0.9)

            mock_set_channel.assert_called_once_with(1, 0.9)

    def test_unmute_channel_default_gain(self, mixer_client):
        """Test unmuting a channel with default gain."""
        with patch.object(mixer_client, "set_channel_volume") as mock_set_channel:
            mixer_client.unmute_channel(1)

            mock_set_channel.assert_called_once_with(1, 1.0)

    def test_mute_master(self, mixer_client):
        """Test muting master volume."""
        with patch.object(mixer_client, "set_master_volume") as mock_set_master:
            mixer_client.mute_master()

            mock_set_master.assert_called_once_with(0.0)

    def test_unmute_master(self, mixer_client):
        """Test unmuting master volume."""
        with patch.object(mixer_client, "set_master_volume") as mock_set_master:
            mixer_client.unmute_master(0.8)

            mock_set_master.assert_called_once_with(0.8)

    def test_unmute_master_default_gain(self, mixer_client):
        """Test unmuting master volume with default gain."""
        with patch.object(mixer_client, "set_master_volume") as mock_set_master:
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
            patch.object(mixer_client, "get_endpoints", return_value=mock_endpoints),
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
            patch("cuemsengine.players.AudioMixer.AudioMixer") as mock_mixer_class,
            patch("cuemsengine.players.AudioMixer.MixerClient") as mock_client_class,
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
                audio_outputs=mock_audio_outputs, port=8000, mixer_id="test-node-123"
            )

            # Verify mixer was created with correct parameters
            mock_mixer_class.assert_called_once_with(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path=None,
                args=None,
            )

            # Verify client was created with correct parameters
            mock_client_class.assert_called_once_with(
                player_port=8000, channel_number=2, mixer_id="test-node-123"
            )

            assert mixer == mock_mixer
            assert client == mock_client

    def test_start_audio_mixer_with_custom_path(self):
        """Test starting audio mixer with custom jack-volume path."""
        mock_audio_outputs = [{"name": "output_1"}]

        with (
            patch("cuemsengine.players.AudioMixer.AudioMixer") as mock_mixer_class,
            patch("cuemsengine.players.AudioMixer.MixerClient") as mock_client_class,
            patch("cuemsengine.players.AudioMixer.sleep"),
        ):
            mock_mixer = Mock()
            mock_mixer.pid = 12345
            mock_mixer_class.return_value = mock_mixer
            mock_client_class.return_value = Mock()

            start_audio_mixer(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path="/custom/jack-volume",
            )

            mock_mixer_class.assert_called_once_with(
                audio_outputs=mock_audio_outputs,
                port=8000,
                mixer_id="test-node-123",
                path="/custom/jack-volume",
                args=None,
            )


class TestMixerClientGainState:
    """869cwpkz4: MixerClient records the gain it commands in _gain_state so the
    node can snapshot the TRUE mixer volume to the controller (jack-volume is
    write-only and cannot be read back)."""

    @pytest.fixture
    def mixer_client(self):
        with patch("cuemsengine.players.AudioMixer.PlayerClient.__init__"):
            client = MixerClient(player_port=8000, channel_number=4, mixer_id="test")
            client.nodes = {}
            client.device = None
            return client

    def test_apply_volume_master_records_and_sends(self, mixer_client):
        with patch.object(mixer_client, "set_value") as sv:
            assert mixer_client.apply_volume("master", 0.5) is True
        sv.assert_called_once_with("/audiomixer/test_mixer/master", 0.5)
        assert mixer_client.snapshot() == {"master": 0.5}

    def test_apply_volume_int_channel_records(self, mixer_client):
        with patch.object(mixer_client, "set_value") as sv:
            assert mixer_client.apply_volume(2, 0.7) is True
        sv.assert_called_once_with("/audiomixer/test_mixer/2", 0.7)
        assert mixer_client.snapshot() == {"2": 0.7}

    def test_apply_volume_numeric_string_channel(self, mixer_client):
        # route_audio_message passes the channel as a string from the OSC path.
        with patch.object(mixer_client, "set_value") as sv:
            assert mixer_client.apply_volume("1", 0.3) is True
        sv.assert_called_once_with("/audiomixer/test_mixer/1", 0.3)
        assert mixer_client.snapshot() == {"1": 0.3}

    def test_apply_volume_invalid_gain_rejected(self, mixer_client):
        with patch.object(mixer_client, "set_value") as sv:
            assert mixer_client.apply_volume("master", 1.5) is False
        sv.assert_not_called()
        assert mixer_client.snapshot() == {}

    def test_apply_volume_out_of_range_channel_rejected(self, mixer_client):
        with patch.object(mixer_client, "set_value") as sv:
            assert mixer_client.apply_volume(9, 0.5) is False  # channel_number=4
        sv.assert_not_called()
        assert mixer_client.snapshot() == {}

    def test_apply_volume_nonnumeric_channel_rejected(self, mixer_client):
        with patch.object(mixer_client, "set_value") as sv:
            assert mixer_client.apply_volume("left", 0.5) is False
        sv.assert_not_called()
        assert mixer_client.snapshot() == {}

    def test_typed_setters_record_state(self, mixer_client):
        with patch.object(mixer_client, "set_value"):
            mixer_client.set_master_volume(0.2)
            mixer_client.set_channel_volume(3, 0.4)
        assert mixer_client.snapshot() == {"master": 0.2, "3": 0.4}

    def test_reset_volumes_populates_all_to_unity(self, mixer_client):
        with patch.object(mixer_client, "set_value"):
            mixer_client.reset_volumes()
        assert mixer_client.snapshot() == {
            "master": 1.0,
            "0": 1.0,
            "1": 1.0,
            "2": 1.0,
            "3": 1.0,
        }

    def test_snapshot_is_a_copy(self, mixer_client):
        with patch.object(mixer_client, "set_value"):
            mixer_client.apply_volume("master", 0.5)
        snap = mixer_client.snapshot()
        snap["master"] = 0.0
        assert mixer_client.snapshot() == {"master": 0.5}


# ---------------------------------------------------------------------------
# 869fbyjzx — wire an audio player only once it reports itself started, and
# check / repair its wiring at GO edge by edge.
# ---------------------------------------------------------------------------

PL = "Audio_Player-X"
P0 = f"{PL}:outport 0"
P1 = f"{PL}:outport 1"
IN1, IN2, IN3, IN4 = (f"test_mixer:input_{i}" for i in range(1, 5))
OUTS2 = ["system:playback_1", "system:playback_2"]
OUTS4 = [f"system:playback_{i}" for i in range(1, 5)]


class _ReadyNever:
    """Stands in for Player.ready: wait() returns at once, never set."""

    def __init__(self):
        self.calls = 0

    def wait(self, _timeout):
        self.calls += 1
        return False


class _ReadyAfter(_ReadyNever):
    def __init__(self, n):
        super().__init__()
        self.n = n

    def wait(self, _timeout):
        self.calls += 1
        return self.calls > self.n


class TestPlayerReadyLine:
    """Player.ready is set by the stdout reader on the player's RUNNING line."""

    @staticmethod
    def _run(lines):
        import io

        from cuemsengine.players.Player import Player

        player = Player()
        fake = Mock()
        fake.pid = 1234
        fake.stdout = io.BytesIO(b"".join(lines))
        fake.poll.side_effect = [None, 0]
        with (
            patch("cuemsengine.players.Player.Popen", return_value=fake),
            patch("cuemsengine.players.Player.sleep"),
        ):
            player.call_subprocess(["cuems-audioplayer"])
        return player

    def test_the_running_line_sets_ready(self):
        player = self._run(
            [
                b"[Cuems:dabc] [OK] AudioPlayer object created OK!\n",
                b"[Cuems:dabc] [OK] RUNNING!\n",
            ]
        )
        assert player.ready.is_set()

    def test_a_second_run_starts_not_ready(self):
        from cuemsengine.players.Player import Player

        player = Player()
        player.ready.set()  # left over from an earlier run
        import io

        fake = Mock()
        fake.pid = 1
        fake.stdout = io.BytesIO(b"starting\n")
        fake.poll.side_effect = [None, 0]
        with (
            patch("cuemsengine.players.Player.Popen", return_value=fake),
            patch("cuemsengine.players.Player.sleep"),
        ):
            player.call_subprocess(["cuems-audioplayer"])
        assert not player.ready.is_set()

    def test_other_lines_do_not(self):
        player = self._run(
            [
                b"[Cuems:dabc] [OK] AudioPlayer object created OK!\n",
                b"Starting object with 2 channels\n",
            ]
        )
        assert not player.ready.is_set()


class TestConnectWaitsForReady:
    @staticmethod
    def _mixer(ports, edges=None):
        cm = _fake_conn_man(ports, edges)
        return _build_bare_mixer(OUTS2, cm), cm

    def test_ready_already_set_wires_without_waiting(self, caplog):
        import threading

        ready = threading.Event()
        ready.set()
        m, cm = self._mixer({P0, P1, IN1, IN2})
        with patch("time.sleep") as mock_sleep, caplog.at_level(logging.INFO):
            result = m.connect_player_to_outputs(PL, "outport", OUTS2, ready=ready)
        assert result is True
        mock_sleep.assert_not_called()
        assert "reported RUNNING" in caplog.text
        cm.connect_by_name.assert_any_call(P0, IN1)
        cm.connect_by_name.assert_any_call(P1, IN2)

    def test_ready_after_some_slices_then_wires(self, caplog):
        ready = _ReadyAfter(3)
        m, cm = self._mixer({P0, P1, IN1, IN2})
        with patch("time.sleep"), caplog.at_level(logging.INFO):
            result = m.connect_player_to_outputs(PL, "outport", OUTS2, ready=ready)
        assert result is True
        assert ready.calls == 4
        assert "reported RUNNING after" in caplog.text

    def test_wiring_happens_after_ready_and_removes_the_auto_connect(self):
        """The point of the gate: by RUNNING, RtAudio has auto-connected the
        outports to system:playback, and the wiring removes those edges."""
        edges = {P0: ["system:playback_1"], P1: ["system:playback_2"]}
        m, cm = self._mixer({P0, P1, IN1, IN2}, edges)
        ready = _ReadyAfter(0)
        with patch("time.sleep"):
            assert m.connect_player_to_outputs(PL, "outport", OUTS2, ready=ready)
        cm.disconnect_by_name.assert_any_call(P0, "system:playback_1")
        cm.disconnect_by_name.assert_any_call(P1, "system:playback_2")

    def test_a_dead_player_ends_the_ready_wait(self, caplog):
        ready = _ReadyNever()
        m, cm = self._mixer({IN1, IN2})
        with patch("time.sleep"), caplog.at_level(logging.WARNING):
            result = m.connect_player_to_outputs(
                PL, "outport", OUTS2, should_abort=lambda: True, ready=ready
            )
        assert result is False
        assert ready.calls == 1
        cm.connect_by_name.assert_not_called()
        assert "exited before reporting RUNNING" in caplog.text

    def test_never_ready_falls_back_to_the_port_and_warns(self, caplog):
        ready = _ReadyNever()
        m, cm = self._mixer({P0, P1, IN1, IN2})
        with patch("time.sleep"), caplog.at_level(logging.WARNING):
            result = m.connect_player_to_outputs(
                PL, "outport", OUTS2, should_abort=lambda: False, ready=ready
            )
        assert result is True
        assert "never reported RUNNING" in caplog.text
        cm.connect_by_name.assert_any_call(P0, IN1)

    def test_no_jack_client_returns_at_once_without_waiting(self):
        """A JACK-stubbed host (the test2 controller) must not wait for ready:
        the 2026-07 load->GO 16 s regression came from such a wait."""
        ready = _ReadyNever()
        m, cm = self._mixer({P0, P1, IN1, IN2})
        cm.client = None
        with patch("time.sleep") as mock_sleep:
            result = m.connect_player_to_outputs(PL, "outport", OUTS2, ready=ready)
        assert result is False
        assert ready.calls == 0
        mock_sleep.assert_not_called()

    def test_one_budget_for_both_phases(self):
        """Never ready AND no port: the total stays today's ceiling (14.5 s),
        not the ready wait plus a full port wait on top."""
        ready = _ReadyNever()
        m, cm = self._mixer({IN1, IN2})
        with patch("time.sleep") as mock_sleep:
            result = m.connect_player_to_outputs(
                PL, "outport", OUTS2, should_abort=lambda: False, ready=ready
            )
        assert result is False
        ready_s = ready.calls * 0.05
        port_s = sum(c.args[0] for c in mock_sleep.call_args_list)
        assert ready_s + port_s <= 14.5 + 1e-9
        assert ready_s >= 14.5 - 0.05

    def test_without_ready_nothing_changes(self):
        m, cm = self._mixer({P0, P1, IN1, IN2})
        with patch("time.sleep"):
            assert m.connect_player_to_outputs(PL, "outport", OUTS2) is True


class TestPlayerConnectionDiff:
    """Every case asserts both lists exactly."""

    @staticmethod
    def _diff(ports, edges, audio_outputs=OUTS2, selected=None):
        cm = _fake_conn_man(ports, edges)
        m = _build_bare_mixer(audio_outputs, cm)
        return m.player_connection_diff(PL, "outport", selected or audio_outputs)

    def test_clean(self):
        assert self._diff({P0, P1, IN1, IN2}, {P0: [IN1], P1: [IN2]}) == ([], [])

    def test_one_stray(self):
        edges = {P0: [IN1, "system:playback_1"], P1: [IN2]}
        assert self._diff({P0, P1, IN1, IN2}, edges) == (
            [],
            [(P0, "system:playback_1")],
        )

    def test_right_edge_missing(self):
        assert self._diff({P0, P1, IN1, IN2}, {P0: [IN1]}) == ([(P1, IN2)], [])

    def test_wrong_destination_is_a_stray_plus_the_missing_edge(self):
        edges = {P0: [IN1], P1: [IN3]}
        assert self._diff({P0, P1, IN1, IN2, IN3}, edges) == (
            [(P1, IN2)],
            [(P1, IN3)],
        )

    def test_stereo_player_one_output_selected(self):
        # Arm wires only outport 0 to input_1; outport 1 -> input_1 is stray.
        edges = {P0: [IN1], P1: [IN1]}
        assert self._diff(
            {P0, P1, IN1, IN2}, edges, selected=["system:playback_1"]
        ) == ([], [(P1, IN1)])

    def test_four_outputs_with_a_missing_middle_input_shifts_the_pairing(self):
        # input_2 does not exist: targets are [input_1, input_3, input_4],
        # so L -> 1, R -> 3, L -> 4, exactly as the arm-time wiring pairs them.
        edges = {P0: [IN1, IN4], P1: [IN3]}
        assert self._diff({P0, P1, IN1, IN3, IN4}, edges, audio_outputs=OUTS4) == (
            [],
            [],
        )

    def test_strays_on_both_outports(self):
        edges = {
            P0: [IN1, "system:playback_1"],
            P1: [IN2, "system:playback_2"],
        }
        assert self._diff({P0, P1, IN1, IN2}, edges) == (
            [],
            [(P0, "system:playback_1"), (P1, "system:playback_2")],
        )

    def test_mono_player_ignores_outport_1(self):
        edges = {P0: [IN1, IN2]}
        assert self._diff({P0, IN1, IN2}, edges) == ([], [])

    def test_mono_at_arm_stereo_at_go_converges(self):
        # Wired as mono (outport 0 to both); outport 1 exists by GO.
        edges = {P0: [IN1, IN2]}
        assert self._diff({P0, P1, IN1, IN2}, edges) == ([(P1, IN2)], [(P0, IN2)])

    def test_an_edge_is_never_both_missing_and_stray(self):
        edges = {P0: ["x:y", IN2], P1: [IN1]}
        missing, stray = self._diff({P0, P1, IN1, IN2}, edges)
        assert not set(missing) & set(stray)

    def test_no_mixer_input_is_none_not_clean(self):
        assert self._diff({P0, P1}, {P0: [], P1: []}) is None

    def test_player_port_gone_is_none(self):
        assert self._diff({IN1, IN2}, {}) is None


class TestRepairPlayerConnections:
    @staticmethod
    def _mixer(edges, connect_result=True, disconnect_result=True):
        cm = _fake_conn_man({P0, P1, IN1, IN2}, edges, connect_result)
        cm.disconnect_by_name.return_value = disconnect_result
        return _build_bare_mixer(OUTS2, cm), cm

    def test_strays_only(self):
        m, cm = self._mixer({P0: [IN1, "system:playback_1"], P1: [IN2]})
        assert m.repair_player_connections([], [(P0, "system:playback_1")]) == (
            True,
            [],
        )
        cm.disconnect_by_name.assert_called_once_with(P0, "system:playback_1")
        cm.connect_by_name.assert_not_called()

    def test_a_stray_already_gone_is_not_disconnected(self):
        m, cm = self._mixer({P0: [IN1], P1: [IN2]})
        assert m.repair_player_connections([], [(P0, "system:playback_1")]) == (
            True,
            [],
        )
        cm.disconnect_by_name.assert_not_called()

    def test_missing_only(self):
        m, cm = self._mixer({P0: [IN1]})
        assert m.repair_player_connections([(P1, IN2)], []) == (True, [])
        cm.connect_by_name.assert_called_once_with(P1, IN2)
        cm.disconnect_by_name.assert_not_called()

    def test_both(self):
        m, cm = self._mixer({P0: [IN1, "system:playback_1"]})
        m.repair_player_connections([(P1, IN2)], [(P0, "system:playback_1")])
        cm.disconnect_by_name.assert_called_once_with(P0, "system:playback_1")
        cm.connect_by_name.assert_called_once_with(P1, IN2)

    def test_a_failed_connect_is_reported(self):
        m, cm = self._mixer({P0: [IN1]}, connect_result=False)
        assert m.repair_player_connections([(P1, IN2)], []) == (False, [])

    def test_a_failed_stray_disconnect_is_reported(self):
        m, cm = self._mixer(
            {P0: [IN1, "system:playback_1"], P1: [IN2]}, disconnect_result=False
        )
        assert m.repair_player_connections([], [(P0, "system:playback_1")]) == (
            True,
            [(P0, "system:playback_1")],
        )

    def test_never_disconnects_an_expected_edge(self):
        m, cm = self._mixer({P0: [IN1, "system:playback_1"], P1: []})
        m.repair_player_connections([(P1, IN2)], [(P0, "system:playback_1")])
        for c in cm.disconnect_by_name.call_args_list:
            assert c.args[1] not in (IN1, IN2), c


class TestVerifyAudioWiringAtGo:
    """run_audioCue's GO-time check (869fbyjzx): edge by edge, never a full
    rewire — a GO can reach it while the cue is audible."""

    @staticmethod
    def _run(diff, repair=(True, [])):
        from types import SimpleNamespace

        from cuemsengine.cues.run_cue import _verify_audio_wiring_at_go

        mixer = Mock()
        mixer.player_connection_diff.return_value = diff
        mixer.repair_player_connections.return_value = repair
        _verify_audio_wiring_at_go(SimpleNamespace(id="cue-1"), mixer, PL, OUTS2)
        mixer.connect_player_to_outputs.assert_not_called()
        return mixer

    def test_clean_graph_is_left_alone(self):
        mixer = self._run(([], []))
        mixer.repair_player_connections.assert_not_called()

    def test_a_stray_is_repaired_edge_by_edge(self, caplog):
        with caplog.at_level(logging.WARNING):
            mixer = self._run(([], [(P0, "system:playback_1")]))
        mixer.repair_player_connections.assert_called_once_with(
            [], [(P0, "system:playback_1")]
        )
        # The go_repair= harness counter reads this literal prefix.
        assert "graph not wired correctly at GO" in caplog.text

    def test_a_missing_edge_is_repaired_edge_by_edge(self):
        mixer = self._run(([(P1, IN2)], []))
        mixer.repair_player_connections.assert_called_once_with([(P1, IN2)], [])

    def test_no_mixer_input_is_a_silent_cue_error(self, caplog):
        with caplog.at_level(logging.ERROR):
            mixer = self._run(None)
        mixer.repair_player_connections.assert_not_called()
        assert "will be SILENT" in caplog.text

    def test_a_failed_connect_is_a_silent_cue_error(self, caplog):
        with caplog.at_level(logging.ERROR):
            self._run(([(P1, IN2)], []), repair=(False, []))
        assert "will be SILENT" in caplog.text

    def test_a_surviving_stray_is_an_error(self, caplog):
        with caplog.at_level(logging.ERROR):
            self._run(
                ([], [(P0, "system:playback_1")]),
                repair=(True, [(P0, "system:playback_1")]),
            )
        assert "stray edge(s) still connected" in caplog.text


class TestSharedBudget:
    """The ready wait and the port wait never exceed today's ceiling,
    whatever share the ready wait used (869fbyjzx review)."""

    @pytest.mark.parametrize("n", [0, 1, 7, 10, 11, 100, 289])
    @pytest.mark.parametrize(
        "max_retries,retry_delay", [(30, 0.5), (10, 0.3), (6, 0.2)]
    )
    def test_total_wait_stays_within_the_ceiling(self, n, max_retries, retry_delay):
        ready = _ReadyAfter(n)
        m, cm = TestConnectWaitsForReady._mixer({IN1, IN2})  # port never appears
        with patch("time.sleep") as mock_sleep:
            m.connect_player_to_outputs(
                PL,
                "outport",
                OUTS2,
                should_abort=lambda: False,
                ready=ready,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
        ceiling = (max_retries - 1) * retry_delay
        # Slices actually waited: the call that returns \"ready\" waits for nothing.
        waited_slices = min(n, max(1, int(round(ceiling / 0.05))))
        used = waited_slices * 0.05 + sum(c.args[0] for c in mock_sleep.call_args_list)
        assert used <= ceiling + 1e-9, (n, used, ceiling)


class TestRepairRecheck:
    def test_a_stray_removed_by_someone_else_is_not_a_survivor(self):
        # disconnect_by_name fails (the edge was already gone), and the edge
        # is not connected any more: it is not reported as left.
        cm = _fake_conn_man({P0, P1, IN1, IN2}, {P0: ["system:playback_2"]})
        calls = {"n": 0}

        def is_connected(src, dst):
            calls["n"] += 1
            return calls["n"] == 1  # connected at the first check, gone after

        cm.is_connected.side_effect = is_connected
        cm.disconnect_by_name.return_value = False
        m = _build_bare_mixer(OUTS2, cm)
        assert m.repair_player_connections([], [(P0, "system:playback_2")]) == (
            True,
            [],
        )
