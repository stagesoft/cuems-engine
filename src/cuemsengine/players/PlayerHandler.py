from cuemsutils.log import Logger
from cuemsutils.cues import AudioCue, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from functools import partial
from threading import Lock
from time import sleep


from .AudioPlayer import AudioPlayer, start_audio_output
from .DmxPlayer import start_dmx_output
from .VideoPlayer import VideoPlayer, VideoClient, start_video_output

from .Player import Player
from ..tools.PortHandler import PORT_HANDLER

class PlayerHandler:
    """
    This class is responsible for handling and generating player objects.

    It is a singleton class, so it will
    only be instantiated once.

    Holds a list of armed cues and provides methods to use them.
    """
    _instace = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern: Ensure only one instance is created"""
        if not cls._instance:
            cls._instance = super(PlayerHandler, cls).__new__(cls)

            cls._instance._cue_players = {}
            cls._instance._video_players = {}
            cls._instance._front_video_player = None
            cls._instance._audio_output_generator = None
            cls._instance._dmx_output_generator = None
            cls._instance._lock = Lock()
        return cls._instance

    # ---------------------------
    # Players List Management
    # ---------------------------

    def store_cue_player(self, cue: Cue, player: Player):
        """Stores a cue player"""
        with self._lock:
            self._cue_players[cue.id] = player

    def get_cue_player(self, cue: Cue) -> Player:
        """Gets a cue player"""
        with self._lock:
            return self._cue_players[cue]

    def remove_cue_player(self, cue: Cue):
        """Removes a cue player"""
        with self._lock:
            player = self._cue_players.pop(cue)
            cue._osc = None
        if isinstance(player, AudioPlayer):
            player.kill()
            PORT_HANDLER.free_port(player.port)
            player.join()
            player = None


    # ---------------------------
    # Audio Player Management
    # ---------------------------

    def set_audio_output_generator(self, path: str, args: str):
        """Sets the audio player generator"""
        Logger.info(f'Setting audio output generator to {path} {args}')
        self._audio_output_generator = partial(start_audio_output, path, args)

    def new_audio_output(self, cue: AudioCue) -> None:
        """Creates a new audio output for the given cue

        The player is stored in the player handler and the osc client is assigned to the cue.
        
        Args:
            cue: The cue to create the audio output for

        Returns:
            None
        """
        Logger.debug(f'Creating new audio output for cue {cue.id}')
        if self._audio_output_generator is None:
            raise ValueError("Audio output generator not set")
        ports = PORT_HANDLER.assign_ports(['audio_output'], cue)
        player, client = self._audio_output_generator(
            ports['audio_output'],
            cue.media['file_name'],
            str(cue.id)
        )
        cue._osc = client
        self.store_cue_player(cue, player)

    # def set_dmx_output_generator(cls, path: str, args: str):
    #     """Sets the dmx player generator"""
    #     cls._dmx_output_generator = partial(start_dmx_output, path, args)

    # def new_dmx_output(cls, cue: DmxCue) -> None:
    #     """Creates a new audio output for the given cue

    #     The player is stored in the player handler and the osc client is assigned to the cue.
        
    #     Args:
    #         cue: The cue to create the dmx output for

    #     Returns:
    #         None
    #     """
    #     if cls._dmx_output_generator is None:
    #         raise ValueError("Audio output generator not set")
    #     ports = PORT_HANDLER.assign_ports(['dmx_output'], cue)
    #     player, client = cls._dmx_output_generator(
    #         ports['dmx_output'],
    #         cue.media['file_name']
    #     )
    #     cue._osc = client
    #     cls.store_cue_player(cue, player)


    # ---------------------------
    # Video Player Management
    # ---------------------------

    def set_video_player(self, cue: VideoCue):
        """Sets the video player for the given cue"""
        Logger.debug(f'Setting video player for cue {cue.id}')
        if not self._front_video_player:
            # Initialize the front video player
            player = self.get_active_videoplayer(get_cue_output_name(cue))
            self._front_video_player = 1
        else:
            player = self.get_inactive_videoplayer(get_cue_output_name(cue))
        
        cue._osc = player['osc']
        self.store_cue_player(cue, player['player'])

    def get_video_players(self):
        """Returns the video players."""
        with self._lock:
            out = []
            for players in self._video_players.values():
                out.extend(players)
            return out

    def reset_video_players(self):
        """Resets the video players."""
        with self._lock:
            self._video_players = {}

    def start_video_outputs(
        self,
        output_names: list[str],
        output_ports: list[dict[str, int]],
        video_player_path: str,
        video_player_args: str,
    ):
        """Starts the video players."""
        Logger.info(f'Starting video outputs for {output_names} ')
        for index, output_name in enumerate(output_names):
            with self._lock:
                if output_name in self._video_players:
                    continue
                self._video_players[output_name] = []

            new_ports = output_ports[index]

            for i in range(2):
                player = dict()
                player['route'] = f'/players/videoplayer-{index}_{i}'
                player['port'] = new_ports[f'video_player_{index}_{i}']

                try:
                    player['player'] = VideoPlayer(
                        player['port'],
                        output_name,
                        video_player_path,
                        video_player_args,
                        '',
                    )
                    player['player'].start()
                    while player['player'].pid is None:
                        sleep(0.001)
                    player['pid'] = player['player'].pid
                    player['osc'] = VideoClient(player['port'], player['route'])
                except Exception as e:
                    raise e

                with self._lock:
                    self._video_players[output_name].append(player)

    def get_active_videoplayer(self, output_name: str):
        """Find the active player for a given output."""
        with self._lock:
            if output_name in self._video_players:
                return self._video_players[output_name][-1]
            return None

    def get_inactive_videoplayer(self, output_name: str):
        """Find the inactive player for a given output."""
        with self._lock:
            if output_name in self._video_players:
                return self._video_players[output_name][0]
            return None

    def toggle_videoplayer(self, output_name: str):
        """Alternates between active and inactive players."""
        with self._lock:
            to_back = self.get_active_videoplayer(output_name)
            to_front = self.get_inactive_videoplayer(output_name)

            if not to_back or not to_front:
                return

            to_back['osc'].set_value('/jadeo/ontop', 0)
            to_front['osc'].set_value('/jadeo/ontop', 1)

            if output_name in self._video_players:
                self._video_players[output_name] = self._video_players[output_name][::-1]


# ---------------------------
# Singleton
# ---------------------------

PLAYER_HANDLER = PlayerHandler()




# ---------------------------
# Helper functions
# ---------------------------

def get_cue_output_name(cue: Cue) -> str:
    """Get the output name for a given cue."""
    outputs_key = next(iter(cue.outputs.keys()))
    return cue.outputs[outputs_key]['output_name']
