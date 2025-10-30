from .JackConnectionManager import JackConnectionManager
from .Player import Player
from ..osc.OssiaClient import PlayerClient
from ..osc.helpers import add_callback_to_all
from ..tools.PortHandler import PORT_HANDLER
from pyossia import ValueType
from cuemsutils.log import logged, Logger
from functools import partial
from time import sleep

JACK_VOLUME_PATH = '/usr/local/bin/jack-volume'
# usage: jack-volume [-c <jack_client_name>] [-s <jack_server_name>] [-p <osc_port>] [-n <number_of_channels>]

class AudioMixer(Player):
    """JACK audio mixer using jack-volume controlled via OSC.
    
    This class manages a jack-volume process which provides volume control
    for multiple audio channels. It connects to JACK and exposes OSC control.
    
    OSC address format: /audiomixer/<instance>/<channel>
    where channel can be 'master' or '0', '1', '2', etc.
    """

    def __init__(self, audio_outputs, port, node_uuid, path=None, args: str | None = None):
        """Initialize the AudioMixer.
        
        Args:
            audio_outputs: List of audio output configurations
            port: OSC port for jack-volume communication
            node_uuid: Unique identifier for this mixer node
            path: Optional path to jack-volume binary (defaults to JACK_VOLUME_PATH)
        """
        super().__init__()
        self.conn_man = JackConnectionManager()
        self.node_uuid = node_uuid
        self.port = port
        self.ports = self.conn_man.get_ports()
        self.path = path if path else JACK_VOLUME_PATH
        self.channel_number = len(audio_outputs)
        self.audio_outputs = audio_outputs
        self.client_name = f'{self.node_uuid}_mixer'
        self.extra_args = args
        
        # Build command line arguments for jack-volume
        self.args = [
            '-c', self.client_name,
            '-p', str(port),
            '-n', str(self.channel_number)
        ]
        
        # Start the mixer process
        self.start()
        sleep(2)  # wait for jack-volume to start up before connecting to it
        
        # Connect JACK ports
        self.connect_to_jack()

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
    def connect_to_jack(self):
        """Connect mixer outputs to system playback ports."""
        for i in range(self.channel_number):
            output_port = f"{self.client_name}:output_{i+1}"
            playback_port = f"system:playback_{i+1}"
            Logger.debug(f"Connecting {output_port} to {playback_port}")
            self.conn_man.connect_by_name(output_port, playback_port)

    @logged
    def connect_player_to_mixer(self, player_name: str, player_output_prefix: str = 'output', mixer_channel: int = 0):
        """Connect a player's output to a specific mixer input channel.
        
        First disconnects any existing connections from the player's outputs,
        then connects them to the mixer inputs.
        
        Args:
            player_name: Name of the player JACK client to connect
            player_output_prefix: Prefix for player's output ports (e.g., 'output')
            mixer_channel: Mixer input channel number (0-indexed)
        """
        if mixer_channel >= self.channel_number:
            Logger.error(f"Invalid mixer channel: {mixer_channel}. Max: {self.channel_number - 1}")
            return
            
        # Define player output ports (assuming stereo outputs)
        channel_0_output = f"{player_name}:{player_output_prefix}_0"
        channel_1_output = f"{player_name}:{player_output_prefix}_1"
        mixer_input_0 = f"{self.client_name}:input_{mixer_channel * 2 + 1}"
        mixer_input_1 = f"{self.client_name}:input_{mixer_channel * 2 + 2}"
        
        # First, disconnect any existing connections from player outputs
        Logger.debug(f"Disconnecting existing connections from {channel_0_output}")
        Logger.debug(f"Disconnecting existing connections from {channel_1_output}")
        
        # Get existing connections and disconnect them
        channel_0_connections = self.conn_man.get_connections(channel_0_output)
        for connection in channel_0_connections:
            Logger.debug(f"Disconnecting {channel_0_output} from {connection}")
            self.conn_man.disconnect_by_name(channel_0_output, connection)
        
        channel_1_connections = self.conn_man.get_connections(channel_1_output)
        for connection in channel_1_connections:
            Logger.debug(f"Disconnecting {channel_1_output} from {connection}")
            self.conn_man.disconnect_by_name(channel_1_output, connection)
        
        # Now connect to mixer inputs
        Logger.debug(f"Connecting {channel_0_output} to {mixer_input_0}")
        Logger.debug(f"Connecting {channel_1_output} to {mixer_input_1}")
        
        self.conn_man.connect_by_name(channel_0_output, mixer_input_0)
        self.conn_man.connect_by_name(channel_1_output, mixer_input_1)


