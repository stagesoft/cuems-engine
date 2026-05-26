# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from functools import partial
from time import sleep

from cuemsutils.log import Logger, logged
from pyossia import ValueType

from ..osc.helpers import add_callback_to_all
from ..osc.OssiaClient import PlayerClient
from ..tools.PortHandler import PORT_HANDLER
from .JackConnectionManager import JackConnectionManager
from .Player import Player

JACK_VOLUME_PATH = "/usr/local/bin/jack-volume"
# usage: jack-volume [-c <jack_client_name>] [-s <jack_server_name>] [-p
# <osc_port>] [-n <number_of_channels>]


class AudioMixer(Player):
    """JACK audio mixer using jack-volume controlled via OSC.

    This class manages a jack-volume process which provides volume control
    for multiple audio channels. It connects to JACK and exposes OSC control.

    OSC address format: /audiomixer/<instance>/<channel>
    where channel can be 'master' or '0', '1', '2', etc.
    """

    def __init__(
        self,
        audio_outputs,
        port,
        mixer_id: str,
        path=None,
        args: str | None = None,
    ):
        """Initialize the AudioMixer.

        Args:
            audio_outputs: List of audio output configurations
            port: OSC port for jack-volume communication
            mixer_id: Unique identifier for this mixer
            path: Optional path to jack-volume binary (defaults to
            JACK_VOLUME_PATH)
        """
        super().__init__()
        self.conn_man = JackConnectionManager()
        self.port = port
        self.ports = self.conn_man.get_ports()
        self.path = path if path else JACK_VOLUME_PATH
        self.channel_number = len(audio_outputs)
        self.audio_outputs = audio_outputs
        self.client_name = get_mixer_client_name(mixer_id)
        self.extra_args = args

        # Build command line arguments for jack-volume
        self.args = [
            "-c",
            self.client_name,
            "-p",
            str(port),
            "-n",
            str(self.channel_number),
        ]

        # Note: start() will be called by start_audio_mixer() with timeout
        # self.connect_to_jack() will be called after start() in
        # start_audio_mixer()

    @logged
    def run(self):
        """Start the jack-volume subprocess."""
        process_call_list = [self.path] + self.args
        if self.extra_args:
            for arg in self.extra_args.split():
                process_call_list.append(arg)
        Logger.info(f"Starting jack-volume with: {process_call_list}")
        self.call_subprocess(process_call_list)

    @logged
    def connect_to_jack(self, max_retries: int = 10, retry_delay: float = 0.5):
        """Connect mixer outputs to the configured playback ports.

        Retries if ports are not yet registered (race with jack-volume
        startup).
        """
        for i, playback_port in enumerate(self.audio_outputs):
            output_port = f"{self.client_name}:output_{i+1}"
            # Wait for both ports to be available
            for attempt in range(max_retries):
                if self.conn_man.port_exists(
                    output_port
                ) and self.conn_man.port_exists(playback_port):
                    break
                if attempt < max_retries - 1:
                    Logger.debug(
                        f"Waiting for JACK ports {output_port} /"
                        f" {playback_port}"
                        f" (attempt {attempt + 1}/{max_retries})"
                    )
                    sleep(retry_delay)
            else:
                Logger.warning(
                    f"JACK ports not available after {max_retries} attempts:"
                    f"{output_port} -> {playback_port}"
                )
                continue
            Logger.debug(f"Connecting {output_port} to {playback_port}")
            self.conn_man.connect_by_name(output_port, playback_port)

    @logged
    def connect_player_to_mixer(
        self,
        player_name: str,
        player_output_prefix: str = "output",
        mixer_channel: int = 0,
        max_retries: int = 30,
        retry_delay: float = 0.5,
    ):
        """Connect a player's output to a specific mixer input channel.

        First disconnects any existing connections from the player's outputs,
        then connects them to the mixer inputs. Will retry if ports are not
        immediately available (race condition with player startup).

        Handles both mono and stereo players:
        - Mono: output_0 → input_1 (single channel)
        - Stereo: output_0 → input_1, output_1 → input_2

        Args:
            player_name: Name of the player JACK client to connect
            player_output_prefix: Prefix for player's output ports (e.g.,
            'output')
            mixer_channel: Mixer input channel number (0-indexed)
            max_retries: Maximum number of connection attempts (default 10)
            retry_delay: Delay between retries in seconds (default 0.2)
        """
        from time import sleep

        if mixer_channel >= self.channel_number:
            Logger.error(
                f"Invalid mixer channel: {mixer_channel}. Max:"
                f"{self.channel_number - 1}"
            )
            return

        # Define player output ports
        # cuems-audioplayer uses space format: "outport 0", "outport 1"
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"
        mixer_input_1 = f"{self.client_name}:input_{mixer_channel * 2 + 1}"
        mixer_input_2 = f"{self.client_name}:input_{mixer_channel * 2 + 2}"

        # Wait for player JACK ports to be available (retry mechanism)
        for attempt in range(max_retries):
            # Check if ports exist by trying to get connections
            connections = self.conn_man.get_connections(channel_0_output)
            if connections is not None or self.conn_man.port_exists(
                channel_0_output
            ):
                break
            if attempt < max_retries - 1:
                Logger.debug(
                    f"Waiting for JACK port {channel_0_output} (attempt"
                    f"{attempt + 1}/{max_retries})"
                )
                sleep(retry_delay)
        else:
            Logger.warning(
                f"JACK port {channel_0_output} not available after"
                f"{max_retries} attempts"
            )

        # Check if player is stereo (has output_1) or mono (only output_0)
        is_stereo = self.conn_man.port_exists(channel_1_output)
        Logger.debug(
            f"Player {player_name} is {'stereo' if is_stereo else 'mono'}"
        )

        # First, disconnect any existing connections from player outputs
        # Guard with port_exists to avoid sending disconnect requests for
        # ports that were destroyed by a concurrent /quit.
        if self.conn_man.port_exists(channel_0_output):
            Logger.debug(
                f"Disconnecting existing connections from {channel_0_output}"
            )
            channel_0_connections = self.conn_man.get_connections(
                channel_0_output
            )
            for connection in channel_0_connections:
                Logger.debug(
                    f"Disconnecting {channel_0_output} from {connection}"
                )
                self.conn_man.disconnect_by_name(channel_0_output, connection)

        if is_stereo and self.conn_man.port_exists(channel_1_output):
            Logger.debug(
                f"Disconnecting existing connections from {channel_1_output}"
            )
            channel_1_connections = self.conn_man.get_connections(
                channel_1_output
            )
            for connection in channel_1_connections:
                Logger.debug(
                    f"Disconnecting {channel_1_output} from {connection}"
                )
                self.conn_man.disconnect_by_name(channel_1_output, connection)

        # Connect to mixer inputs
        # For mono: connect output_0 to both input_1 and input_2 (if available)
        # For stereo: connect output_0 → input_1, output_1 → input_2

        # Connect first channel
        if self.conn_man.port_exists(mixer_input_1):
            Logger.debug(f"Connecting {channel_0_output} to {mixer_input_1}")
            self.conn_man.connect_by_name(channel_0_output, mixer_input_1)
        else:
            Logger.warning(f"Mixer input port {mixer_input_1} does not exist")

        # Connect second channel (if mixer has it)
        if self.conn_man.port_exists(mixer_input_2):
            if is_stereo:
                Logger.debug(
                    f"Connecting {channel_1_output} to {mixer_input_2}"
                )
                self.conn_man.connect_by_name(channel_1_output, mixer_input_2)
            else:
                # Mono player: connect output_0 to both mixer inputs for
                # centered sound
                Logger.debug(
                    f"Mono player: Connecting {channel_0_output} to"
                    f"{mixer_input_2}"
                )
                self.conn_man.connect_by_name(channel_0_output, mixer_input_2)
        else:
            Logger.debug(
                f"Mixer input port {mixer_input_2} does not exist (mono mixer)"
            )

    @logged
    def connect_player_to_outputs(
        self,
        player_name: str,
        player_output_prefix: str = "outport",
        selected_outputs: list = None,
        max_retries: int = 30,
        retry_delay: float = 0.5,
    ):
        """
        Connect a player to specific system outputs based on cue configuration.

        Maps selected output port names to mixer inputs:
        - system:playback_1 → mixer input_1
        - system:playback_2 → mixer input_2

        For stereo audio with a single output selected, both player channels
        are summed to that output. For both outputs, normal stereo routing.

        Args:
            player_name: Name of the player JACK client to connect
            player_output_prefix: Prefix for player's output ports (e.g.,
            'outport')
            selected_outputs: List of output port names (e.g.,
            ['system:playback_1'])
            max_retries: Maximum number of connection attempts
            retry_delay: Delay between retries in seconds
        """
        from time import sleep

        # Default to stereo (both outputs) if none specified
        if not selected_outputs:
            selected_outputs = ["system:playback_1", "system:playback_2"]
            Logger.debug(
                f"No outputs specified, defaulting to stereo:"
                f"{selected_outputs}"
            )

        # Define player output ports - cuems-audioplayer uses "outport 0",
        # "outport 1"
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"

        # Build output→input mapping from the configured audio_outputs list
        output_to_input = {
            name: f"{self.client_name}:input_{i+1}"
            for i, name in enumerate(self.audio_outputs)
        }

        # Wait for player JACK ports to be available
        for attempt in range(max_retries):
            connections = self.conn_man.get_connections(channel_0_output)
            if connections is not None or self.conn_man.port_exists(
                channel_0_output
            ):
                break
            if attempt < max_retries - 1:
                Logger.debug(
                    f"Waiting for JACK port {channel_0_output} (attempt"
                    f"{attempt + 1}/{max_retries})"
                )
                sleep(retry_delay)
        else:
            Logger.warning(
                f"JACK port {channel_0_output} not available after"
                f"{max_retries} attempts"
            )
            return

        # Check if player is stereo
        is_stereo = self.conn_man.port_exists(channel_1_output)
        Logger.debug(
            f"Player {player_name} is {'stereo' if is_stereo else 'mono'}"
        )

        # First, disconnect any existing connections from player outputs
        # Guard with port_exists to avoid operating on destroyed ports.
        if self.conn_man.port_exists(channel_0_output):
            Logger.debug(
                f"Disconnecting existing connections from {channel_0_output}"
            )
            channel_0_connections = self.conn_man.get_connections(
                channel_0_output
            )
            for connection in channel_0_connections:
                self.conn_man.disconnect_by_name(channel_0_output, connection)

        if is_stereo and self.conn_man.port_exists(channel_1_output):
            channel_1_connections = self.conn_man.get_connections(
                channel_1_output
            )
            for connection in channel_1_connections:
                self.conn_man.disconnect_by_name(channel_1_output, connection)

        # Determine which mixer inputs to connect to
        target_inputs = []
        for output in selected_outputs:
            if output in output_to_input:
                mixer_input = output_to_input[output]
                if self.conn_man.port_exists(mixer_input):
                    target_inputs.append(mixer_input)
                else:
                    Logger.warning(f"Mixer input {mixer_input} does not exist")

        if not target_inputs:
            Logger.error(
                f"No valid mixer inputs found for outputs: {selected_outputs}"
            )
            return

        Logger.info(
            f"Connecting {player_name} to outputs: {selected_outputs} ->"
            f"{target_inputs}"
        )

        # Fan-out routing: treat target_inputs as alternating L/R pairs.
        # Even-indexed targets (0, 2, 4 …) receive outport 0 (L channel).
        # Odd-indexed targets  (1, 3, 5 …) receive outport 1 (R channel)
        #   or outport 0 again when the player is mono.
        # This covers 1, 2 or any number of outputs uniformly.
        for i, mixer_input in enumerate(target_inputs):
            if i % 2 == 0:
                Logger.debug(f"L → {mixer_input}")
                self.conn_man.connect_by_name(channel_0_output, mixer_input)
            else:
                if is_stereo:
                    Logger.debug(f"R → {mixer_input}")
                    self.conn_man.connect_by_name(
                        channel_1_output, mixer_input
                    )
                else:
                    Logger.debug(f"Mono → {mixer_input}")
                    self.conn_man.connect_by_name(
                        channel_0_output, mixer_input
                    )

    def player_connections_correct(
        self,
        player_name: str,
        player_output_prefix: str = "outport",
        selected_outputs: list = None,
    ) -> bool:
        """
        Verify the player's outputs are wired exactly as
        connect_player_to_outputs would wire them.

        Mirrors the routing in connect_player_to_outputs: same output_to_input
        mapping (built from audio_outputs), same alternating L/R fan-out walk,
        same mono branch (outport 0 → both pair members when channel_1 absent).

        Returns False if any expected edge is missing, points elsewhere, or if
        outport 0 itself does not exist (subprocess gone). Caller decides
        whether to repair via connect_player_to_outputs or abort the cue.
        """
        if not selected_outputs:
            selected_outputs = ["system:playback_1", "system:playback_2"]

        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"

        if not self.conn_man.port_exists(channel_0_output):
            return False

        is_stereo = self.conn_man.port_exists(channel_1_output)

        output_to_input = {
            name: f"{self.client_name}:input_{i+1}"
            for i, name in enumerate(self.audio_outputs)
        }

        target_inputs = []
        for output in selected_outputs:
            if output in output_to_input:
                mixer_input = output_to_input[output]
                if self.conn_man.port_exists(mixer_input):
                    target_inputs.append(mixer_input)

        if not target_inputs:
            return False

        for i, mixer_input in enumerate(target_inputs):
            if i % 2 == 0 or not is_stereo:
                expected_src = channel_0_output
            else:
                expected_src = channel_1_output
            if not self.conn_man.is_connected(expected_src, mixer_input):
                return False

        return True

    @logged
    def disconnect_player(
        self, player_name: str, player_output_prefix: str = "outport"
    ):
        """Disconnect a player's outputs from the mixer.

        Must be called BEFORE the player's JACK client is destroyed (i.e.
        before
        sending /quit), otherwise JACK receives disconnect requests for ports
        that no longer exist, which can corrupt its shared memory registry.

        Args:
            player_name: Name of the player JACK client
            player_output_prefix: Prefix for player's output ports
        """
        channel_0_output = f"{player_name}:{player_output_prefix} 0"
        channel_1_output = f"{player_name}:{player_output_prefix} 1"

        for port_name in (channel_0_output, channel_1_output):
            if not self.conn_man.port_exists(port_name):
                continue
            connections = self.conn_man.get_connections(port_name)
            for connection in connections:
                Logger.debug(f"Disconnecting {port_name} from {connection}")
                self.conn_man.disconnect_by_name(port_name, connection)


