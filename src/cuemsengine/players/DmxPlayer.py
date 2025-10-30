from cuemsutils.log import logged
from time import sleep

from .Player import Player
from ..osc.OssiaClient import PlayerClient
from ..osc.endpoints import OSC_DMXPLAYER_CONF

class DmxPlayer(Player):
    def __init__(self, port, path, args):
        super().__init__()
        self.port = port
        self.stdout = None
        self.stderr = None
        # self.card_id = card_id
        self.path = path
        self.args = args
    @logged
    def run(self):
        """Call dmxplayer-cuems in a subprocess"""
        process_call_list = [self.path]
        if self.args is not None:
            for arg in self.args.split():
                process_call_list.append(arg)
        process_call_list.extend(['--port', str(self.port)])
        self.call_subprocess(process_call_list)

class DmxClient(PlayerClient):
    def __init__(self, player_port: int, name: str = "dmxplayer"):
        super().__init__(
            player_port = player_port,
            endpoints = OSC_DMXPLAYER_CONF,
            name = name
        )
## TODO: Implment DmxPlayer as a server
