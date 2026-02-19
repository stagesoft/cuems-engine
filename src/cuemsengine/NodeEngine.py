from functools import partial
from time import sleep

from cuemsutils.cues import CueList, VideoCue, AudioCue, DmxCue
from cuemsutils.cues.MediaCue import MediaCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine
from .cues.CueHandler import CUE_HANDLER
from .osc.endpoints import OSC_VIDEOPLAYER_CONF, OSC_DMXPLAYER_CONF
from .osc.helpers import add_callback_to_all, add_prefix_to_all
from .tools.CuemsDeploy import CuemsDeploy
from .tools.PortHandler import PORT_HANDLER
from .players import AudioClient, DmxClient, VideoClient
from .players.PlayerHandler import PLAYER_HANDLER


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
        self.nng_hub_address = f"tcp://{self.controller_ip}:{self.cm.node_conf['nng_hub_port']}"
        PORT_HANDLER.add_system_ports()
        if hasattr(self, 'cm'):
            PORT_HANDLER.add_config_ports(
                get_config_ports(self.cm.node_conf)
            )
            self.deploy_manager = CuemsDeploy(
                library_path=self.cm.library_path,
                tmp_path=self.cm.tmp_path
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
            self.quit_video_devs()
            self.disconnect_video_devs()
            PLAYER_HANDLER.reset_video_players()
            Logger.info('Quitted video devs')
        except Exception as e:
            Logger.warning(f'Exception raised when quitting video devs: {e}')

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
        
        # Set the audio player generator
        PLAYER_HANDLER.set_audio_output_generator(
            self.cm.node_conf['audioplayer']['path'],
            self.cm.node_conf['audioplayer']['args']
        )

    # Video functions
    def set_video_players(self):
        """Set the video players"""
        Logger.info(f'Setting video players with: {self.cm.node_conf["videoplayer"]}')
        if not self.cm.node_hw_outputs['video_outputs']:
            Logger.info('No video outputs detected.')
            return
        
        output_names = self.cm.node_hw_outputs['video_outputs']
        output_ports = []
        for index in range(len(output_names)):
            ports = PORT_HANDLER.assign_ports([
                f'video_player_{index}_0',
                f'video_player_{index}_1'
            ])
            PORT_HANDLER.add_config_ports(ports)
            output_ports.append(ports)

        try:
            PLAYER_HANDLER.start_video_outputs(
                output_names,
                output_ports,
                self.cm.node_conf['videoplayer']['path'],
                self.cm.node_conf['videoplayer']['args']
            )
        except Exception as e:
            Logger.error(f'Error checking & starting video devices...')
            Logger.error(e)
            Logger.error(f'Exiting...')
            exit(-1)
        
        for output in PLAYER_HANDLER._video_players.keys():
            try:
                CUE_HANDLER.communications_thread.add_player(f'videoplayer_{output}', None, timeout=0.1)
            except Exception:
                pass  # Ignore - NNG is for distributed nodes

    def quit_video_devs(self):
        try:
            PLAYER_HANDLER.quit_videocomposer()
            Logger.info('Videocomposer quit successfully')
        except Exception as e:
            Logger.exception(e)

    def disconnect_video_devs(self):
        try:
            PLAYER_HANDLER.disconnect_video_midi()
            Logger.info('Videocomposer disconnected successfully')
        except Exception as e:
            Logger.exception(e)

    def unload_video_devs(self):
        try:
            PLAYER_HANDLER.reset_video_layers()
            Logger.info('Video layers unloaded successfully')
        except Exception as e:
            Logger.exception(e)

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
            PLAYER_HANDLER.start_dmx_player(
                port=dmx_ports['dmx_player'],
                node_uuid=node_uuid,
                path=self.cm.node_conf['dmxplayer']['path'],
                args=self.cm.node_conf['dmxplayer']['args']
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
        """Prepare the project to be played"""
        self.deploy_project(project)
        self.cm.load_project_config(project)
        self.read_script(project)
        self.deploy_media(project)
        self.outputs_map = self.map_cue_outputs()
        PLAYER_HANDLER.set_outputs_map(self.outputs_map)
        # Reset video loaded tracking for new project (xjadeo workaround)
        PLAYER_HANDLER.reset_video_loaded_outputs()
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
        # Don't allow loading while script is running
        if self.get_status('running') == "yes":
            Logger.warning(f'Cannot load project {project} while script is running. Stop first.')
            return

        # FIRST: Clean up any existing audio players from the previous project
        # This MUST happen BEFORE ready_project() which replaces self.script
        # Otherwise the old cue objects are orphaned and their players never get killed
        Logger.debug('Cleaning up previous project resources before loading new one')
        PLAYER_HANDLER.kill_all_audio_players()
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
        return True

    def deploy_project(self, project):
        """Deploy the project files to the node"""
        self.deploy_manager.sync_files(project, 'project')

    def deploy_media(self, project):
        """Deploy the media files to the node"""
        if not self.script:
            Logger.error('No script loaded')
            return
        file_names = self.script.get_own_media_filenames(config=self.cm)
        if len(file_names) == 0:
            Logger.info('No media files to deploy')
            return
        self.deploy_manager.sync_files(project, 'media', file_names)

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
        self.unload_video_devs()
        CUE_HANDLER.disarm_all()
        
        # Reset mixer volumes to default when preparing script
        mixer_client = PLAYER_HANDLER.get_audio_mixer_client()
        if mixer_client:
            mixer_client.reset_volumes()
        
        self.initial_cuelist_process()
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
            # First GO - start from beginning
            cue_to_go = self.script.cuelist.contents[0]
            Logger.info(f'GO command received. Starting script {self.script.name}')
        else:
            # Successive GO - advance to next cue
            if self.next_cue_pointer:
                cue_to_go = self.next_cue_pointer
                Logger.info(f'GO command received. Advancing to next cue: {cue_to_go.id}')
            else:
                # No next cue - script has finished (or remaining cues auto-chain)
                # Reset state same as STOP does, ready for next GO
                Logger.info(f'Script finished. Resetting for next GO.')
                self.set_status('running', 'no')
                self.ongoing_cue = None
                self.next_cue_pointer = None
                
                # Notify Controller that script finished (so it can update its own status)
                try:
                    from .comms.NodesHub import NodeOperation, OperationType, ActionType
                    operation = NodeOperation(
                        type=OperationType.STATUS,
                        action=ActionType.UPDATE,
                        sender=self.cm.node_uuid,
                        target='script_finished',
                        data={'running': 'no'}
                    )
                    CUE_HANDLER.communications_thread.send_operation(operation, timeout=0.1)
                    Logger.debug('Notified Controller that script finished')
                except Exception as e:
                    Logger.warning(f'Could not notify Controller of script finish: {e}')
                
                self.ready_script()  # Re-arm all cues like STOP does
                # Return here - next GO will start from beginning (arming is async)
                return

        if not cue_to_go._local:
            Logger.info(f'Actual cue outside node space. CUE : {cue_to_go.id}')
            return

        if not CUE_HANDLER.find_armed_cue(cue_to_go):
            Logger.error(f'Trying to go a cue that is not yet loaded. CUE : {cue_to_go.id}')
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
        self.go_offset = self.mtc_listener.main_tc.milliseconds

        # OSCQuery status notification
        if self.next_cue_pointer:
            next_cue = self.next_cue_pointer.id
        else:
            next_cue = ""

        Logger.info(f'Cue {cue_to_go.id} started. Next cue: {next_cue if next_cue else "none"}')
        
        # Start a watcher thread to detect when playback completes naturally
        def watch_playback_completion():
            """Wait for main cue thread to finish and update status."""
            main_thread.join()
            # Only reset if we're still marked as running (not stopped manually)
            if self.get_status('running') == 'yes':
                Logger.info('Playback completed naturally. Resetting status.')
                self.set_status('running', 'no')
                self.ongoing_cue = None
                self.next_cue_pointer = None
                
                # Notify Controller that script finished
                try:
                    from .comms.NodesHub import NodeOperation, OperationType, ActionType
                    operation = NodeOperation(
                        type=OperationType.STATUS,
                        action=ActionType.UPDATE,
                        sender=self.cm.node_uuid,
                        target='script_finished',
                        data={'running': 'no'}
                    )
                    CUE_HANDLER.communications_thread.send_operation(operation, timeout=0.1)
                    Logger.debug('Notified Controller that script finished')
                except Exception as e:
                    Logger.warning(f'Could not notify Controller of script finish: {e}')
                
                self.ready_script()  # Re-arm all cues like STOP does
        
        from threading import Thread
        watcher = Thread(target=watch_playback_completion, daemon=True)
        watcher.start()

    def stop_playback(self, value=None):
        """Stop playback and reset to ready state.
        
        This stops playback and resets the project so it's ready for GO again.
        """
        Logger.info('STOP command received. Stopping playback.')
        
        # Disconnect all video players from MIDI
        self.disconnect_video_devs()
        
        # Update status
        self.set_status('running', "no")
        
        # Reset script state so GO can work again from the beginning
        if self.script:
            self.ready_script()
            Logger.info(f'Project {self.script.name} reset and ready for GO.')
        else:
            # Just disarm if no script loaded
            CUE_HANDLER.disarm_all()
        
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