def build_mixer_osc_endpoints(client_name: str, channel_number: int) -> dict:
    """Build OSC endpoint configuration for audio mixer.

    Creates OSC addresses in the format expected by jack-volume
    (audiomixer_routes branch):
    /audiomixer/{client_name}/master
    /audiomixer/{client_name}/0
    /audiomixer/{client_name}/1
    etc.

    Args:
        client_name: Name of the mixer client instance (JACK client name)
        channel_number: Number of audio channels in the mixer

    Returns:
        Dictionary of OSC endpoints with their configuration
    """
    endpoints = {}
    base_path = f"/audiomixer/{client_name}"

    # Master volume control
    endpoints[f"{base_path}/master"] = [ValueType.Float, None, 1.0]

    # Individual channel volume controls
    for i in range(channel_number):
        endpoints[f"{base_path}/{i}"] = [ValueType.Float, None, 1.0]

    return endpoints


class MixerClient(PlayerClient):
    """OSC Client for controlling the AudioMixer via jack-volume.

    Provides methods to control volume for individual channels and master
    volume.
    Uses OSC addresses: /audiomixer/<instance>/<channel>
    where channel can be 'master' or '0', '1', '2', etc.
    """

    def __init__(self, player_port: int, channel_number: int, mixer_id: str):
        """Initialize the MixerClient.

        Args:
            player_port: OSC port where jack-volume is listening
            channel_number: Number of audio channels in the mixer
            mixer_id: Unique identifier for this mixer
        """
        self.client_name = get_mixer_client_name(mixer_id)
        self.channel_number = channel_number

        # Build OSC endpoint configuration for jack-volume
        endpoints = build_mixer_osc_endpoints(self.client_name, channel_number)

        super().__init__(
            player_port=player_port,
            endpoints=endpoints,
            name=f"mixer-{mixer_id}",
        )

    @logged
    def set_master_volume(self, gain: float):
        """Set the master volume gain.

        Args:
            gain: Volume gain (0.0 to 1.0)
        """
        if not 0.0 <= gain <= 1.0:
            Logger.error(
                f"Invalid gain value: {gain}. Must be between 0.0 and 1.0"
            )
            return

        path = f"/audiomixer/{self.client_name}/master"
        Logger.debug(f"Setting master volume to {gain}")
        self.set_value(path, gain)

    @logged
    def set_channel_volume(self, channel: int, gain: float):
        """Set volume for a specific channel.

        Args:
            channel: Channel number (0-indexed)
            gain: Volume gain (0.0 to 1.0)
        """
        if not 0.0 <= gain <= 1.0:
            Logger.error(
                f"Invalid gain value: {gain}. Must be between 0.0 and 1.0"
            )
            return

        if channel >= self.channel_number:
            Logger.error(
                f"Invalid channel: {channel}. Max: {self.channel_number - 1}"
            )
            return

        path = f"/audiomixer/{self.client_name}/{channel}"
        Logger.debug(f"Setting channel {channel} volume to {gain}")
        self.set_value(path, gain)

    @logged
    def set_all_channels_volume(self, gain: float):
        """Set volume for all channels (excluding master).

        Args:
            gain: Volume gain (0.0 to 1.0)
        """
        for i in range(self.channel_number):
            self.set_channel_volume(i, gain)

    @logged
    def reset_volumes(self):
        """Reset all volumes to maximum (1.0).

        Call this when loading a project or starting playback to ensure
        consistent volume levels.
        """
        Logger.info("Resetting mixer volumes to default (1.0)")
        self.set_master_volume(1.0)
        self.set_all_channels_volume(1.0)

    @logged
    def mute_channel(self, channel: int):
        """Mute a specific channel by setting its volume to 0.0.

        Args:
            channel: Channel number (0-indexed)
        """
        self.set_channel_volume(channel, 0.0)

    @logged
    def unmute_channel(self, channel: int, gain: float = 1.0):
        """Unmute a specific channel by setting its volume.

        Args:
            channel: Channel number (0-indexed)
            gain: Volume gain to restore (0.0 to 1.0), defaults to 1.0
        """
        self.set_channel_volume(channel, gain)

    @logged
    def mute_master(self):
        """Mute master volume."""
        self.set_master_volume(0.0)

    @logged
    def unmute_master(self, gain: float = 1.0):
        """Unmute master volume.

        Args:
            gain: Volume gain to restore (0.0 to 1.0), defaults to 1.0
        """
        self.set_master_volume(gain)

    @logged
    def add_to_oscquery_server(self, oscquery_server):
        """Add this mixer's OSC routes to a local OSCQuery server.

        This allows the mixer controls to be visible and controllable
        through the OSCQuery server interface.

        Args:
            oscquery_server: OssiaServer instance to add endpoints to
        """
        Logger.info(f"Adding mixer {self.client_name} to OSCQuery server")

        # Get endpoints from this client
        endpoints = self.get_endpoints()
        Logger.debug(f"Mixer endpoints: {list(endpoints.keys())}")

        # Create callback that forwards values from server to this client
        def server_to_client_callback(value):
            """Forward OSC values from server to mixer client."""
            Logger.debug(f"Forwarding value to mixer: {value}")
            # The value will be automatically sent to jack-volume via the OSC
            # client

        # Add callback to all endpoints
        endpoints_with_callbacks = add_callback_to_all(
            endpoints, server_to_client_callback
        )

        # Add endpoints to the OSCQuery server
        oscquery_server.add_endpoints(endpoints_with_callbacks)

        Logger.info(
            f"Mixer {self.client_name} added to OSCQuery server with"
            f"{len(endpoints)} endpoints"
        )


