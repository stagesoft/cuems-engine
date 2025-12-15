from functools import partial
from pyossia import GlobalMessageQueue
from threading import Thread
from time import sleep

from cuemsutils.cues import CueList, VideoCue, AudioCue, DmxCue, MediaCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine
from .cues.CueHandler import CUE_HANDLER
from .osc.OssiaClient import PlayerClient
from .osc.endpoints import OSC_VIDEOPLAYER_CONF, OSC_DMXPLAYER_CONF
from .osc.helpers import add_callback_to_all, add_prefix_to_all
from .tools.CuemsDeploy import CuemsDeploy
from .tools.PortHandler import PORT_HANDLER
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
        self.ocsquery_queue_loop = Thread(
            target=self.oscquery_loop, name='OSCQueryQueueLoop'
        )

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
        self.set_oscquery_comms()
        self.set_players()
        self.mtc_listener.start()
        super().start()
        
    @logged
    def stop(self):
        self.stop_requested = True
        self.stop_node_engine()
        if self.ocsquery_queue_loop.is_alive():
            self.ocsquery_queue_loop.join(timeout=1)
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
        """Set the OSCQuery commands for the NodeEngine"""
        self.commands_dict = {
            'deploy': self.ready_project,
            # Not a node responsibility
            # 'hwdiscovery': None, # self.hw_discovery_callback,
            'load': self.load_project,
            'loadcue': None, # self.load_cue,
            'go': self.go_script,
            'gocue': self.go_script, # self.go_cue_callback,
            'pause': None, # self.pause_callback,
            # 'preload': None, # self.load_cue_callback,
            'resetall': None, # self.reset_all_callback,
            'stop': None, # self.stop_callback,
            'test': None, # self.test_callback
            'unload': None, # self.unload_cue_callback,
            'update': None, # self.update_player_endpoints,
        }
        self.oscquery_client = self.set_oscquery_client()
        self.oscquery_queue = GlobalMessageQueue(self.oscquery_client.device)
        self.ocsquery_queue_loop.start()
    
    def oscquery_loop(self):
        while not self.stop_requested:
            message = self.oscquery_queue.pop()
            if message is not None:
                parameter, value = message
                self.route_message(parameter, value)
            else:
                sleep(0.001)

    def route_message(self, parameter, value):
        # Exclude 'engine' common node
        path_elements = str(parameter.node).split('/')[2:]
        Logger.debug(f'Routing message: {path_elements}')
        if path_elements[0] == 'command':
            self.run_command(path_elements[1], value)
        if path_elements[0] == 'players':
            # Exclude other nodes' players
            if path_elements[1] != self.cm.node_uuid:
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
        if command in self.commands_dict.keys():
            self.commands_dict[command](value)
            return True
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
            CUE_HANDLER.communications_thread.add_player(f'videoplayer_{output}', None)

    def quit_video_devs(self):
        for dev in PLAYER_HANDLER.get_video_players():
            try:
                dev['osc'].set_value('/jadeo/cmd', 'quit')
            except Exception as e:
                Logger.exception(e)

        for output in PLAYER_HANDLER._video_players.keys():
            CUE_HANDLER.communications_thread.remove_player(f'videoplayer_{output}')

    def disconnect_video_devs(self):
        for dev in PLAYER_HANDLER.get_video_players():
            try:
                dev['osc'].set_value('/jadeo/cmd', 'midi disconnect')
            except Exception as e:
                Logger.exception(e)

    def unload_video_devs(self):
        for dev in PLAYER_HANDLER.get_video_players():
            try:
                dev['osc'].set_value('/jadeo/load', '')
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
            CUE_HANDLER.communications_thread.add_player(f'dmxplayer_{node_uuid}', None)
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
        if self.get_status('load') == project:
            Logger.info(f'Project {project} already loaded')
            return

        # Obtain the project files
        self.ready_project(project)
        
        # Prepare the script to be played
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
        self.initial_cuelist_process()
        Logger.info(f'Script {self.script.name} loaded and ready to be played')

    def go_script(self, value):
        if self.get_status('running') == "yes":
            Logger.info(f'Script already running. Current cue: {self.ongoing_cue.id}')
            return

        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return

        if not self.with_mtc:
            Logger.warning('No MTC listener, cannot process GO command.')
            return

        # Signal go start
        Logger.info(f'GO command received. Starting script {self.script.name}')
        self.set_status('running', "yes")

        # Get the cue to go
        if not self.ongoing_cue:
            cue_to_go = self.script.cuelist.contents[0]
        else:
            if self.next_cue_pointer:
                cue_to_go = self.next_cue_pointer
            else:
                Logger.info(f'Reached end of script. Last cue was {self.ongoing_cue.__class__.__name__} {self.ongoing_cue.id}')
                self.ready_script()
                return

        if not cue_to_go._local:
            Logger.info(f'Actual cue outside node space. CUE : {cue_to_go.id}')
            return

        if not CUE_HANDLER.find_armed_cue(cue_to_go):
            Logger.error(f'Trying to go a cue that is not yet loaded. CUE : {cue_to_go.id}')
            return
        self.ongoing_cue = cue_to_go
    #    self.oscquery_server.set_value('/engine/status/currentcue', self.ongoing_cue.id)
        main_thread = CUE_HANDLER.go(
            cue_to_go,
            self.mtc_listener
        )
        self.next_cue_pointer = self.ongoing_cue.get_next_cue()
        self.go_offset = self.mtc_listener.main_tc.milliseconds

        # OSCQuery status notification
        if self.next_cue_pointer:
            next_cue = self.next_cue_pointer.id
        else:
            next_cue = ""

        CUE_HANDLER.wait_for_cue(main_thread)

        Logger.info(f'go_script reached end of script')
    #    self.oscquery_server.set_value('/engine/status/nextcue', next_cue)


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
    client: PlayerClient = cue._osc
    client.set_value(audio_cmd, value)

def redirect_dmx_cmd(path_parts: list[str], value: str) -> None:
    """Redirect the DMX command to the DMX player"""
    dmx_index = path_parts.index('mixer') + 1 # +1 to skip the 'mixer' keyword
    dmx_cmd = '/' + '/'.join(path_parts[dmx_index:])
    PLAYER_HANDLER.get_dmx_player_client().set_value(dmx_cmd, value)

def redirect_video_cmd(path_parts: list[str], value: str) -> None:
    """Redirect the video command to the video player at front"""
    jadeo_index = path_parts.index('jadeo')
    jadeo_cmd = '/' + '/'.join(path_parts[jadeo_index:])
    output_index = path_parts[jadeo_index - 1]
    output_name = PLAYER_HANDLER.get_video_output_names(int(output_index))
    output_player = PLAYER_HANDLER.get_active_videoplayer(output_name)
    if not output_player:
        Logger.error(f'No active video player found for output {output_name} at index {output_index}')
        return None
    client: PlayerClient = output_player['osc']
    client.set_value(jadeo_cmd, value)
