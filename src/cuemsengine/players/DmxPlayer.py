from cuemsutils.log import Logger, logged
from time import sleep

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
    def __init__(self, player_port: int, client_name: str):
        """Initialize the DMX client.
        
        Args:
            player_port: OSC port for communication
            client_name: Name for this client instance
        """
        super().__init__(
            player_port = player_port,
            endpoints = OSC_DMXPLAYER_CONF,
            name = client_name
        )

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
