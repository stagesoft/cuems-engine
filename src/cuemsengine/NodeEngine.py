# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
from functools import partial
from time import sleep
import os
import subprocess
import threading

from cuemsutils.cues import CueList, VideoCue, AudioCue, DmxCue
from cuemsutils.cues.MediaCue import MediaCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine
from .cues.CueHandler import CUE_HANDLER
from .display_conf import read_display_conf, DisplayConfNotFoundError
from .osc.helpers import add_prefix_to_all
from .tools.CuemsDeploy import CuemsDeploy
from .tools.PortHandler import PORT_HANDLER
from .players import AudioClient, DmxClient, VideoClient
from .players.PlayerHandler import PLAYER_HANDLER

VIDEOCOMPOSER_OSC_PORT_DEFAULT = 7000


def _append_output_latency_flag(args, player_conf: dict) -> str:
    """Append --output-latency-ms <int> to args when the player's
    settings.xml config has an explicit integer value.

    settings.xml accepts integer (override) or the literal string
    "auto" (use the binary's built-in default or auto-calibration).
    xmlschema decodes integers as Python int and "auto" as str.
    isinstance(value, int) distinguishes reliably; "auto" and None
    both mean "don't emit the flag". See cuems-utils
    test_output_latency_ms_type_round_trip for the typing contract.

    args may be None (empty <args/> element decodes to None in xmlschema)
    or an empty string — normalize both to '' before concatenation so the
    spawned argv never carries a literal "None" token.
    """
    args = args or ''
    value = player_conf.get('output_latency_ms')
    if isinstance(value, int):
        return f'{args} --output-latency-ms {value}'.strip()
    return args

