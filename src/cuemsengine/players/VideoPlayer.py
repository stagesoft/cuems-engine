from cuemsutils.log import logged, Logger

from .Player import Player
from ..osc.OssiaClient import PlayerClient
from ..osc.endpoints import OSC_VIDEOPLAYER_CONF

class VideoPlayer(Player):
    """Video player systemd service wrapper.

    This class restarts the videocomposer service.
    
    IMPORTANT: This class should not be used, since videocomposer is a systemd service and not a subprocess.
    """
    def __init__(self):
        super().__init__()
        Logger.warning('Restarting the videocomposer service. Use VideoClient only to control videocomposer.')

    @logged
    def run(self):
        # Calling videocomposer in a subprocess
        process_call_list = [
            'systemctl',
            'restart',
            'videocomposer.service'
        ]
        Logger.info(f'Restarting videocomposer service: {process_call_list}')
        self.call_subprocess(process_call_list)

class VideoClient(PlayerClient):
    def __init__(self, player_port: int, name: str = "videocomposer"):
        super().__init__(
            player_port = player_port,
            name = name,
            endpoints = OSC_VIDEOPLAYER_CONF
        )
