from cuemsutils.log import Logger
from cuemsutils.cues import AudioCue, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from functools import partial
from threading import RLock
from typing import Callable

from .AudioPlayer import AudioPlayer, AudioClient, start_audio_output
from .VideoPlayer import VideoPlayer, VideoClient, VideoOutput
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
    _instance: 'PlayerHandler | None' = None

    # Instance attributes (declared for IDE/type checker support)
    _audio_output_generator: partial | None
    _audio_mixer: AudioMixer | None
    _audio_mixer_client: MixerClient | None
    _cue_players: dict[Cue, Player]
    _audio_players_by_id: dict[str, AudioPlayer]
    _dmx_player: DmxPlayer | None
    _dmx_player_client: DmxClient | None
    _player_endpoints_generator: partial | None
    _video_client: VideoClient | None
    _video_outputs: dict[str, VideoOutput]
    _audio_outputs: dict[str, dict]
    _loaded_layer_ids: set[str]
    _outputs_map: dict | None
    _lock: RLock
    _media_folder: str
    _node_uuid: str | None

    def __new__(cls, *args, **kwargs):
        """Singleton pattern: Ensure only one instance is created"""
        if not cls._instance:
            cls._instance = super(PlayerHandler, cls).__new__(cls)

            cls._instance._audio_output_generator = None
            cls._instance._audio_mixer = None
            cls._instance._audio_mixer_client = None
            cls._instance._cue_players = {}
            cls._instance._audio_players_by_id = {}
            cls._instance._dmx_player = None
            cls._instance._dmx_player_client = None
            cls._instance._player_endpoints_generator = None
            cls._instance._video_client = None
            cls._instance._video_outputs = {}
            cls._instance._audio_outputs = {}
            cls._instance._loaded_layer_ids = set()
            cls._instance._outputs_map = None
            cls._instance._lock = RLock()
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
            osc_client = None
            cue_id = str(cue.id)
            with self._lock:
                try:
                    player = self._cue_players.pop(cue)
                except KeyError:
                    # Try to find by ID in _audio_players_by_id
                    player = self._audio_players_by_id.pop(cue_id, None)
                    if player is None:
                        Logger.error(f'Cue player not found for cue {cue.id}')
                
                # Also remove from ID-based tracking
                self._audio_players_by_id.pop(cue_id, None)
                
                # Save OSC client reference before clearing
                osc_client = getattr(cue, '_osc', None)
                cue._osc = None
            if isinstance(player, AudioPlayer):
                PORT_HANDLER.remove_ports(cue)
                self._kill_audio_player(player, osc_client, cue_id)

    def reset_all(self):
        """Complete reset of PlayerHandler for testing"""
        Logger.debug('Performing complete PlayerHandler reset')
        self.reset_video_layers()
        self._video_outputs = {}
        self._cue_players = {}
        self._outputs_map = None
        with self._lock:
            self._loaded_layer_ids.clear()


    # ---------------------------
    # Audio Player Management
    # ---------------------------

    def set_audio_output_generator(self, path: str, args: str):
        """Sets the audio player generator"""
        Logger.info(f'Setting audio output generator to {path} {args}')
        self._audio_output_generator = partial(start_audio_output, path=path, args=args)

    def set_audio_outputs(self, audio_outputs: dict[str, dict]) -> None:
        """Store audio output configs keyed by <id>."""
        self._audio_outputs = audio_outputs

    def resolve_audio_port(self, output_id: str) -> str | None:
        """Resolve an output <id> to its JACK port name (mapped_to)."""
        output = self._audio_outputs.get(output_id)
        if output:
            return output.get('mapped_to')
        return None

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

    def _kill_audio_player(self, player: AudioPlayer, osc_client: AudioClient, cue_id: str) -> None:
        """Helper method to kill an audio player process"""
        if player is None:
            return
        
        # First, try to send /quit OSC command to gracefully stop the player
        if osc_client is not None:
            try:
                osc_client.set_value('/quit', True)
                Logger.debug(f'Sent /quit command to audio player for cue {cue_id}')
            except Exception as e:
                Logger.warning(f'Failed to send /quit to audio player: {e}')
        
        # Then kill the subprocess forcefully
        try:
            if player.p is not None:
                player.p.kill()
                Logger.debug(f'Killed audio player subprocess for cue {cue_id}')
        except Exception as e:
            Logger.warning(f'Failed to kill audio player subprocess: {e}')
        
        # Wait for thread to finish
        try:
            player.join(timeout=2.0)
        except Exception as e:
            Logger.warning(f'Failed to join audio player thread: {e}')

    def kill_all_audio_players(self):
        """Kill ALL tracked audio players - used during project cleanup"""
        with self._lock:
            players_to_kill = list(self._audio_players_by_id.items())
            self._audio_players_by_id.clear()
            
            # Also clear audio players from _cue_players
            cue_players_to_remove = []
            for cue, player in self._cue_players.items():
                if isinstance(player, AudioPlayer):
                    cue_players_to_remove.append((cue, player))
            for cue, player in cue_players_to_remove:
                self._cue_players.pop(cue, None)
                players_to_kill.append((str(cue.id), player))
        
        Logger.info(f'Killing {len(players_to_kill)} audio players during cleanup')
        for cue_id, player in players_to_kill:
            self._kill_audio_player(player, None, cue_id)


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
        
        # Also track by cue ID string for cleanup when cue object is lost
        with self._lock:
            self._audio_players_by_id[str(cue.id)] = player
        
        # Connect the player to the audio mixer if available
        if self._audio_mixer is not None:
            # Use the cue ID as the player name
            # audioplayer-cuems creates JACK client as "Audio_Player-{uuid}" with ports "outport 0", "outport 1"
            uuid_slug = ''.join(str(cue.id).split('-'))
            player_name = f'Audio_Player-{uuid_slug}'
            Logger.info(f'Connecting player {player_name} to audio mixer')
            # Connect to mixer channel 0 by default (can be made configurable later)
            # connect_player_to_mixer has built-in retry logic for JACK port availability
            self._audio_mixer.connect_player_to_mixer(
                player_name=player_name,
                player_output_prefix='outport',  # audioplayer-cuems uses "outport 0", "outport 1"
                mixer_channel=0
            )


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

    def get_video_client(self) -> VideoClient:
        """Returns the video client instance."""
        return self._video_client

    def set_video_client(self, port: int) -> None:
        """Sets the video client for this node."""
        Logger.info(f'Setting video client for node {self._node_uuid}')
        self._video_client = VideoClient(player_port=port)

    def start_video_outputs(self, output_names: dict[str, dict[str, any]]) -> None:
        """Ensures that the all the required video output exist."""
        Logger.info(f'Checking & starting video outputs for {output_names} ')
        canvas_w, canvas_h = 0, 0
        for cfg in output_names.values():
            region = cfg.get('canvas_region') or {}
            right = region.get('x', 0) + region.get('width', 1920)
            bottom = region.get('y', 0) + region.get('height', 1080)
            canvas_w = max(canvas_w, right)
            canvas_h = max(canvas_h, bottom)
        for output_name, output_config in output_names.items():
            output_config['canvas_width'] = canvas_w
            output_config['canvas_height'] = canvas_h
            video_output = VideoOutput(**output_config)
            video_output.apply_config(self._video_client)
            self._video_outputs[output_name] = video_output

    def get_video_output(self, output_name: str) -> VideoOutput:
        """Returns the VideoOutput object for a given output name."""
        return self._video_outputs[output_name]

    def register_layer(self, layer_id: str) -> None:
        """Track a layer as active in the videocomposer."""
        with self._lock:
            self._loaded_layer_ids.add(layer_id)

    def deregister_layer(self, layer_id: str) -> None:
        """Remove a layer from active tracking."""
        with self._lock:
            self._loaded_layer_ids.discard(layer_id)

    def reset_video_layers(self):
        """Unload all tracked video layers (video blackout)."""
        Logger.debug('Resetting video layers')
        with self._lock:
            if self._video_client is None:
                self._loaded_layer_ids.clear()
                return
            for layer_id in list(self._loaded_layer_ids):
                try:
                    self._video_client.set_value('/videocomposer/layer/unload', layer_id)
                    self._video_client.remove_layer_endpoints(layer_id)
                except Exception as e:
                    Logger.debug(f'Error unloading layer {layer_id}: {e}')
            self._loaded_layer_ids.clear()

    def quit_videocomposer(self):
        """Quits the videocomposer process."""
        Logger.debug('Quitting videocomposer')
        if self._video_client is not None:
            try:
                self._video_client.set_value('/videocomposer/quit', None)
            except Exception as e:
                Logger.debug(f'Error sending quit to videocomposer: {e}')
        self._video_client = None
        self._video_outputs = {}
        with self._lock:
            self._loaded_layer_ids.clear()


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
        outputs = self._outputs_map.get(cue.id, None)
        # outputs_map stores lists, but callers expect a single string
        if isinstance(outputs, list) and len(outputs) > 0:
            return outputs[0]
        return outputs

    def get_all_cue_output_names(self, cue: Cue) -> list:
        """Get all output names for a given cue from the outputs map.
        
        Args:
            cue: The cue to get the output names for

        Returns:
            List of output names for the given cue, or empty list if not found
        
        Raises:
            AttributeError: If the outputs map is not set
        """
        if self._outputs_map is None:
            Logger.error('Outputs map not set')
            raise AttributeError('Outputs map not set')
        outputs = self._outputs_map.get(cue.id, None)
        if isinstance(outputs, list):
            return outputs
        elif outputs:
            return [outputs]
        return []

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
