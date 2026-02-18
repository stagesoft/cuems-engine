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

class VideoOutput:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name')
        self.x = kwargs.get('x')
        self.y = kwargs.get('y')
        self.width = kwargs.get('width')
        self.height = kwargs.get('height')
        self.resolution = kwargs.get('resolution', "native")

    def apply_config(self, video_client: VideoClient) -> None:
        """Applies the configuration to the video client."""
        video_client.set_value('/videocomposer/display/resolution_mode', self.resolution)
        self.set_region(video_client)

    def set_region(self, video_client: VideoClient) -> None:
        """Sets the region of the video output."""
        if any([self.x, self.y, self.width, self.height]) is None:
            return
        
        video_client.set_value('/videocomposer/display/region', [self.name, self.x, self.y, self.width, self.height])
