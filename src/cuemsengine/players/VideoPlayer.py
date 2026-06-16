# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
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
        The renderer negates Y (glTranslatef(x, -y, 0)) because OpenGL Y points
        up while screen Y points down.  The canvas FBO also has Y=0 at the
        bottom, so we negate Y here to compensate — positive Y in the returned
        value means "below canvas center" in screen coords, which maps to the
        correct FBO position after the renderer's negation.
        """
        output_cx = self.canvas_region['x'] + self.canvas_region['width'] // 2
        output_cy = self.canvas_region['y'] + self.canvas_region['height'] // 2
        canvas_cx = self.canvas_width // 2
        canvas_cy = self.canvas_height // 2
        return (output_cx - canvas_cx, canvas_cy - output_cy)

    def get_layer_scale(self) -> tuple[float, float]:
        """Returns (scaleX, scaleY) to fit the video layer within this output's region.

        The videocomposer renders layers at full canvas size with letterboxing.
        For typical setups (ultra-wide canvas, 16:9 video), the video fills the
        canvas height and is letterboxed horizontally.  The height ratio therefore
        determines the correct uniform scale to fit the output region.
        """
        s = self.canvas_region['height'] / self.canvas_height if self.canvas_height else 1.0
        return (s, s)

    def apply_config(self, video_client: VideoClient) -> None:
        """No-op: videocomposer reads display config from display.conf at startup.

        /run/cuems/display.conf is the shared contract between engine and
        videocomposer for canvas geometry. cuems-generate-display-conf
        (videocomposer's ExecStartPre) writes it from default_mappings.xml;
        both VC and the engine (via cuemsengine.display_conf.read_display_conf)
        read it independently. The engine must NOT send /display/region or
        resolution_mode here because that caused the MultiOutputRenderer to
        reconfigure (and sometimes switch to native 4K resolution, corrupting
        the canvas layout). Phase 2 will gate runtime tweaks behind explicit
        edit-mode OSC handlers.
        """
        Logger.info(f'VideoOutput {self.mapped_to}: region ({self.x},{self.y} {self.width}x{self.height})')
