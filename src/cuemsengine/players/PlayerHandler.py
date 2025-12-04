from cuemsutils.log import Logger
from cuemsutils.cues import AudioCue, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from functools import partial
from threading import RLock
from time import sleep
from typing import Callable

from .AudioPlayer import AudioPlayer, start_audio_output
from .VideoPlayer import VideoPlayer, VideoClient
from .AudioMixer import AudioMixer, MixerClient, start_audio_mixer
from .DmxPlayer import DmxPlayer, DmxClient, start_dmx_player

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
            cls._instance._audio_mixer = None
            cls._instance._audio_mixer_client = None
            cls._instance._cue_players = {}
            cls._instance._dmx_player = None
            cls._instance._dmx_player_client = None
            cls._instance._player_endpoints_generator = None
            cls._instance._front_video_player = None
            cls._instance._video_output_names = []
            cls._instance._video_players = {}
            cls._instance._outputs_map = None
            cls._instance._lock = RLock()  # Use RLock to allow reentrant locking
            cls._instance._media_folder = DEFAULT_MEDIA_FOLDER
            cls._instance._node_uuid = None
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
                try:
                    player = self._cue_players.pop(cue)
                except KeyError:
                    Logger.error(f'Cue player not found for cue {cue.id}')
                    player = None
                cue._osc = None
            if isinstance(player, AudioPlayer):
                PORT_HANDLER.remove_ports(cue)
                if player is not None:
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

    def start_audio_mixer(self, audio_outputs: list, port: int, mixer_id: str, path: str = None, args: str | None = None) -> tuple[AudioMixer, MixerClient]:
        """Starts the audio mixer for this node.
        
        Args:
            audio_outputs: List of audio output configurations
            port: OSC port for jack-volume communication
            node_uuid: Unique identifier for this mixer node
            path: Optional path to jack-volume binary
            
        Returns:
            Tuple containing the AudioMixer and MixerClient instances
        """
        Logger.info(f'Starting audio mixer {mixer_id}')
        self._audio_mixer, self._audio_mixer_client = start_audio_mixer(
            audio_outputs=audio_outputs,
            port=port,
            mixer_id=mixer_id,
            path=path,
            args=args
        )
        return self._audio_mixer, self._audio_mixer_client

    def get_audio_mixer(self) -> AudioMixer:
        """Returns the audio mixer instance."""
        return self._audio_mixer

    def get_audio_mixer_client(self) -> MixerClient:
        """Returns the audio mixer client instance."""
        return self._audio_mixer_client

    # ---------------------------
    # DMX Player Management
    # ---------------------------

    def start_dmx_player(self, port: int, node_uuid: str, path: str, args: str | None = None) -> tuple[DmxPlayer, DmxClient]:
        """Starts the DMX player for this node.
        
        Args:
            port: OSC port for dmxplayer communication
            node_uuid: Unique identifier for this player node
            path: Path to dmxplayer-cuems binary
            
        Returns:
            Tuple containing the DmxPlayer and DmxClient instances
        """
        Logger.info(f'Starting DMX player for node {node_uuid}')
        self._dmx_player, self._dmx_player_client = start_dmx_player(
            port=port,
            node_uuid=node_uuid,
            path=path,
            args=args
        )
        return self._dmx_player, self._dmx_player_client

    def get_dmx_player(self) -> DmxPlayer:
        """Returns the DMX player instance."""
        return self._dmx_player

    def get_dmx_player_client(self) -> DmxClient:
        """Returns the DMX player client instance."""
        return self._dmx_player_client

    # ---------------------------
    # Audio Cue Management
    # ---------------------------

    def new_audio_output(self, cue: AudioCue) -> None:
        """Creates a new audio output for the given cue

        The player is stored in the player handler and the osc client is assigned to the cue.
        After creating the player, it will be automatically connected to the audio mixer if one exists.
        
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
        
        # Connect the player to the audio mixer if available
        if self._audio_mixer is not None:
            # Wait for the player to register with JACK
            sleep(0.5)
            
            # Use the cue ID as the player name (same as the client name format)
            uuid_slug = ''.join(str(cue.id).split('-'))
            player_name = f'audioplayer-{uuid_slug}'
            Logger.info(f'Connecting player {player_name} to audio mixer')
            # Connect to mixer channel 0 by default (can be made configurable later)
            self._audio_mixer.connect_player_to_mixer(
                player_name=player_name,
                player_output_prefix='output',
                mixer_channel=0
            )

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
        output_name = self.get_cue_output_name(cue)
        if not output_name:
            Logger.error(f'No video player found for cue {cue.id}')
            raise ValueError(f'No video player found for cue {cue.id}')
        
        if not self._front_video_player:
            # Initialize the front video player
            player = self.get_active_videoplayer(output_name)
            self._front_video_player = 1
        else:
            player = self.get_inactive_videoplayer(output_name)

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
        """Resets the video players and kills their processes."""
        Logger.debug('Resetting video players')
        with self._lock:
            # Kill all video player processes before resetting
            for output_name, players in list(self._video_players.items()):
                for player_dict in players:
                    try:
                        if 'player' in player_dict:
                            player = player_dict['player']
                            player.kill()
                            # Wait for thread to die
                            if player.is_alive():
                                player.join(timeout=0.5)
                    except Exception as e:
                        Logger.debug(f'Error killing video player: {e}')
            self._video_players = {}
            self._video_output_names = []
    
    def reset_all(self):
        """Complete reset of PlayerHandler for testing"""
        Logger.debug('Performing complete PlayerHandler reset')
        self.reset_video_players()
        self._cue_players = {}
        self._front_video_player = None
        self._outputs_map = None

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
                    # Clean up existing players for this output before recreating
                    for player_dict in self._video_players[output_name]:
                        try:
                            if 'player' in player_dict:
                                player_dict['player'].kill()
                        except Exception as e:
                            Logger.debug(f'Error killing existing video player: {e}')
                self._video_players[output_name] = []

            new_ports = output_ports[index]

            for i in range(1):
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
                    # Start with timeout handling (now done in Player.start())
                    player['player'].start(timeout=5.0)
                    
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
    
    def set_outputs_map(self, outputs_map: dict):
        """Set the outputs map for the player handler"""
        self._outputs_map = outputs_map

    def get_cue_output_name(self, cue: Cue) -> str | None:
        """Get the output name for a given cue from the outputs map.
        
        Args:
            cue: The cue to get the output name for

        Returns:
            The output name for the given cue or None if the cue is not found in the outputs map
        
        Raises:
            AttributeError: If the outputs map is not set
        """
        if self._outputs_map is None:
            Logger.error('Outputs map not set')
            raise AttributeError('Outputs map not set')
        return self._outputs_map.get(cue.id, None)

    def add_media_folder(self, path: str):
        """Adds a media folder to the player handler"""
        path = path.split('/')
        if path[-1] != 'media':
            path.append('media')
        self._media_folder = '/' + '/'.join(path)
        if self._media_folder[0:2] == "//":
            self._media_folder = self._media_folder[1:]

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
