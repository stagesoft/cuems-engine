from cuemsutils.log import Logger
from cuemsutils.cues import AudioCue, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from functools import partial
from threading import Lock
from time import sleep
from typing import Callable

from .AudioPlayer import AudioPlayer, start_audio_output
from .VideoPlayer import VideoPlayer, VideoClient
from .DmxPlayer import DmxPlayer, DmxClient

from .Player import Player
from ..tools.PortHandler import PORT_HANDLER

DEFAULT_MEDIA_FOLDER = '/opt/cuems_library/media/'

class PlayerHandler:
    """
    This class is responsible for handling and generating player objects.

    It is a singleton class, so it will
    only be instantiated once.

    Holds a list of armed cues and provides methods to use them.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern: Ensure only one instance is created"""
        if not cls._instance:
            cls._instance = super(PlayerHandler, cls).__new__(cls)

            cls._instance._audio_output_generator = None
            cls._instance._cue_players = {}
            cls._instance._dmx_output_generator = None
            cls._instance._player_endpoints_generator = None
            cls._instance._front_video_player = None
            cls._instance._video_output_names = []
            cls._instance._lock = Lock()
            cls._instance._media_folder = DEFAULT_MEDIA_FOLDER
            cls._instance._node_uuid = None
            cls._instance._video_players = {}
            cls._instance._dmx_players = {}
        return cls._instance

    # ---------------------------
    # Players List Management
    # ---------------------------

    def store_cue_player(self, cue: Cue, player: Player):
        """Stores a cue player"""
        with self._lock:
            self._cue_players[cue] = player

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
            PORT_HANDLER.remove_ports(cue)
            player.kill()
            player.join()
            player = None


    # ---------------------------
    # Audio Player Management
    # ---------------------------

    def set_audio_output_generator(self, path: str, args: str):
        """Sets the audio player generator"""
        Logger.info(f'Setting audio output generator to {path} {args}')
        self._audio_output_generator = partial(start_audio_output, path=path, args=args)

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
            port=ports['audio_output'],
            media=self.media_path(cue.media['file_name']),
            uuid=str(cue.id)
        )
        cue._osc = client
        self.set_player_endpoints(cue)
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
            player = self.get_active_videoplayer(self.get_cue_output_name(cue))
            self._front_video_player = 1
        else:
            player = self.get_inactive_videoplayer(self.get_cue_output_name(cue))
        
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
                    player['osc'] = VideoClient(
                        player['port'],
                        player['route']
                    )
                    Logger.debug(f"Found videoplayer nodes: {player['osc'].nodes_from_device()}")
                except Exception as e:
                    raise e

                with self._lock:
                    self._video_players[output_name].append(player)
        with self._lock:
            self._video_output_names = output_names

    def get_video_output_names(self, index: int):
        """Returns the video output names."""
        with self._lock:
            return self._video_output_names[index]

    def get_video_output_index(self, output_name: str):
        """Returns the index of a given output name."""
        with self._lock:
            return self._video_output_names.index(output_name)


    def start_dmx_outputs(
        self,
        output_names: list[str],
        output_ports: list[dict[str, int]],
        video_player_path: str,
        video_player_args: str,
    ):
        """Starts the dmx players."""
        Logger.info(f'Starting dmx outputs for {output_names} ')
        for index, output_name in enumerate(output_names):
            with self._lock:
                if output_name in self._dmx_players:
                    continue
                self._dmx_players[output_name] = []

            new_ports = output_ports[index]

            player = dict()
            player['route'] = f'/players/dmxplayer-{index}'
            player['port'] = new_ports[f'dmx_player_{index}']

            try:
                player['player'] = DmxPlayer(
                    player['port'],
                    video_player_path,
                    video_player_args
                )
                player['player'].start()
                while player['player'].pid is None:
                    sleep(0.001)
                player['pid'] = player['player'].pid
                player['osc'] = DmxClient(
                    player['port'],
                    player['route']
                )
            except Exception as e:
                raise e

            with self._lock:
                self._dmx_players[output_name].append(player)




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
    # Helper functions
    # ---------------------------

    def set_player_endpoints_generator(self, func: Callable, *args, **kwargs):
        """Sets the player endpoints generator"""
        Logger.info(f'Setting player endpoints generator to {func}')
        self._player_endpoints_generator = partial(func, *args, **kwargs)

    def set_player_endpoints(self, cue: Cue) -> None:
        """Sets the player endpoints for a given cue"""
        if self._player_endpoints_generator is None:
            raise ValueError("Player endpoints generator not set")
        try:
            self._player_endpoints_generator(cue)
        except Exception as e:
            Logger.error(f'Error setting player endpoints for cue {cue.id}: {e}')

    def get_cue_output_name(self, cue: Cue) -> str:
        """Get the output name for a given cue."""
        outputs_key = next(iter(cue.outputs))
        Logger.debug(f'Cue outputs: {outputs_key} ')
        Logger.debug(f'video player keys: {self._video_players.keys()}')
        Logger.debug(f"Output key is {outputs_key} and output name {outputs_key['output_name'][-1]}")
        output_id = outputs_key['output_name'][-1]

        return output_id

    def add_media_folder(self, path: str):
        """Adds a media folder to the player handler"""
        path = path.split('/')
        if path[-1] != 'media':
            path.append('media')
        self._media_folder = '/' + '/'.join(path)

    def media_path(self, file_name: str) -> str:
        """Returns the media path for a given file name"""
        return self._media_folder + '/' + file_name

    def add_node_uuid(self, uuid: str):
        """Adds a node uuid to the player handler"""
        self._node_uuid = uuid


# ---------------------------
# Singleton
# ---------------------------

PLAYER_HANDLER = PlayerHandler()
