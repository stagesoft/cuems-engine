from cuemsutils.log import logged, Logger

from .Player import Player
from ..osc.OssiaClient import PlayerClient
from ..osc.endpoints import OSC_VIDEOPLAYER_CONF, OSC_VIDEOPLAYER_LAYER_CONF

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

    def create_layer_endpoints(self, layer_id: str) -> None:
        """Register per-layer OSC endpoints for the given layer_id."""
        layer_endpoints = {
            k.format(layer_id): v
            for k, v in OSC_VIDEOPLAYER_LAYER_CONF.items()
        }
        self.create_endpoints(layer_endpoints)

    def remove_layer_endpoints(self, layer_id: str) -> None:
        """Remove per-layer OSC endpoints for the given layer_id."""
        for template_path in OSC_VIDEOPLAYER_LAYER_CONF:
            path = template_path.format(layer_id)
            try:
                self.remove_node(path)
            except Exception as e:
                Logger.debug(f'Could not remove endpoint {path}: {e}')

class VideoOutput:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name')
        self.mapped_to = kwargs.get('mapped_to', self.name)
        self.x = kwargs.get('x', 0)
        self.y = kwargs.get('y', 0)
        self.width = kwargs.get('width', 1920)
        self.height = kwargs.get('height', 1080)
        self.resolution = kwargs.get('resolution', "1080p")
        self.canvas_region = kwargs.get('canvas_region', {
            'x': self.x, 'y': self.y,
            'width': self.width, 'height': self.height,
        })
        self.canvas_width = kwargs.get('canvas_width', self.width)
        self.canvas_height = kwargs.get('canvas_height', self.height)

    def get_layer_placement(self) -> tuple[int, int]:
        """Returns (x, y) offset from canvas center to this output's center.

        The videocomposer uses center-relative coordinates: (0, 0) = canvas center.
        """
        output_cx = self.canvas_region['x'] + self.canvas_region['width'] // 2
        output_cy = self.canvas_region['y'] + self.canvas_region['height'] // 2
        canvas_cx = self.canvas_width // 2
        canvas_cy = self.canvas_height // 2
        return (output_cx - canvas_cx, output_cy - canvas_cy)

    def apply_config(self, video_client: VideoClient) -> None:
        """No-op: videocomposer reads display config from display.conf at startup.

        cuems-generate-display-conf (ExecStartPre) generates display.conf from
        default_mappings.xml — the single source of truth for connector→region
        mappings.  The engine must NOT send /display/region or resolution_mode
        because that caused the MultiOutputRenderer to reconfigure (and sometimes
        switch to native 4K resolution, corrupting the canvas layout).
        """
        Logger.info(f'VideoOutput {self.mapped_to}: region ({self.x},{self.y} {self.width}x{self.height})')