class NodeEngine(BaseEngine):
    """
    This engine manages players for each node
    
    Communicates with the ControllerEngine via OSCQuery
    
    Interacts with Player objects via OSC

    It is responsible for:
      - Starting and stopping players
      - Monitoring player status
      - Restarting players
      - Updating player configurations
      - Handling player failures
      - Providing a clean interface for starting and stopping players
      - Providing a clean interface for monitoring player status
    
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._command_lock = threading.Lock()
        self._loading_lock = threading.Lock()
        self._loading = False
        self._project_generation: int = 0
        self.nng_hub_address = f"tcp://{self.controller_ip}:{self.cm.node_conf['nng_hub_port']}"
        PORT_HANDLER.add_system_ports()
        if hasattr(self, 'cm'):
            PORT_HANDLER.add_config_ports(
                get_config_ports(self.cm.node_conf)
            )
            self.deploy_manager = CuemsDeploy(
                library_path=self.cm.library_path,
                tmp_path=self.cm.tmp_path,
                controller_ip=self.controller_ip,  # set by BaseEngine.set_cm()
            )
            PLAYER_HANDLER.add_media_folder(
                self.cm.library_path
            )
            PLAYER_HANDLER.set_player_endpoints_generator(
                self.add_player_endpoints,
                # TODO: Use node host from config
                prefix = '/players'
            )

    def start(self):
        CUE_HANDLER.set_nng_comms(self.nng_hub_address, self.cm.node_uuid)
        self.set_oscquery_comms()  # Creates command dictionary and OSCQuery client
        self.set_players()  # Creates player devices - must be before NNG callback
        self._setup_nng_command_callback()  # Set up NNG command receiving (after players ready)
        self.mtc_listener.start()
        super().start()
    
    def _setup_nng_command_callback(self):
        """Set up the callback for receiving commands via NNG from ControllerEngine.
        
        This provides push-based command delivery as an alternative to HTTP polling.
        Commands are received via the NNG bus and routed to the appropriate handlers.
        """
        if hasattr(CUE_HANDLER, 'communications_thread') and CUE_HANDLER.communications_thread:
            CUE_HANDLER.communications_thread.set_command_callback(self._handle_nng_command)
            Logger.info("NNG command callback registered for NodeEngine")
        else:
            Logger.warning("CUE_HANDLER communications thread not available for command callback")

        from .cues.ActionHandler import ACTION_HANDLER

        ACTION_HANDLER.finalize_node_layer_bindings()
        ACTION_HANDLER.set_result_sink(self._action_result_sink)


    def _handle_nng_command(self, command_name: str, value, address: str = None):
        """Handle a command received via NNG from ControllerEngine.
        
        Args:
            command_name: The command name (e.g., 'go', 'load', 'stop', 'player_control')
            value: The command value
            address: The original OSC address (optional)
        """
        Logger.info(f"NNG command received: {command_name} = {repr(value)}")
        
        if command_name == 'player_control' and address:
            # Handle player control messages (mixer volumes, video controls, etc.)
            self._handle_player_control_message(address, value)
        else:
            # Handle standard commands (go, load, stop)
            self.run_command(command_name, value)
    
    def _handle_player_control_message(self, address: str, value):
        """Handle player control messages received via NNG.
        
        Routes to appropriate player handlers based on the OSC address.
        Supports two formats:
        1. Engine format: /engine/players/<uuid>/<type>/...
        2. Direct format: /<uuid>/<type>/... (from UI)
        
        Args:
            address: The OSC address
            value: The value to set
        """
        parts = address.strip('/').split('/')
        
        # Determine format and extract node_uuid, player_type, path_parts
        if len(parts) >= 4 and parts[0] == 'engine' and parts[1] == 'players':
            # Engine format: /engine/players/<node_uuid>/<type>/...
            node_uuid = parts[2]
            player_type = parts[3]
            path_parts = parts[4:] if len(parts) > 4 else []
        elif len(parts) >= 2:
            # Direct format: /<node_uuid>/<type>/...
            node_uuid = parts[0]
            player_type = parts[1]
            path_parts = parts[2:] if len(parts) > 2 else []
        else:
            Logger.warning(f"Invalid player control address: {address}")
            return
        
        # Only handle messages for this node
        if node_uuid != self.cm.node_uuid:
            Logger.debug(f"Ignoring player message for other node: {node_uuid}")
            return
        
        Logger.debug(f"Handling player control: type={player_type}, path={path_parts}, value={value}")
        
        # Route to appropriate handler based on player type
        if player_type == 'video':
            redirect_video_cmd(path_parts, value)
        elif player_type == 'audio':
            CUE_HANDLER.route_audio_message(path_parts, value)
        elif player_type == 'dmx':
            CUE_HANDLER.route_dmx_message(path_parts, value)
        elif player_type == 'audiomixer':
            # Legacy: pre-2026 OSC format /{uuid}/audiomixer/{channel}.
            # The current UI sends /{uuid}/audio/mixer/{output_index}/{channel}/volume,
            # which routes via player_type == 'audio' → CueHandler.route_audio_message().
            # Kept for backwards compatibility with any external tool still using
            # the old format; new code should not target this path.
            # Direct audiomixer command: /<uuid>/audiomixer/<channel>
            # path_parts[0] is channel (e.g., '0', 'master')
            self._handle_audiomixer_command(path_parts, value)
        elif player_type == 'jadeo':
            # Direct video command: /<uuid>/jadeo/<cmd>
            redirect_video_cmd(['jadeo'] + path_parts, value)
        else:
            Logger.debug(f"Unknown player type in control message: {player_type}")
    
    def _handle_audiomixer_command(self, path_parts: list, value):
        """Handle direct audiomixer OSC command.
        
        Args:
            path_parts: Remaining path parts after /<uuid>/audiomixer/
                       e.g., ['0'] for channel 0, ['master'] for master
            value: Volume value (0.0 to 1.0)
        """
        if not path_parts:
            Logger.warning("Empty audiomixer command path")
            return
        
        channel = path_parts[0]
        # jack-volume expects /audiomixer/<client_name>/<channel>
        mixer_cmd = f'/audiomixer/0_mixer/{channel}'
        
        try:
            PLAYER_HANDLER.get_audio_mixer_client().set_value(mixer_cmd, value)
            Logger.debug(f"Audiomixer command: {mixer_cmd} = {value}")
        except Exception as e:
            Logger.error(f"Error sending audiomixer command: {e}")
        
    @logged
    def stop(self):
        self.stop_requested = True
        self.stop_node_engine()
        super().stop()

    def stop_node_engine(self):
        """Stop the NodeEngine elements"""
        CUE_HANDLER.disarm_all()
        self.stop_video_devs()

    def stop_video_devs(self):
        try:
            self.unload_video_devs()
            Logger.info('Video devs stopped')
        except Exception as e:
            Logger.warning(f'Exception raised when stopping video devs: {e}')

    def quit_video_devs(self):
        try:
            PLAYER_HANDLER.quit_videocomposer()
            Logger.info('Videocomposer quit successfully')
        except Exception as e:
            Logger.exception(e)

    def unload_video_devs(self):
        try:
            PLAYER_HANDLER.reset_videocomposer()
            Logger.info('Videocomposer reset successfully')
        except Exception as e:
            Logger.exception(e)

    #########################
    # OSCQuery logic
    #########################
    def add_player_endpoints(self, cue: Cue, prefix: str = '/players'):
        """Add player endpoints from a cue to the OSCQuery server
        
        Args:
            cue: The cue containing the player client
            prefix: Prefix to add to all endpoint paths (default: '/players')
        """
        if not hasattr(cue, '_osc') or cue._osc is None:
            Logger.warning(f'Cue {cue.id} has no OSC client, cannot add endpoints')
            return
        
        try:
            # Get endpoints from the player client
            endpoints = cue._osc.get_endpoints()
            if not endpoints:
                Logger.warning(f'No endpoints found for cue {cue.id}')
                return
            
            # Add prefix to all endpoints
            prefixed_endpoints = add_prefix_to_all(endpoints, f"{prefix}/{self.cm.node_uuid}/{cue.id}")
            
            # Add endpoints to OSCQuery server
            if hasattr(self, 'oscquery_server') and self.oscquery_server:
                self.oscquery_server.add_endpoints(prefixed_endpoints)
                Logger.debug(f'Added {len(prefixed_endpoints)} endpoints for cue {cue.id}')
            else:
                Logger.warning('OSCQuery server not initialized, cannot add endpoints')
        except Exception as e:
            Logger.error(f'Error adding player endpoints for cue {cue.id}: {e}')
            Logger.exception(e)

    def set_oscquery_comms(self):
        """Set up the command dictionary for the NodeEngine.
        
        Commands are received via NNG from ControllerEngine.
        OSCQuery client is no longer used since pyossia server was removed.
        """
        self.commands_dict = {
            'deploy': self.ready_project,
            'load': self.load_project,
            'loadcue': None,
            'go': self.go_script,
            'gocue': self.go_script,
            'pause': None,
            'resetall': None,
            'stop': self.stop_playback,
            'setnextcue': self.set_next_cue,
            'cue_enabled': self._handle_cue_enabled,
            'test': None,
            'unload': None,
            'update': None,
        }

    def route_message(self, parameter, value):
        # Exclude 'engine' common node
        path_elements = str(parameter.node).split('/')[2:]
        if path_elements[0] == 'command':
            self.run_command(path_elements[1], value)
        elif path_elements[0] == 'status':
            Logger.debug(f'Status update received: {path_elements[1]} = {repr(value)}')
        elif path_elements[0] == 'players':
            # Exclude other nodes' players
            if path_elements[1] != self.cm.node_uuid:
                Logger.debug(f'Ignoring player message for other node: {path_elements[1]}')
                return
            # Route the message to the appropriate player handler
            if path_elements[2] == 'video':
                redirect_video_cmd(path_elements[3:], value)
            if path_elements[2] == 'audio':
                CUE_HANDLER.route_audio_message(path_elements[3:], value)
            if path_elements[2] == 'dmx':
                CUE_HANDLER.route_dmx_message(path_elements[3:], value)
        else:
            Logger.debug(f'Recieved unused OSCQuery path: {str(parameter.node)}')
            return

    def run_command(self, command, value):
        with self._command_lock:
            Logger.debug(f'NodeEngine executing command: {command}({repr(value)})')
            if command in self.commands_dict.keys():
                handler = self.commands_dict[command]
                if handler is not None:
                    handler(value)
                    return True
                else:
                    Logger.warning(f'Command {command} has no handler')
                    return False
            else:
                Logger.error(f'Command {command} not found')
                return False

    #########################
    # Player logic
    #########################
    def set_players(self):
        self.set_video_players()
        self.set_audio_players()
        self.set_dmx_players()
        self.set_gradient_client()

    def set_gradient_client(self) -> None:
        """Wire GradientClient into PLAYER_HANDLER using settings from node_conf."""
        port = int(self.cm.node_conf['gradient_osc_port'])
        PLAYER_HANDLER.set_gradient_client(port=port, node_uuid=self.cm.node_uuid)

    # Audio functions
    def set_audio_players(self):
        """Set the audio players and audio mixer"""
        # Initialize the audio mixer for this node
        if self.cm.node_hw_outputs.get('audio_outputs'):
            audio_outputs = self.cm.node_hw_outputs['audio_outputs']
            Logger.info(f'Initializing audio mixer with {len(audio_outputs)} outputs')
            
            # Assign a port for the audio mixer
            mixer_id = '0' # TODO: make this a unique identifier for the mixer
            mixer_ports = PORT_HANDLER.assign_ports(['audio_mixer'])
            PORT_HANDLER.add_config_ports(mixer_ports)
            # Start the audio mixer
            try:
                PLAYER_HANDLER.start_audio_mixer(
                    audio_outputs=audio_outputs,
                    port=mixer_ports['audio_mixer'],
                    mixer_id=mixer_id,
                    path=self.cm.node_conf['audiomixer']['path'],
                    args=self.cm.node_conf['audiomixer']['args']
                )
                Logger.info(f'Audio mixer started successfully for mixer {mixer_id}')
                # Register mixer with Controller via NNG
                try:
                    CUE_HANDLER.communications_thread.add_player(f'audiomixer_{mixer_id}', None, timeout=0.1)
                    Logger.info(f'Audio mixer {mixer_id} registered with Controller')
                except Exception as e:
                    Logger.warning(f'Could not register mixer with Controller: {e}')
            except Exception as e:
                Logger.error(f'Error starting audio mixer: {e}')
                Logger.exception(e)
        else:
            Logger.info('No audio outputs detected, skipping audio mixer initialization')
        
        # Build audio output lookup keyed by <id> (mirrors video output pattern)
        audio_outputs = {}
        for port_type_dict in self.cm.node_mappings.get('audio', []):
            for port_type_list in port_type_dict.values():
                for port in port_type_list:
                    for _, output_data in port.items():
                        output_id = str(output_data.get('id', output_data['name']))
                        mappings = output_data.get('mappings', [])
                        mapped_to = mappings[0]['mapped_to'] if mappings else output_data['name']
                        audio_outputs[output_id] = {
                            'name': output_data['name'],
                            'mapped_to': mapped_to,
                        }
        PLAYER_HANDLER.set_audio_outputs(audio_outputs)

        # Set the audio player generator. Append --output-latency-ms
        # from settings.xml when the operator supplied an integer
        # override (isinstance int); "auto" or absent ⇒ audioplayer
        # runs its Phase-3 JACK-latency query path.
        audio_args = _append_output_latency_flag(
            self.cm.node_conf['audioplayer']['args'],
            self.cm.node_conf['audioplayer'],
        )
        PLAYER_HANDLER.set_audio_output_generator(
            self.cm.node_conf['audioplayer']['path'],
            audio_args,
        )

    # Video functions
    def set_video_players(self):
        """Set the video players"""
        Logger.info(f'Setting video players with: {self.cm.node_conf["videoplayer"]}')
        if not self.cm.node_hw_outputs['video_outputs']:
            Logger.info('No video outputs detected.')
            return

        PLAYER_HANDLER.add_node_uuid(self.cm.node_uuid)
        vc_conf = self.cm.node_conf.get('videoplayer', {})
        osc_video_port = int(vc_conf.get('osc_port', VIDEOCOMPOSER_OSC_PORT_DEFAULT))
        PLAYER_HANDLER.set_video_client(osc_video_port)
        PORT_HANDLER.add_config_ports({'videocomposer': osc_video_port})

        # Canvas geometry comes from /run/cuems/display.conf, written by
        # cuems-generate-display-conf (videocomposer's ExecStartPre). It's the
        # same file the videocomposer reads, so engine + VC agree on canvas
        # size and per-output regions without a handshake. The XML's optional
        # <canvas_region> is a UI-template hint (normalized [0,1]) and is
        # ignored here — engine never sources physical layout from XML.
        display_regions, (canvas_w, canvas_h) = read_display_conf()

        video_outputs = {}
        for port_type_dict in self.cm.node_mappings.get('video', []):
            for port_type_list in port_type_dict.values():
                for port in port_type_list:
                    for _, output_data in port.items():
                        output_id = str(output_data.get('id', output_data['name']))
                        name = output_data['name']
                        mappings = output_data.get('mappings', [])
                        mapped_to = mappings[0]['mapped_to'] if mappings else name
                        region = display_regions.get(mapped_to)
                        if region is None:
                            Logger.warning(
                                f"DISPLAY_MISMATCH: XML output id={output_id} "
                                f"name={name!r} maps to {mapped_to!r} which is "
                                f"not in display.conf; skipping. Available: "
                                f"{sorted(display_regions.keys())}"
                            )
                            continue
                        video_outputs[output_id] = {
                            'name': name,
                            'mapped_to': mapped_to,
                            'x': region['x'],
                            'y': region['y'],
                            'width': region['width'],
                            'height': region['height'],
                            'canvas_region': dict(region),
                        }
        PLAYER_HANDLER.start_video_outputs(
            video_outputs, canvas_override=(canvas_w, canvas_h)
        )


    # DMX functions
    def set_dmx_players(self):
        """Set the DMX player for this node and register its endpoints."""
        # Assign a port for the DMX player
        dmx_ports = PORT_HANDLER.assign_ports(['dmx_player'])
        PORT_HANDLER.add_config_ports(dmx_ports)

        # Get node UUID for player naming
        node_uuid = self.cm.node_conf.get('uuid', 'default_node')

        # Start the DMX player
        try:
            # Append --output-latency-ms from settings.xml when an
            # integer override is present. Dmx has no "auto" form —
            # absent ⇒ dmxplayer's 35 ms Phase-5A default stands.
            dmx_args = _append_output_latency_flag(
                self.cm.node_conf['dmxplayer']['args'],
                self.cm.node_conf['dmxplayer'],
            )
            PLAYER_HANDLER.start_dmx_player(
                port=dmx_ports['dmx_player'],
                node_uuid=node_uuid,
                path=self.cm.node_conf['dmxplayer']['path'],
                args=dmx_args,
            )
            try:
                CUE_HANDLER.communications_thread.add_player(f'dmxplayer_{node_uuid}', None, timeout=0.1)
            except Exception:
                pass  # Ignore - NNG is for distributed nodes
            Logger.info(f'DMX player started successfully for node {node_uuid}')
        except Exception as e:
            Logger.error(f'Error starting DMX player: {e}')
            Logger.exception(e)
            return
        
    def quit_dmx_devs(self):
        """Quit the DMX player if it exists"""
        dmx_client = PLAYER_HANDLER.get_dmx_player_client()
        if dmx_client:
            try:
                dmx_client.set_value('/quit', 1)
            except Exception as e:
                Logger.exception(e)
        CUE_HANDLER.communications_thread.remove_player(f'dmxplayer_{self.cm.node_uuid}')


    #########################
    # Project logic
    #########################
    def ready_project(self, project):
        """Prepare the project to be played.

        deploy_project() runs in _load_project_inner BEFORE this point,
        before the teardown of the previous project — so that a deploy
        failure aborts the load without destroying running state.
        Media deploy runs here because it is best-effort: a failure
        logs but does not abort (cached media may already be on disk).
        """
        self.cm.load_project_config(project)
        self.read_script(project)
        self.deploy_media(project)
        self.ensure_video_indexes()
        self.outputs_map = self.map_cue_outputs()
        PLAYER_HANDLER.set_outputs_map(self.outputs_map)
        PORT_HANDLER.clean_random_ports()

    def map_cue_outputs(self, cuelist: CueList = None):
        """Load the output mappings for the project"""
        outputs_map = {}
        if cuelist is None:
            cuelist = self.script.cuelist
        for cue in cuelist.contents:
            if isinstance(cue, CueList):
                outputs_map.update(self.map_cue_outputs(cue))
            elif not isinstance(cue, MediaCue):
                continue

            outputs = [x[1] for x in cue.get_all_output_names() if x[0] == self.cm.node_uuid]
            if outputs:
                outputs_map[cue.id] = outputs
        Logger.debug(f'Outputs map: {outputs_map}')
        return outputs_map

    def load_project(self, project):
        """Load the project files to the node"""
        with self._loading_lock:
            if self._loading:
                Logger.warning(f'Load already in progress, ignoring duplicate load of {project}')
                return
            self._loading = True

        try:
            return self._load_project_inner(project)
        finally:
            with self._loading_lock:
                self._loading = False

    def _load_project_inner(self, project):
        # Don't allow loading while script is running
        if self.get_status('running') == "yes":
            Logger.warning(f'Cannot load project {project} while script is running. Stop first.')
            return False

        # Deploy the critical project files (script.xml, mappings.xml,
        # settings.xml) BEFORE tearing down the previous project. If the
        # controller is unreachable we abort here with the previous
        # project still armed and usable — better than ending up with
        # everything stopped and no new project loaded.
        if not self.deploy_project(project):
            Logger.error(
                f'Project deploy FAILED for {project} — aborting load; '
                f'previous project remains unchanged'
            )
            return False

        gradient_client = PLAYER_HANDLER.get_gradient_client()
        if gradient_client:
            try:
                gradient_client.send_cancel_all()
            except Exception as exc:
                Logger.error(f'gradient send_cancel_all failed on project load: {exc}')
        else:
            Logger.debug('gradient_client not initialised, skipping cancel_all on project load')

        # Stop any running cue threads from the previous project first,
        # so they can't interfere with cleanup (same logic as stop_playback).
        CUE_HANDLER.stop_all_cues()

        # DMX: stop following MTC, blackout all universes.
        dmx_client = PLAYER_HANDLER.get_dmx_player_client()
        if dmx_client:
            try:
                dmx_client.disable_mtcfollow()
            except Exception as e:
                Logger.warning(f'DMX disable mtcfollow failed: {e}')
            try:
                dmx_client.send_blackout()
            except Exception as e:
                Logger.warning(f'DMX blackout failed: {e}')

        # Video: reset videocomposer (remove all layers, cancel loads, reset master).
        self.unload_video_devs()

        # Audio: reset mixer volumes, kill all players, clean up JACK.
        mixer_client = PLAYER_HANDLER.get_audio_mixer_client()
        if mixer_client:
            try:
                mixer_client.reset_volumes()
            except Exception as e:
                Logger.warning(f'JACK volume reset failed: {e}')
        PLAYER_HANDLER.kill_all_audio_players()
        PLAYER_HANDLER.kill_orphaned_audio_processes()
        PLAYER_HANDLER.cleanup_zombie_jack_clients()

        # Disarm all cues from the previous project.
        CUE_HANDLER.disarm_all()
        
        # Obtain the project files (this replaces self.script with new project)
        self.ready_project(project)
        
        # Prepare the script to be played (arms new cues)
        self.ready_script()

        # Start cue dependencies
        # self.set_players()

        # Confirm the project is loaded
        self.set_show_lock_file()
        self.script.unix_name = project
        self.set_status('load', project)
        Logger.info(f'Project {project} loaded')

        # Notify Controller that arming is complete (GO button can go green)
        try:
            from .comms.NodesHub import NodeOperation, OperationType, ActionType
            operation = NodeOperation(
                type=OperationType.STATUS,
                action=ActionType.UPDATE,
                sender=self.cm.node_uuid,
                target='armed_ready',
                data={'armed': 'yes'}
            )
            CUE_HANDLER.communications_thread.send_operation(operation, timeout=0.1)
            Logger.debug('Notified Controller that arming after load is complete')
        except Exception as e:
            Logger.warning(f'Could not notify Controller of armed_ready: {e}')

        # Broadcast initial nextcue to UI
        self._broadcast_nextcue()

        return True

    def deploy_project(self, project):
        """Deploy the project files (script.xml, mappings.xml, settings.xml).

        Critical path: if these fail to sync, the local copy may be stale
        and arming cues against it is unsafe. Caller is expected to abort
        the load on False.
        """
        return self.deploy_manager.sync_files(project, 'project')

    def deploy_media(self, project):
        """Deploy the media files (and their .idx sidecar indexes).

        Best-effort: a failure here is recoverable if media is already
        cached on disk. Returns False to surface the failure to logs,
        but the caller continues the load.
        """
        if not self.script:
            Logger.error('No script loaded')
            return False
        bare_names = self.script.get_own_media_filenames(config=self.cm)
        if len(bare_names) == 0:
            Logger.info('No media files to deploy')
            return True
        # The rsync module 'cuems' maps to /opt/cuems_library on the
        # controller. Media files live in <module>/media/<name>; their
        # .idx sidecars live in <module>/media/indexes/<name>.idx.
        # get_own_media_filenames returns the bare filename, so we
        # prepend the module-relative path here.
        # Also include .idx sidecar files for video assets — rsync with
        # --ignore-missing-args silently skips entries that don't exist
        # on the source, so this is safe even when the index hasn't been
        # created yet.
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.mpg'}
        media_entries = [f'media/{name}' for name in bare_names]
        idx_entries = [
            f'media/indexes/{name}.idx'
            for name in bare_names
            if os.path.splitext(name)[1].lower() in video_exts
        ]
        if not self.deploy_manager.sync_files(project, 'media', media_entries + idx_entries):
            Logger.error(
                f'Media deploy failed for {project} — continuing with cached '
                f'files; cues whose media is missing locally will fail on GO'
            )
            return False
        return True

    def ensure_video_indexes(self):
        """Run cuems-videoindexer on any video files that are missing a .idx sidecar.

        This is a safety net for files that were copied manually or deployed to a
        node that never ran the editor upload hook. For normally-uploaded files the
        index was already created by the editor and this is a no-op.
        """
        if not self.script:
            return
        file_names = self.script.get_own_media_filenames(config=self.cm)
        video_exts = {'.mp4', '.mov', '.avi', '.mkv', '.mpg'}
        unindexed = []
        for name in file_names:
            ext = os.path.splitext(name)[1].lower()
            if ext not in video_exts:
                continue
            full_path = PLAYER_HANDLER.media_path(name)
            idx_dir = os.path.join(os.path.dirname(full_path), 'indexes')
            idx_path = os.path.join(idx_dir, os.path.basename(full_path) + '.idx')
            if not os.path.exists(idx_path):
                unindexed.append(full_path)
        if unindexed:
            Logger.info(f'ensure_video_indexes: indexing {len(unindexed)} video(s) missing .idx')
            try:
                subprocess.run(['cuems-videoindexer'] + unindexed, timeout=600)
            except Exception as e:
                Logger.warning(f'ensure_video_indexes: indexer failed: {e}')

    #########################
    # Nextcue
    #########################
    def _broadcast_nextcue(self):
        """Send the current next_cue_pointer UUID to the Controller via NNG."""
        cue_id = self.next_cue_pointer.id if self.next_cue_pointer else ""
        try:
            CUE_HANDLER.communications_thread.update_nextcue(cue_id, timeout=0.1)
            Logger.debug(f'Broadcast nextcue: {cue_id or "(none)"}')
        except Exception as e:
            Logger.warning(f'Could not broadcast nextcue: {e}')

    def _arm_with_enabled_guard(self, cue, project_gen: int):
        """Arm a cue and disarm if it was disabled or project changed while arming.

        Runs in a daemon thread. After arm() completes, re-checks
        cue.enabled and project generation to handle races where:
        - A disable command arrived while arm_cue() was loading media
        - A stop/reload invalidated this project's cues
        """
        if self._project_generation != project_gen:
            Logger.info(f'Aborting arm of {cue.id} — project generation changed')
            return
        CUE_HANDLER.arm(cue, init=True)
        # If project changed during arm, disarm the stale cue.
        if self._project_generation != project_gen:
            if CUE_HANDLER.find_armed_cue(cue):
                CUE_HANDLER.disarm(cue)
            Logger.info(f'Disarmed cue {cue.id} — project changed during async arm')
            return
        # If cue was disabled while we were arming, disarm now.
        if not cue.enabled and CUE_HANDLER.find_armed_cue(cue):
            CUE_HANDLER.disarm(cue)
            Logger.info(f'Disarmed cue {cue.id} — disabled during async arm')

    def _action_result_sink(self, outcome: dict):
        """Custom result sink for ActionHandler — extends default with cue_enabled sync."""
        from .cues.ActionHandler import ACTION_HANDLER
        # Always run default behavior (sends action_cue_outcome via NNG)
        ACTION_HANDLER._default_result_sink(outcome)

        # If an enable/disable action was applied, notify Controller
        action_type = outcome.get('action_type')
        status = outcome.get('status')
        if action_type in ('enable', 'disable') and status == 'applied':
            target_id = outcome.get('target_id')
            if target_id:
                self._notify_cue_enabled(target_id, action_type == 'enable')

    def _notify_cue_enabled(self, cue_id: str, enabled: bool):
        """Send cue enabled status to Controller via NNG."""
        from .comms.NodesHub import NodeOperation, OperationType, ActionType
        try:
            operation = NodeOperation(
                type=OperationType.STATUS,
                action=ActionType.UPDATE,
                sender=self.cm.node_uuid if hasattr(self, 'cm') and self.cm else 'node',
                target='cue_enabled',
                data={'cue_id': cue_id, 'enabled': enabled}
            )
            CUE_HANDLER.communications_thread.send_operation(operation, timeout=0.1)
        except Exception as e:
            Logger.warning(f'Could not notify cue_enabled: {e}')

    def set_next_cue(self, value):
        """Handle setnextcue command from the UI — override next_cue_pointer."""
        if not self.script:
            Logger.warning('No script loaded, cannot set next cue.')
            return
        cue = self.script.find(value)
        if cue:
            self.next_cue_pointer = cue
            if not CUE_HANDLER.find_armed_cue(cue):
                Logger.info(f'Re-arming cue {cue.id} selected as next cue')
                CUE_HANDLER.arm(cue, init=True)
            CUE_HANDLER._arm_ahead(cue)  # extend window from selected cue
            self._broadcast_nextcue()
            Logger.info(f'Next cue overridden by UI: {value}')
        else:
            Logger.warning(f'setnextcue: cue {value} not found in script')

    def _handle_cue_enabled(self, value):
        """Handle cue_enabled toggle from Controller.

        Value format: "<cue_id> <0|1>" (space-separated UUID and enabled flag).
        """
        if not self.script:
            Logger.warning('No script loaded, cannot toggle cue enabled')
            return

        if not value or not isinstance(value, str):
            Logger.warning(f'Invalid cue_enabled value: {repr(value)}')
            return

        parts = value.split(' ', 1)
        if len(parts) != 2 or parts[1] not in ('0', '1'):
            Logger.warning(f'Invalid cue_enabled format: {repr(value)}')
            return

        cue_id, enabled_str = parts
        enabled = enabled_str == '1'

        cue = self.script.find(cue_id)
        if not cue:
            Logger.warning(f'cue_enabled: cue {cue_id} not found in script')
            return

        cue.enabled = enabled

        if not enabled:
            # Disarm only if armed and NOT currently playing.
            # A playing cue has a running go thread (_go_generation > 0) and is still loaded.
            is_playing = (getattr(cue, '_go_generation', 0) > 0
                          and getattr(cue, 'loaded', False))
            if CUE_HANDLER.find_armed_cue(cue) and not is_playing:
                CUE_HANDLER.disarm(cue)
                Logger.info(f'Disarmed disabled cue {cue_id}')
            # Recalculate next_cue_pointer if the disabled cue was next
            if self.next_cue_pointer and self.next_cue_pointer.id == cue_id:
                self.next_cue_pointer = cue.get_next_cue()
                self._broadcast_nextcue()
                Logger.info(f'Next cue was disabled, advanced to {self.next_cue_pointer.id if self.next_cue_pointer else "none"}')
        else:
            # Re-arm in a daemon thread to avoid blocking _command_lock
            # (arm() is slow — media loading, process spawning).
            if cue._local and not CUE_HANDLER.find_armed_cue(cue):
                gen = self._project_generation
                threading.Thread(
                    target=self._arm_with_enabled_guard,
                    args=(cue, gen),
                    daemon=True,
                    name=f'ReArm:{cue_id}'
                ).start()
                Logger.info(f'Re-arming enabled cue {cue_id} (async)')

        self._notify_cue_enabled(cue_id, enabled)
        Logger.info(f'Cue {cue_id} set to {"enabled" if enabled else "disabled"}')

    #########################
    # Script logic
    #########################
    def ready_script(self):
        """Check if the script is ready to be played"""
        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return
        
        self.ongoing_cue = None
        self.next_cue_pointer = None
        self.go_offset = 0
        self._project_generation += 1  # Abort in-flight daemon arm threads
        self.unload_video_devs()
        CUE_HANDLER.disarm_all()
        
        # Reset mixer volumes to default when preparing script
        mixer_client = PLAYER_HANDLER.get_audio_mixer_client()
        if mixer_client:
            mixer_client.reset_volumes()
        
        self.initial_cuelist_process()

        # Set initial nextcue to the first enabled cue in the script
        if self.script.cuelist.contents:
            first_enabled = None
            for c in self.script.cuelist.contents:
                if c.enabled:
                    first_enabled = c
                    break
            self.next_cue_pointer = first_enabled

        Logger.info(f'Script {self.script.name} loaded and ready to be played')

    def go_script(self, value):
        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return

        if not self.with_mtc:
            Logger.warning('No MTC listener, cannot process GO command.')
            return

        # Determine the cue to go
        if not self.ongoing_cue:
            # First GO - use next_cue_pointer (may have been overridden by setnextcue)
            cue_to_go = self.next_cue_pointer or self.script.cuelist.contents[0]
            Logger.info(f'GO command received. Starting script {self.script.name}')
        else:
            # Successive GO - advance to next cue
            if self.next_cue_pointer:
                cue_to_go = self.next_cue_pointer
                Logger.info(f'GO command received. Advancing to next cue: {cue_to_go.id}')
            else:
                # No next cue - script has finished. Do not stop timecode or reset state.
                Logger.info('No more cues. Press STOP to restart.')
                return

        if not cue_to_go._local:
            Logger.info(f'Actual cue outside node space. CUE : {cue_to_go.id}')
            return

        if not cue_to_go.enabled:
            Logger.info(f'Cue {cue_to_go.id} is disabled, advancing to next enabled cue')
            self.next_cue_pointer = cue_to_go.get_next_cue()
            self._broadcast_nextcue()
            return

        if not CUE_HANDLER.find_armed_cue(cue_to_go):
            Logger.info(f'Cue {cue_to_go.id} not armed, re-arming before GO')
            CUE_HANDLER.arm(cue_to_go, init=True)
            if not CUE_HANDLER.find_armed_cue(cue_to_go):
                Logger.error(f'Failed to re-arm cue {cue_to_go.id}, cannot GO')
                return

        # Update state
        self.set_status('running', "yes")
        self.ongoing_cue = cue_to_go
        
        # Start the cue
        main_thread = CUE_HANDLER.go(
            cue_to_go,
            self.mtc_listener
        )
        
        # Update next cue pointer
        self.next_cue_pointer = self.ongoing_cue.get_next_cue()
        # Drift baseline; consumed by BaseEngine.timecode = mtc - go_offset.
        # _exact for sub-ms precision at NTSC framerates.
        self.go_offset = self.mtc_listener.main_tc.milliseconds_exact

        # Broadcast nextcue to UI
        self._broadcast_nextcue()

        Logger.info(f'Cue {cue_to_go.id} started. Next cue: {self.next_cue_pointer.id if self.next_cue_pointer else "none"}')

    def stop_playback(self, value=None):
        """Stop playback, full cleanup, then re-arm so GO is available again.
        
        Does the cleanup that ready_script() doesn't handle (DMX blackout,
        disconnect video, kill audio), then delegates reset + re-arm to
        ready_script(). Notifies Controller when armed (GO button green).
        """
        Logger.info('STOP command received. Stopping playback.')

        self.set_status('running', "no")

        gradient_client = PLAYER_HANDLER.get_gradient_client()
        if gradient_client:
            try:
                gradient_client.send_cancel_all()
            except Exception as exc:
                Logger.error(f'gradient send_cancel_all failed on stop: {exc}')
        else:
            Logger.debug('gradient_client not initialised, skipping cancel_all on stop')

        # Signal all running cue threads to stop immediately.
        # Must happen BEFORE blackout/reset so loop_cue threads don't
        # re-push DMX frames or send /visible after cleanup.
        CUE_HANDLER.stop_all_cues()
        sleep(0.05)  # 50ms — loop_cue polls every 20ms

        # DMX: disable MTC following first (freezes the playhead so queued
        # scenes can't fire), then blackout via OLA for instant visual reset.
        dmx_client = PLAYER_HANDLER.get_dmx_player_client()
        if dmx_client:
            try:
                dmx_client.disable_mtcfollow()
            except Exception as e:
                Logger.warning(f'DMX disable mtcfollow failed: {e}')
            try:
                dmx_client.send_blackout()
            except Exception as e:
                Logger.warning(f'DMX blackout failed: {e}')
        
        # Unload all video layers (instant visual blackout)
        self.unload_video_devs()
        
        # Kill all audio players (ready_script does not do this)
        PLAYER_HANDLER.kill_all_audio_players()
        PLAYER_HANDLER.cleanup_zombie_jack_clients()

        # Reset state + disarm + volume reset + re-arm cues
        if self.script:
            self.ready_script()
            Logger.info(f'Project {self.script.name} reset and ready for GO.')
            
            # Notify Controller that re-arm is complete (GO button can go green)
            try:
                from .comms.NodesHub import NodeOperation, OperationType, ActionType
                operation = NodeOperation(
                    type=OperationType.STATUS,
                    action=ActionType.UPDATE,
                    sender=self.cm.node_uuid,
                    target='armed_ready',
                    data={'armed': 'yes'}
                )
                CUE_HANDLER.communications_thread.send_operation(operation, timeout=0.1)
                Logger.debug('Notified Controller that re-arm is complete')
            except Exception as e:
                Logger.warning(f'Could not notify Controller of armed_ready: {e}')

            # Broadcast nextcue (reset to first cue after stop)
            self._broadcast_nextcue()
        else:
            Logger.info('Playback stopped (no script loaded).')
        
        Logger.info('Playback stopped.')


## MISCELLANEOUS FUNCTIONS ##

# helper functions
def is_int(value: any) -> bool:
    """Check if a value is an integer"""
    try:
        int(value)
        return True
    except ValueError:
        return False

def get_config_ports(node_conf: dict) -> dict:
    """Create a dict of ports from the config"""
    k = [i for i in node_conf.keys() if 'port' in i and is_int(node_conf[i])]
    v = [int(node_conf[i]) for i in k]
    return dict(zip(k, v))


def redirect_audio_cmd(path_parts: list[str], value: str) -> None:
    """Redirect the audio command to the audio player"""
    if path_parts[0] == 'mixer':
        redirect_audio_mixer_cmd(path_parts[1:], value)
    elif path_parts[0] == 'cue':
        redirect_audio_player_cmd(path_parts[1:], value)
    else:
        Logger.error(f'Invalid audio command: {path_parts}')
        return

def redirect_audio_mixer_cmd(path_parts: list[str], value: str) -> None:
    """Redirect the audio mixer command to the audio mixer
     Follows the logic:
     <output_index>/master/volume -> /audiomixer/0_mixer/master
     <output_index>/0/volume -> /audiomixer/0_mixer/0
     <output_index>/1/volume -> /audiomixer/0_mixer/1
     ...
    Args:
        path_parts: List of path parts
        value: Value to set
    """
    output_index, channel, _ = path_parts
    mixer_cmd = f'/audiomixer/0_mixer/{channel}'
    PLAYER_HANDLER.get_audio_mixer_client().set_value(mixer_cmd, value)

def redirect_audio_player_cmd(path_parts: list[str], value: str) -> None:
    """Redirect the audio mixer command to the audio mixer
     Follows the logic:
     <cue_uuid>/master/volume -> /volmaster
     <cue_uuid>/0/volume -> /vol0
     <cue_uuid>/1/volume -> /vol1
     ...
    
    Args:
        path_parts: List of path parts
        value: Value to set
    """
    cue_uuid, channel, _ = path_parts
    audio_cmd = f'/vol{channel}'
    cue = CUE_HANDLER.get_armed_cue(cue_uuid)
    if not cue:
        Logger.error(f'Cue {cue_uuid} not found')
        return
    client: AudioClient = cue._osc
    client.set_value(audio_cmd, value)

def redirect_dmx_cmd(path_parts: list[str], value: str) -> None:
    """Redirect the DMX command to the DMX player"""
    dmx_index = path_parts.index('mixer') + 1 # +1 to skip the 'mixer' keyword
    dmx_cmd = '/' + '/'.join(path_parts[dmx_index:])
    client: DmxClient = PLAYER_HANDLER.get_dmx_player_client()
    client.set_value(dmx_cmd, value)

def redirect_video_cmd(path_parts: list[str], value: str) -> None:
    """Redirect the video command to the video client"""
    videocomposer_index = path_parts.index('videocomposer')
    videocomposer_cmd = '/' + '/'.join(path_parts[videocomposer_index:])
    client: VideoClient = PLAYER_HANDLER.get_video_client()
    client.set_value(videocomposer_cmd, value)
