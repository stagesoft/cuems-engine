import subprocess
from time import sleep

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
    _gradient_client: 'GradientClient | None'
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
            cls._instance._gradient_client = None
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
                        Logger.debug(f'Cue player not found for cue {cue.id}')
                        return
                
                # Also remove from ID-based tracking
                self._audio_players_by_id.pop(cue_id, None)
                
                # Save OSC client reference before clearing
                osc_client = getattr(cue, '_osc', None)
                cue._osc = None
            if isinstance(player, AudioPlayer):
                killed = self._kill_audio_player(player, osc_client, cue_id)
                # Free port AFTER process is dead to prevent concurrent arm
                # from getting a port the OS still has bound (Bug 2 fix).
                # Skip if kill failed — process still holds the port.
                if killed:
                    PORT_HANDLER.remove_ports(cue)

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

    def _kill_audio_player(self, player: AudioPlayer, osc_client: AudioClient, cue_id: str) -> bool:
        """Helper method to kill an audio player process.

        The order is critical: disconnect JACK ports first, THEN send /quit.
        If /quit is sent first the player destroys its JACK client immediately,
        and subsequent disconnect calls hit non-existent ports which can corrupt
        JACK's shared-memory semaphore registry.

        Returns:
            True if the process was successfully killed (or was already dead),
            False if the process could not be killed (still alive after timeout).
        """
        if player is None:
            return True

        # 1. Disconnect player from the mixer BEFORE destroying its JACK client
        if self._audio_mixer is not None:
            try:
                uuid_slug = ''.join(cue_id.split('-'))
                player_name = f'Audio_Player-{uuid_slug}'
                self._audio_mixer.disconnect_player(player_name)
                Logger.debug(f'Disconnected {player_name} from mixer')
            except Exception as e:
                Logger.warning(f'Failed to disconnect audio player from mixer: {e}')

        # 2. Send /quit OSC command to gracefully stop the player
        if osc_client is not None:
            try:
                osc_client.set_value('/quit', True)
                Logger.debug(f'Sent /quit command to audio player for cue {cue_id}')
            except Exception as e:
                Logger.warning(f'Failed to send /quit to audio player: {e}')

            # Free the random OSC local port back into the pool
            local_port = getattr(osc_client, 'local_port', None)
            if local_port is not None:
                PORT_HANDLER.remove_random_port(local_port)

        # 3. Kill the subprocess and wait for the OS to release its resources.
        #    SIGKILL is near-instant; 1s timeout handles edge cases (D state).
        process_dead = True
        try:
            if player.p is not None:
                player.p.kill()
                player.p.wait(timeout=1.0)
                Logger.debug(f'Killed audio player subprocess for cue {cue_id}')
        except subprocess.TimeoutExpired:
            Logger.error(f'Audio player process for cue {cue_id} did not die after SIGKILL — port may still be bound')
            process_dead = False
        except Exception as e:
            Logger.warning(f'Failed to kill audio player subprocess: {e}')

        # Wait for thread to finish
        try:
            player.join(timeout=0.5)
        except Exception as e:
            Logger.warning(f'Failed to join audio player thread: {e}')

        # 4. Verify JACK has removed the dead client's ports.
        #    wait() reaps the process, which triggers JACK to unregister the
        #    client. Poll briefly to confirm ports are gone before returning.
        if process_dead and self._audio_mixer is not None:
            uuid_slug = ''.join(cue_id.split('-'))
            player_name = f'Audio_Player-{uuid_slug}'
            for _ in range(10):
                if not self._audio_mixer.conn_man.port_exists(f'{player_name}:outport 0'):
                    break
                sleep(0.1)
            else:
                Logger.warning(f'JACK client {player_name} still has ports after kill')

        return process_dead

    def kill_all_audio_players(self):
        """Kill ALL tracked audio players - used during project cleanup"""
        with self._lock:
            players_to_kill = list(self._audio_players_by_id.items())
            self._audio_players_by_id.clear()

            # Also clear audio players from _cue_players, saving the OSC
            # client so _kill_audio_player can free the random port.
            cue_players_to_remove = []
            for cue, player in self._cue_players.items():
                if isinstance(player, AudioPlayer):
                    osc_client = getattr(cue, '_osc', None)
                    cue._osc = None
                    cue_players_to_remove.append((cue, player, osc_client))
            for cue, player, osc_client in cue_players_to_remove:
                self._cue_players.pop(cue, None)
                players_to_kill.append((str(cue.id), player, osc_client))

        Logger.info(f'Killing {len(players_to_kill)} audio players during cleanup')
        for entry in players_to_kill:
            if len(entry) == 3:
                cue_id, player, osc_client = entry
            else:
                cue_id, player = entry
                osc_client = None
            self._kill_audio_player(player, osc_client, cue_id)

    def cleanup_zombie_jack_clients(self) -> int:
        """Scan for JACK Audio_Player clients whose processes have died.

        Enumerates all JACK ports matching Audio_Player-* and cross-references
        with tracked players in _audio_players_by_id. Unmatched ports are
        zombies left by crashed processes — disconnect them from the mixer.

        Called on project load to clear stale state from previous runs.

        Returns:
            Number of zombie clients found and cleaned up.
        """
        if self._audio_mixer is None:
            return 0

        all_ports = self._audio_mixer.conn_man.get_ports(
            pattern='Audio_Player-.*', is_audio=True, is_output=True
        )
        if not all_ports:
            return 0

        # Extract unique client names from port names (e.g. "Audio_Player-abc123:outport 0" → "Audio_Player-abc123")
        jack_clients = set()
        for port_name in all_ports:
            client_name = port_name.split(':')[0]
            jack_clients.add(client_name)

        # Build set of tracked player client names
        with self._lock:
            tracked_slugs = set()
            for cue_id in self._audio_players_by_id:
                slug = ''.join(cue_id.split('-'))
                tracked_slugs.add(f'Audio_Player-{slug}')

        zombies = jack_clients - tracked_slugs
        if not zombies:
            return 0

        Logger.warning(f'Found {len(zombies)} zombie JACK audio clients: {zombies}')
        for client_name in zombies:
            try:
                self._audio_mixer.disconnect_player(client_name)
                Logger.info(f'Disconnected zombie JACK client {client_name}')
            except Exception as e:
                Logger.warning(f'Failed to disconnect zombie {client_name}: {e}')

        return len(zombies)

    def kill_orphaned_audio_processes(self):
        """Kill cuems-audioplayer OS processes not tracked by this engine.

        On engine restart, previously spawned audioplayer processes survive
        because they are independent subprocesses. The new engine has no
        reference to them, so they steal JACK client names and cause silence.
        """
        import os
        import signal
        result = subprocess.run(
            ['pgrep', '-f', 'cuems-audioplayer'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return

        tracked_pids = set()
        with self._lock:
            for player in self._audio_players_by_id.values():
                if player and player.p:
                    tracked_pids.add(player.p.pid)

        for pid_str in result.stdout.strip().split('\n'):
            if not pid_str:
                continue
            pid = int(pid_str)
            if pid not in tracked_pids:
                Logger.warning(f'Killing orphaned audioplayer process {pid}')
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

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

        # Kill any existing player for this cue before spawning a new one.
        # This prevents orphaned audioplayer processes when a cue is re-armed
        # without being disarmed first (the old process would keep running,
        # holding its JACK client and OSC port, while its reference is silently
        # overwritten in _audio_players_by_id).
        cue_id = str(cue.id)
        with self._lock:
            existing_player = self._audio_players_by_id.pop(cue_id, None)
            self._cue_players.pop(cue, None)
        if existing_player is not None:
            Logger.warning(f'Killing existing audio player for cue {cue_id} before re-arm')
            # Save and clear OSC client so loop_audioCue stops sending to the
            # dying player (it will hit AttributeError, caught by its blanket
            # except AttributeError handler and exit silently).
            existing_osc = getattr(cue, '_osc', None)
            cue._osc = None
            killed = self._kill_audio_player(existing_player, existing_osc, cue_id)
            # Free assigned port AFTER process is dead to avoid Bug 2's race.
            # Skip if kill failed — process still holds the port.
            if killed:
                PORT_HANDLER.remove_ports(cue)

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
            uuid_slug = ''.join(str(cue.id).split('-'))
            player_name = f'Audio_Player-{uuid_slug}'

            # Resolve each output_name to its JACK port via the ID in the mappings.
            # output_name format: "{node_uuid}_{output_id}"  (e.g. "a3811d78-..._6")
            # resolve_audio_port maps the numeric ID → JACK port name (e.g. "usb_audio:playback_1")
            selected_outputs = []
            for output in getattr(cue, 'outputs', []):
                raw = output.get('output_name', '')
                output_id = raw[37:] if len(raw) > 37 else None  # strip "{uuid}_"
                if output_id is not None:
                    jack_port = self.resolve_audio_port(output_id)
                    if jack_port:
                        selected_outputs.append(jack_port)
                    else:
                        Logger.warning(f'Cannot resolve audio output ID "{output_id}" to a JACK port')

            if not selected_outputs:
                Logger.warning(f'No valid audio outputs resolved for cue {cue.id}, skipping mixer connection')
            else:
                Logger.info(f'Connecting {player_name} to outputs: {selected_outputs}')
                self._audio_mixer.connect_player_to_outputs(
                    player_name=player_name,
                    player_output_prefix='outport',
                    selected_outputs=selected_outputs
                )


    # ---------------------------
    # DMX Player Management
    # ---------------------------

    def start_dmx_player(self, port: int, node_uuid: str, path: str, args: str | None = None) -> tuple[DmxPlayer, DmxClient]:
        """Starts the DMX player for this node.
        
        Args:
            port: OSC port for dmxplayer communication
            node_uuid: Unique identifier for this player node
            path: Path to cuems-dmxplayer binary
            
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

    def get_gradient_client(self) -> 'GradientClient | None':
        """Returns the GradientClient instance, or None if not yet initialised."""
        return self._gradient_client

    def set_gradient_client(self, port: int, node_uuid: str) -> None:
        """Construct (or replace) the GradientClient for this node.

        Safe to call multiple times: any new call replaces the prior client.
        PyOscClient is fire-and-forget UDP with no held resources, so no
        teardown of the prior client is needed.
        """
        from .GradientClient import GradientClient
        self._gradient_client = GradientClient(
            host='127.0.0.1', port=port, node_uuid=node_uuid,
        )
        Logger.info(
            f'GradientClient: bound to 127.0.0.1:{port} node_uuid={node_uuid}'
        )

    def start_video_outputs(
        self,
        output_names: dict[str, dict[str, any]],
        canvas_override: tuple[int, int] | None = None,
    ) -> None:
        """Ensures that the all the required video output exist.

        ``canvas_override`` is an optional ``(width, height)`` carrying the
        engine reader's authoritative canvas size — set when display.conf
        has a ``canvas_size=`` global key. When provided, it must be >=
        the per-region bounding box (we validate as defense in depth — the
        reader already validates, but a stale caller could pass garbage).
        When ``None``, fall back to bbox computed from the output regions.
        """
        Logger.info(f'Checking & starting video outputs for {output_names} ')
        bbox_w, bbox_h = 0, 0
        for cfg in output_names.values():
            region = cfg.get('canvas_region') or {}
            right = region.get('x', 0) + region.get('width', 1920)
            bottom = region.get('y', 0) + region.get('height', 1080)
            bbox_w = max(bbox_w, right)
            bbox_h = max(bbox_h, bottom)
        if canvas_override is not None:
            cw, ch = canvas_override
            if cw < bbox_w or ch < bbox_h:
                raise ValueError(
                    f"canvas_override {cw}x{ch} is smaller than the per-output "
                    f"bounding box {bbox_w}x{bbox_h}; monitors would be cropped"
                )
            canvas_w, canvas_h = cw, ch
        else:
            canvas_w, canvas_h = bbox_w, bbox_h
        Logger.info(f'Canvas: {canvas_w}x{canvas_h} (bbox={bbox_w}x{bbox_h})')
        for output_name, output_config in output_names.items():
            output_config['canvas_width'] = canvas_w
            output_config['canvas_height'] = canvas_h
            video_output = VideoOutput(**output_config)
            video_output.apply_config(self._video_client)
            self._video_outputs[output_name] = video_output

    def get_video_output(self, output_name: str) -> VideoOutput:
        """Returns the VideoOutput object for a given output name."""
        return self._video_outputs[output_name]

    def _resolve_canvas_dimensions(self) -> tuple[int, int]:
        """Return the node's canvas (width, height) in pixels.

        All alias VideoOutputs on a node share the same canvas totals,
        written by start_video_outputs. Raises if no aliases exist yet —
        custom outputs have no independent canvas dimensions.
        """
        for vo in self._video_outputs.values():
            return vo.canvas_width, vo.canvas_height
        raise RuntimeError(
            "Cannot resolve canvas dimensions: no named video outputs "
            "are registered. Custom outputs require at least one alias "
            "on the same node."
        )

    def make_custom_video_output(self, cue_output) -> VideoOutput:
        """Build a VideoOutput for a per-cue custom region.

        cue_output is a dict-like VideoCueOutput with a canvas_region
        holding normalized floats in [0, 1]. Converts to pixel integers
        so VideoOutput.get_layer_placement / get_layer_scale work the
        same way they do for alias outputs.
        """
        region_norm = cue_output["canvas_region"]
        canvas_w, canvas_h = self._resolve_canvas_dimensions()
        region_px = {
            "x": int(region_norm["x"] * canvas_w),
            "y": int(region_norm["y"] * canvas_h),
            "width": int(region_norm["width"] * canvas_w),
            "height": int(region_norm["height"] * canvas_h),
        }
        return VideoOutput(
            name=cue_output.get("output_name", "custom"),
            canvas_region=region_px,
            canvas_width=canvas_w,
            canvas_height=canvas_h,
            width=region_px["width"],
            height=region_px["height"],
        )

    def resolve_video_output_for_cue(self, cue, output_name: str) -> VideoOutput:
        """Resolve an output_name suffix to a VideoOutput.

        For alias suffixes (<int>) looks up the cached VideoOutput.
        For custom suffixes (custom_<n>) synthesizes a VideoOutput from
        the matching VideoCueOutput's inline canvas_region.
        """
        if output_name.startswith("custom_"):
            full = f"{self._node_uuid}_{output_name}"
            cue_output = next(
                (o for o in cue.outputs if o.get("output_name") == full),
                None,
            )
            if cue_output is None:
                raise KeyError(f"No VideoCueOutput match for {full}")
            return self.make_custom_video_output(cue_output)
        return self._video_outputs[output_name]

    def register_layer(self, layer_id: str) -> None:
        """Track a layer as active in the videocomposer."""
        with self._lock:
            self._loaded_layer_ids.add(layer_id)

    def deregister_layer(self, layer_id: str) -> None:
        """Remove a layer from active tracking."""
        with self._lock:
            self._loaded_layer_ids.discard(layer_id)

    def reset_videocomposer(self):
        """Send atomic reset to videocomposer (removes all layers + resets master)."""
        Logger.debug('Sending atomic reset to videocomposer')
        if self._video_client is not None:
            try:
                self._video_client.set_value('/videocomposer/reset', None)
            except Exception as e:
                Logger.warning(f'Error sending reset to videocomposer: {e}')
            # Remove all layer endpoints from the OSC client
            with self._lock:
                for layer_id in list(self._loaded_layer_ids):
                    try:
                        self._video_client.remove_layer_endpoints(layer_id)
                    except Exception as e:
                        Logger.debug(f'Error removing layer endpoints {layer_id}: {e}')
        with self._lock:
            self._loaded_layer_ids.clear()

    def reset_video_layers(self):
        """Unload all tracked video layers (video blackout). Legacy per-layer method."""
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

    @property
    def node_uuid(self) -> str | None:
        """Public read-only accessor for the node uuid."""
        return self._node_uuid


# ---------------------------
# Singleton
# ---------------------------

PLAYER_HANDLER = PlayerHandler()
