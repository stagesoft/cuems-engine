from functools import partial
from typing import Any

from cuemsutils.cues import CueList, VideoCue, AudioCue, DmxCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine, NODE_ENGINE_PORT
from .cues.CueHandler import CUE_HANDLER
from .osc import ENGINE_CMD_ENDPOINTS
from .osc.OssiaClient import PlayerClient
from .osc.endpoints import OSC_VIDEOPLAYER_CONF, OSC_DMXPLAYER_CONF
from .osc.helpers import add_callbacks_from_dict, add_callback_to_all, add_prefix_to_all
from .tools.CuemsDeploy import CuemsDeploy
from .tools.communicate import NodeCommunications
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
        self.set_communications()
        self.set_video_players()
        self.set_audio_players()
        self.set_dmx_players()
        self.mtc_listener.start()
        super().start()
        
    @logged
    def stop(self):
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

    # OSCQuery functions
    def set_communications(self):
        """Set the communications infrastructure"""
        Logger.info("Starting communications for Node")
        if hasattr(self, 'cm') and self.cm:
            node_host = self.cm.node_conf['host']
        else:
            node_host = CONTROLLER_HOST
        osc_hub_address = f"tcp://{self.node_host}:{NODE_ENGINE_PORT}"
        self.communications_thread = NodeCommunications(
            osc_hub_address=osc_hub_address,
            commands_dict=self.commands_dict
        )
        self.communications_thread.start()

    def apply_oscquery_commands(self):
        cmd_dict = {
            'deploy': self.ready_project,
            # Not a node responsibility
            # 'hwdiscovery': None, # self.hw_discovery_callback,
            'load': self.load_project,
            'loadcue': None, # self.load_cue,
            #'go': self.go_script,
            'gocue': self.go_script, # self.go_cue_callback,
            'pause': None, # self.pause_callback,
            # 'preload': None, # self.load_cue_callback,
            'resetall': None, # self.reset_all_callback,
            'stop': None, # self.stop_callback,
            'test': None, # self.test_callback
            'unload': None, # self.unload_cue_callback,
            'update': None, # self.update_player_endpoints,
        }
        # Add the node endpoints with callbacks
        endpoints = add_callbacks_from_dict(
             ENGINE_CMD_ENDPOINTS,
        #    add_prefix_to_all(ENGINE_CMD_ENDPOINTS, '/node'),
            cmd_dict
        )
        #self.oscquery_server.create_endpoints(endpoints)
        # # Add the controller endpoints without callbacks
        # endpoints.update(
        #     add_prefix_to_all(
        #         ENGINE_CMD_ENDPOINTS,
        #         '/controller'
        #     )
        # )
        Logger.debug(f"OscQuery Node endpoints: {endpoints}")
        #self.mirror_nodes_on_controller(self.oscquery_client)
        self.oscquery_client.create_endpoints(endpoints)

    def mirror_nodes_on_controller(self, client):
        """Mirror the nodes from the NodeEngines to the Controller"""
        # Set the callbacks client for the nodes
        Logger.debug(f'Mirroring nodes from {client} to the Controller')
        endpoints = client.get_endpoints()
        self.oscquery_server.add_endpoints(endpoints)
        for node in client.nodes.values():
            if "status" in str(node):
                Logger.debug(f'ignoring node : {str(node)}')
                continue
            client.set_node_callback(node, self.client_to_server_values)
        Logger.debug(f'Altered endpoints: {client.get_endpoints()}')

    def update_controller_endpoints(self):
        """Update the controller endpoints"""
        ## TODO: Set the host from the config
        host = 'localhost'
        
        self.oscquery_server.set_value(
            '/controller/engine/command/update',
            host
        )

    def set_oscquery_values(self, values: dict):
        for key, value in values.items():
            self.oscquery_client.set_value(key, value)

    def add_player_endpoints(self, cue: Cue, prefix: str):
        if not hasattr(cue, '_osc') or not isinstance(cue._osc, PlayerClient):
            Logger.error(f'Cue {cue.id} does not have a player client')
            return

        # Get the player client
        client: PlayerClient = cue._osc

        # Add the prefix to the endpoints
        prefix = self.build_player_prefix(cue, prefix)

        # Register the endpoints in the server
        self.add_player_nodes_to_local(client, prefix)
        # Notify the controller to update the endpoints
        #self.update_controller_endpoints()

    def remove_player_endpoints(self, cue_id: str):
        if not CUE_HANDLER.find_cue(cue_id):
            Logger.error(f'Cue {cue_id} not found')
            return

        ## DEV: Remove the player endpoints from the server
        return

    def build_player_prefix(self, cue: Cue, prefix: str = None) -> str:
        """Build the player prefix for a given cue"""
        if not cue.id:
            Logger.error('Cue has no id for building player prefix')
            return ''
        if not prefix:
            prefix = ''
        return f'{prefix}/{cue.id}'

    # Project functions
    def ready_project(self, project):
        """Prepare the project to be played"""
        self.deploy_project(project)
        self.cm.load_project_config(project)
        self.read_script(project)
        self.deploy_media(project)
        PORT_HANDLER.clean_random_ports()

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
        self.set_video_players()
        self.set_audio_players()
        self.set_dmx_players()

        # Check local cues
        # self.check_local_cues(self.script.cuelist)

        # Confirm the project is loaded
        self.set_show_lock_file()
        self.script.unix_name = project
        self.set_status('load', project)
        Logger.info(f'Project {project} loaded')

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

    # Check functions
    def check_local_cues(self, cuelist: CueList):
        """Check the local cues and ensure that the _local attribute is set to True"""
        if not hasattr(cuelist, 'contents') or not cuelist.contents:
            Logger.info('No cues to check')
            return

        for cue in cuelist.contents:
            # ignore return value found in check_mappings
            _ = cue.check_mappings(self.cm)
            if cue._local and cue.autoload:
                if isinstance(cue, VideoCue):
                    continue
                CUE_HANDLER.arm(cue, True)
            if isinstance(cue, CueList):
                self.check_local_cues(cue)

    def check_audio_devs(self):
        pass

    def check_dmx_devs(self):
        pass

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

        # Set the video endpoints
        endpoints = {}
        redirect_fn = partial(NodeEngine.redirect_video_cmd, self)
        for index in range(len(output_names)):
            x = add_prefix_to_all(
                OSC_VIDEOPLAYER_CONF,
                f'/players/video/{index}'
            )
            x = add_callback_to_all(x, redirect_fn)
            endpoints.update(x)
        self.oscquery_server.create_endpoints(endpoints)
        #self.update_controller_endpoints()

    def quit_video_devs(self):
        for dev in PLAYER_HANDLER.get_video_players():
            try:
                dev['osc'].set_value('/jadeo/cmd', 'quit')
            except Exception as e:
                Logger.exception(e)

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
            Logger.info(f'DMX player started successfully for node {node_uuid}')
        except Exception as e:
            Logger.error(f'Error starting DMX player: {e}')
            Logger.exception(e)
            return
        
        # Register DMX player endpoints on OSCQuery server
        # This allows other nodes to send DMX commands to this node's DMX player
        try:
            # Get the DMX player client
            dmx_client = PLAYER_HANDLER.get_dmx_player_client()
            if dmx_client:
                # Register DMX player endpoints using the same mechanism as Audio
                # This creates callbacks that forward OSCQuery server values to the DMX player client
                prefix = f'/dmxplayer/{node_uuid}'
                self.add_player_nodes_to_local(dmx_client, prefix)
                Logger.info(f'DMX player endpoints registered on OSCQuery server: {prefix}')
                
        except Exception as e:
            Logger.error(f'Error registering DMX player endpoints: {e}')
            Logger.exception(e)

    def quit_dmx_devs(self):
        """Quit the DMX player if it exists"""
        dmx_client = PLAYER_HANDLER.get_dmx_player_client()
        if dmx_client:
            try:
                dmx_client.set_value('/quit', 1)
            except Exception as e:
                Logger.exception(e)

    def redirect_video_cmd(self, path: str, value: str) -> None:
        """Redirect the video command to the video player at front"""
        path_parts = str(path).split('/')
        jadeo_index = path_parts.index('jadeo')
        jadeo_cmd = '/' + '/'.join(path_parts[jadeo_index:])
        output_index = path_parts[jadeo_index - 1]
        output_name = PLAYER_HANDLER.get_video_output_names(output_index)
        output_player = PLAYER_HANDLER.get_active_videoplayer(output_name)
        if not output_player:
            Logger.error(f'No active video player found for output {output_name} at index {output_index}')
            return
        client: PlayerClient = output_player['osc']
        client.set_value(jadeo_cmd, value)

    # Script functions
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

    def get_config_ports(self):
        """Create a dict of ports from the config"""
        k = [i for i in self.cm.node_conf.keys() if 'port' in i and is_int(self.cm.node_conf[i])]
        v = [int(self.cm.node_conf[i]) for i in k]
        return dict(zip(k, v))

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
        Logger.info(f'GO command received. Starting script {self.script.unix_name}')
        self.oscquery_server.set_value('/engine/status/running', "yes")

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