def build_mixer_osc_endpoints(client_name: str, channel_number: int) -> dict:
    """Build OSC endpoint configuration for audio mixer.
    
    Creates OSC addresses in the format:
    /audiomixer/{instance}/master
    /audiomixer/{instance}/0
    /audiomixer/{instance}/1
    etc.
    
    Args:
        client_name: Name of the mixer client instance
        channel_number: Number of audio channels in the mixer
    
    Returns:
        Dictionary of OSC endpoints with their configuration
    """
    endpoints = {}
    base_path = f'/audiomixer/{client_name}'
    
    # Master volume control
    endpoints[f'{base_path}/master'] = [ValueType.Float, None, 1.0]
    
    # Individual channel volume controls
    for i in range(channel_number):
        endpoints[f'{base_path}/{i}'] = [ValueType.Float, None, 1.0]
    
    return endpoints


class MixerClient(PlayerClient):
    """OSC Client for controlling the AudioMixer via jack-volume.
    
    Provides methods to control volume for individual channels and master volume.
    Uses OSC addresses: /audiomixer/<instance>/<channel>
    where channel can be 'master' or '0', '1', '2', etc.
    """

    def __init__(self, player_port: int, channel_number: int, client_name: str):
        """Initialize the MixerClient.
        
        Args:
            player_port: OSC port where jack-volume is listening
            channel_number: Number of audio channels in the mixer
            client_name: Name of the jack-volume client
        """
        self.client_name = client_name
        self.channel_number = channel_number
        
        # Build OSC endpoint configuration for jack-volume
        endpoints = build_mixer_osc_endpoints(client_name, channel_number)
        
        super().__init__(
            player_port=player_port,
            endpoints=endpoints,
            name=f'mixer-{client_name}'
        )

    @logged
    def set_master_volume(self, gain: float):
        """Set the master volume gain.
        
        Args:
            gain: Volume gain (0.0 to 1.0)
        """
        if not 0.0 <= gain <= 1.0:
            Logger.error(f"Invalid gain value: {gain}. Must be between 0.0 and 1.0")
            return
            
        path = f'/audiomixer/{self.client_name}/master'
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
            Logger.error(f"Invalid gain value: {gain}. Must be between 0.0 and 1.0")
            return
            
        if channel >= self.channel_number:
            Logger.error(f"Invalid channel: {channel}. Max: {self.channel_number - 1}")
            return
            
        path = f'/audiomixer/{self.client_name}/{channel}'
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
            # The value will be automatically sent to jack-volume via the OSC client
        
        # Add callback to all endpoints
        endpoints_with_callbacks = add_callback_to_all(endpoints, server_to_client_callback)
        
        # Add endpoints to the OSCQuery server
        oscquery_server.add_endpoints(endpoints_with_callbacks)
        
        Logger.info(f"Mixer {self.client_name} added to OSCQuery server with {len(endpoints)} endpoints")


@logged
def start_audio_mixer(
    audio_outputs: list,
    port: int,
    node_uuid: str,
    path: str = None,
    args: str | None = None
) -> tuple[AudioMixer, MixerClient]:
    """Start an audio mixer and its OSC client.
    
    This function creates and starts a jack-volume mixer process and
    sets up an OSC client to control it.
    
    Args:
        audio_outputs: List of audio output configurations
        port: OSC port for jack-volume communication
        node_uuid: Unique identifier for this mixer node
        path: Optional path to jack-volume binary
    
    Returns:
        Tuple containing the AudioMixer and MixerClient instances
    """
    # Create and start the mixer
    mixer = AudioMixer(
        audio_outputs=audio_outputs,
        port=port,
        node_uuid=node_uuid,
        path=path,
        args=args
    )
    
    # Wait for mixer process to start
    while mixer.pid is None:
        sleep(0.001)
    
    # Create OSC client for controlling the mixer
    client = MixerClient(
        player_port=port,
        channel_number=len(audio_outputs),
        client_name=f'{node_uuid}_mixer'
    )
    
    Logger.info(f"Audio mixer started: {node_uuid}_mixer on port {port}")
    return mixer, client

