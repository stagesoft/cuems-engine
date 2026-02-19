from cuemsutils.log import Logger, logged
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

        # Bundle parameters for building OSC bundles (pyossia now sends proper #bundle wire format)
        self._create_bundle_parameters()
        Logger.debug(f"DMX bundle parameters created for {self.name}")

    def _create_bundle_parameters(self) -> None:
        """Create parameters on the OSC device for bundle construction."""
        root = self.device.root_node
        self._frame_param = root.add_node("/frame").create_parameter(ossia.ValueType.List)
        self._mtc_time_param = root.add_node("/mtc_time").create_parameter(ossia.ValueType.String)
        self._start_offset_param = root.add_node("/start_offset").create_parameter(ossia.ValueType.Int)
        self._fade_time_param = root.add_node("/fade_time").create_parameter(ossia.ValueType.Float)
        self._mtcfollow_param = root.add_node("/mtcfollow").create_parameter(ossia.ValueType.Int)

    def enable_mtcfollow(self) -> None:
        """Re-enable MTC following in the DMX player.

        Called before sending a new cue so the dmxplayer resumes tracking
        timecode. Must be called after send_blackout() which leaves
        mtcfollow disabled intentionally.
        """
        self._mtcfollow_param.push_value(1)
        Logger.debug("DMX mtcfollow re-enabled for playback")

    @logged
    def send_dmx_scene(
        self,
        universe_frames: dict[int, dict[int, int]],
        mtc_time: str | int,
        fade_time: float = 0.0
    ) -> None:
        """Send a complete DMX scene as an OSC bundle via pyossia.
        
        Constructs an OSC bundle containing:
        - /frame messages: universe_id followed by channel/value pairs
        - /mtc_time or /start_offset: timing information
        - /fade_time: fade duration
        """
        try:
            bundle = ossia.Bundle()

            for universe_id, channels in universe_frames.items():
                if channels:
                    frame_data = [int(universe_id)]
                    for channel, value in sorted(channels.items()):
                        frame_data.append(int(channel))
                        frame_data.append(int(value))
                    bundle.append(self._frame_param, frame_data)
                    Logger.debug(f"Added frame for universe {universe_id} with {len(channels)} channels")

            if isinstance(mtc_time, int):
                bundle.append(self._start_offset_param, int(mtc_time))
                Logger.debug(f"Added start_offset: {mtc_time}ms")
            else:
                bundle.append(self._mtc_time_param, str(mtc_time))
                Logger.debug(f"Added mtc_time: {mtc_time}")

            bundle.append(self._fade_time_param, float(fade_time))
            Logger.debug(f"Added fade_time: {fade_time}s")

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
    def send_blackout(self, universe_ids: int | tuple[int, ...] = (0, 1)) -> None:
        """Send a blackout (all channels to 0) directly to OLA.

        Bypasses the dmxplayer's scene mechanism entirely by calling
        ola_set_dmx for each universe. This avoids race conditions between
        the OSC receiver thread and the OLA timer thread in dmxplayer-cuems
        (the scene's mtcStart can capture a stale playHead value when MTC
        has just stopped).

        Args:
            universe_ids: DMX universe(s) to black out.
        """
        import subprocess

        if isinstance(universe_ids, int):
            universe_ids = (universe_ids,)

        zeros = ','.join(['0'] * 512)
        for uid in universe_ids:
            try:
                subprocess.run(
                    ['ola_set_dmx', '-u', str(uid), '-d', zeros],
                    timeout=2, check=True,
                    capture_output=True,
                )
            except Exception as e:
                Logger.error(f"Blackout ola_set_dmx failed for universe {uid}: {e}")

        Logger.info(f"Sent DMX blackout via ola_set_dmx for universe(s) {universe_ids}")

@logged
def start_dmx_player(
    port: int,
    node_uuid: str,
    path: str,
    args: str | None = None,
    timeout: float = 5.0
) -> tuple[DmxPlayer, DmxClient]:
    """Start a DMX player and its OSC client.
    
    This function creates and starts a dmxplayer-cuems process and
    sets up an OSC client to control it.
    
    Args:
        port: OSC port for dmxplayer communication
        node_uuid: Unique identifier for this player node
        path: Path to dmxplayer-cuems binary
        args: Additional arguments for dmxplayer-cuems
        timeout: Maximum time to wait for player to start (seconds)
    
    Returns:
        Tuple containing the DmxPlayer and DmxClient instances
        
    Raises:
        RuntimeError: If player fails to start within timeout or thread dies
    """
    # Create and start the player with timeout handling
    player = DmxPlayer(
        port=port,
        node_uuid=node_uuid,
        path=path,
        args=args
    )
    player.start(timeout=timeout)
    
    # Create OSC client for controlling the player
    client = DmxClient(
        player_port=port,
        client_name=f'{node_uuid}_dmxplayer'
    )
    
    Logger.info(f"DMX player started: {node_uuid}_dmxplayer on port {port}")
    return player, client
