from cuemsutils.log import logged, Logger
from time import sleep

from .Player import Player
from ..osc.OssiaClient import PlayerClient
from ..osc.endpoints import OSC_AUDIOPLAYER_CONF

class AudioPlayer(Player):
    def __init__(self, port, path, args, media, uuid=None):
        super().__init__()
        self.port = port
        self.path = path
        self.args = args
        self.media = media
        self.uuid = uuid

    @logged
    def run(self):
        # Calling audioplayer-cuems in a subprocess
        process_call_list = [self.path]
        if self.args:
            Logger.debug(f"Running audio player with args: {self.args}")
            for arg in self.args.split():
                process_call_list.append(arg)
        process_call_list.extend(['--port', str(self.port)])
        if self.uuid != None:
            uuid_slug = ''.join(self.uuid.split('-'))
            process_call_list.extend(['--uuid', uuid_slug])
        process_call_list.append(self.media)
        
        self.call_subprocess(process_call_list)

class AudioClient(PlayerClient):
    def __init__(self, player_port: int, name: str = "audioplayer"):
        super().__init__(
            player_port = player_port,
            endpoints = OSC_AUDIOPLAYER_CONF,
            name = name
        )

def start_audio_output(
    port: int,
    path: str,
    args: list[str],
    media: str,
    uuid: str,
    timeout: float = 5.0
) -> tuple[AudioPlayer, AudioClient]:
    """Starts an audio output
    
    Args:
        port: The port to use for the audio output
        path: The path to the audio player executable
        args: The arguments to pass to the audio player
        media: The media to play
        uuid: The uuid of the audio output
        timeout: Maximum time to wait for player to start (seconds)

    Returns:
        A tuple containing the audio player and client
        
    Raises:
        RuntimeError: If player fails to start within timeout or thread dies
    """
    player = AudioPlayer(
        port = port,
        path = path,
        args = args,
        media = media,
        uuid = uuid
    )
    player.start(timeout=timeout)

    client = AudioClient(
        player_port = port,
        name = f'audioplayer-{uuid}'
    )

    return player, client
