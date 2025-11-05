from cuemsutils.log import Logger, logged
from time import sleep
from pyossia import ossia

from .Player import Player
from ..osc.OssiaClient import PlayerClient
from ..osc.endpoints import OSC_DMXPLAYER_CONF

class DmxPlayer(Player):
    """DMX player process wrapper.
    
    Manages a single dmxplayer-cuems process per node and exposes OSC control.
    """

    def __init__(self, port, node_uuid, path=None, args: str | None = None):
        """Initialize the DmxPlayer.
        
        Args:
            port: OSC port for dmxplayer communication
            node_uuid: Unique identifier for this player node
            path: Path to dmxplayer-cuems binary
        """
        super().__init__()
        self.node_uuid = node_uuid
        self.port = port
        self.path = path
        self.client_name = f'{self.node_uuid}_dmxplayer'
        self.args = args
        self.stdout = None
        self.stderr = None
        
        # Start the player process
        self.start()

    @logged
    def run(self):
        """Call dmxplayer-cuems in a subprocess"""
        process_call_list = [self.path]
        if self.args:
            for arg in self.args.split():
                process_call_list.append(arg)
        process_call_list.extend(['--port', str(self.port)])
        process_call_list.extend(['--uuid', str(self.node_uuid)])
        Logger.info(f"Starting dmxplayer with: {process_call_list}")
        self.call_subprocess(process_call_list)

class DmxClient(PlayerClient):
    def __init__(self, player_port: int, client_name: str, host: str = "127.0.0.1"):
        """Initialize the DMX client.
        
        Args:
            player_port: OSC port for communication
            client_name: Name for this client instance
            host: Host IP address of the dmxplayer
        """
        super().__init__(
            player_port = player_port,
            endpoints = OSC_DMXPLAYER_CONF,
            name = client_name
        )
        self.host = host
        self.player_port = player_port
        
        # Create bundle parameters for DMX scene messages
        # These are ephemeral - just for bundle construction, not registered on device
        self._create_bundle_parameters()
    
    def _create_bundle_parameters(self):
        """Create parameters on the OSC device for bundle construction.
        
        These parameters are created on the client's OSC device and used for
        building OSC bundles. They represent the OSC endpoints that the
        dmxplayer expects to receive.
        """
        # Create parameters on this client's device
        root = self.device.root_node
        
        # Create parameters matching dmxplayer's expected OSC endpoints
        self._frame_param = root.add_node("/frame").create_parameter(ossia.ValueType.List)
        self._mtc_time_param = root.add_node("/mtc_time").create_parameter(ossia.ValueType.String)
        self._start_offset_param = root.add_node("/start_offset").create_parameter(ossia.ValueType.Int)
        self._fade_time_param = root.add_node("/fade_time").create_parameter(ossia.ValueType.Float)
        
        Logger.debug(f"DMX bundle parameters created on device for {self.name}")
    
    @logged
    def send_dmx_scene(
        self,
        universe_frames: dict[int, dict[int, int]],
        mtc_time: str | int,
        fade_time: float = 0.0
    ) -> None:
        """Send a complete DMX scene as an OSC bundle using pyossia.
        
        Constructs an OSC bundle containing:
        - /frame messages: universe_id followed by channel/value pairs
        - /mtc_time or /start_offset: timing information
        - /fade_time: fade duration
        
        Args:
            universe_frames: Dictionary mapping universe_id -> {channel: value}
                            Example: {1: {0: 255, 1: 128, 2: 64}}
            mtc_time: MTC start time as string ("now", "+H:M:S", "H:M:S") or milliseconds (int)
            fade_time: Fade duration in seconds (float)
        
        Example:
            client.send_dmx_scene(
                universe_frames={1: {0: 255, 1: 255, 2: 255}},
                mtc_time="now",
                fade_time=2.0
            )
        """
        try:
            bundle = ossia.Bundle()
            
            # Add frame data for each universe
            for universe_id, channels in universe_frames.items():
                if channels:  # Only add if there are channels to set
                    # Build frame list: [universe_id, ch0, val0, ch1, val1, ...]
                    frame_data = [int(universe_id)]
                    for channel, value in sorted(channels.items()):
                        frame_data.append(int(channel))
                        frame_data.append(int(value))
                    
                    bundle.append(self._frame_param, frame_data)
                    Logger.debug(f"Added frame for universe {universe_id} with {len(channels)} channels")
            
            # Add MTC time
            if isinstance(mtc_time, int):
                # Integer (milliseconds) - use /start_offset
                bundle.append(self._start_offset_param, int(mtc_time))
                Logger.debug(f"Added start_offset: {mtc_time}ms")
            else:
                # String format: "now", "+H:M:S", or "H:M:S"
                bundle.append(self._mtc_time_param, str(mtc_time))
                Logger.debug(f"Added mtc_time: {mtc_time}")
            
            # Add fade time
            bundle.append(self._fade_time_param, float(fade_time))
            Logger.debug(f"Added fade_time: {fade_time}s")
            
            # Push the bundle via the OSC device
            self.device.push_bundle(bundle)
            
            Logger.info(
                f"Sent DMX scene bundle: {len(universe_frames)} universe(s), "
                f"mtc={mtc_time}, fade={fade_time}s"
            )
            
        except Exception as e:
            Logger.error(f"Error sending DMX scene bundle: {e}")
            Logger.exception(e)
            raise

@logged
def start_dmx_player(
    port: int,
    node_uuid: str,
    path: str,
    args: str | None = None
) -> tuple[DmxPlayer, DmxClient]:
    """Start a DMX player and its OSC client.
    
    This function creates and starts a dmxplayer-cuems process and
    sets up an OSC client to control it.
    
    Args:
        port: OSC port for dmxplayer communication
        node_uuid: Unique identifier for this player node
        path: Path to dmxplayer-cuems binary
    
    Returns:
        Tuple containing the DmxPlayer and DmxClient instances
    """
    # Create and start the player
    player = DmxPlayer(
        port=port,
        node_uuid=node_uuid,
        path=path,
        args=args
    )
    
    # Wait for player process to start
    while player.pid is None:
        sleep(0.001)
    
    # Create OSC client for controlling the player
    client = DmxClient(
        player_port=port,
        client_name=f'{node_uuid}_dmxplayer'
    )
    
    Logger.info(f"DMX player started: {node_uuid}_dmxplayer on port {port}")
    return player, client