@logged
def start_audio_mixer(
    audio_outputs: list,
    port: int,
    mixer_id: str,
    path: str = None,
    args: str | None = None,
    timeout: float = 5.0,
) -> tuple[AudioMixer, MixerClient]:
    """Start an audio mixer and its OSC client.

    This function creates and starts a jack-volume mixer process and
    sets up an OSC client to control it.

    Args:
        audio_outputs: List of audio output configurations
        port: OSC port for jack-volume communication
        mixer_id: Unique identifier for this mixer
        path: Optional path to jack-volume binary
        args: Additional arguments for jack-volume
        timeout: Maximum time to wait for mixer to start (seconds)

    Returns:
        Tuple containing the AudioMixer and MixerClient instances

    Raises:
        RuntimeError: If mixer fails to start within timeout or thread dies
    """
    # Create the mixer
    mixer = AudioMixer(
        audio_outputs=audio_outputs,
        port=port,
        mixer_id=mixer_id,
        path=path,
        args=args,
    )

    # Start with timeout handling
    mixer.start(timeout=timeout)

    # Wait for jack-volume to fully initialize before connecting
    sleep(2)

    # Connect JACK ports
    mixer.connect_to_jack()

    # Create OSC client for controlling the mixer
    client = MixerClient(
        player_port=port, channel_number=len(audio_outputs), mixer_id=mixer_id
    )

    Logger.info(f"Audio mixer {mixer_id} started on port {port}")
    return mixer, client


### Helper functions ###
def get_mixer_client_name(mixer_id: str) -> str:
    """Get the client name for the mixer.

    Args:
        mixer_id: Unique identifier for this mixer

    Returns:
        Client name for the mixer
    """
    return f"{mixer_id}_mixer"
