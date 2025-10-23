from cuemsutils.cues import Cue, CueList, VideoCue
from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine, NODE_ENGINE_PORT
from .cues.CueHandler import CUE_HANDLER
from .osc import ENGINE_CMD_ENDPOINTS
from .osc.helpers import add_callbacks_from_dict, add_callback_to_all, add_prefix_to_all
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
        PORT_HANDLER.add_system_ports()
        if hasattr(self, 'cm'):
            PORT_HANDLER.add_config_ports(
                self.get_config_ports()
            )
            self.deploy_manager = CuemsDeploy(
                library_path=self.cm.library_path,
                tmp_path=self.cm.tmp_path
            )
            PLAYER_HANDLER.add_media_folder(
                self.cm.library_path
            )

    def start(self):
        self.set_oscquery()
        self.set_video_players()
        self.set_audio_players()
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
    def set_oscquery(self):
        """Set the OSCQuery infrastructure"""
        Logger.info("Starting oscquery for Node")
        self.set_oscquery_server(
            add_prefix_to_all(
                self.get_status_endpoints(), '/node'
            ),
            port = NODE_ENGINE_PORT
        )
        Logger.debug(f"OscQuery Node server set")
        self.set_oscquery_client()
        Logger.debug(f"OscQuery Node client set")
        self.apply_oscquery_commands()


    def apply_oscquery_commands(self):
        cmd_dict = {
            'deploy': self.ready_project,
            # Not a node responsibility
            # 'hwdiscovery': None, # self.hw_discovery_callback,
            'load': self.load_project,
            'loadcue': None, # self.load_cue,
            'go': self.go_script,
            'gocue': None, # self.go_cue_callback,
            'pause': None, # self.pause_callback,
            # 'preload': None, # self.load_cue_callback,
            'resetall': None, # self.reset_all_callback,
            'stop': None, # self.stop_callback,
            'test': None, # self.test_callback
            'unload': None # self.unload_cue_callback,
        }
        endpoints = add_callbacks_from_dict(
            add_prefix_to_all(ENGINE_CMD_ENDPOINTS, '/node'),
            cmd_dict
        )
        self.oscquery_server.create_endpoints(endpoints)
        Logger.debug(f"OscQuery Node endpoints: {endpoints}")
        #self.oscquery_client.create_endpoints(ENGINE_CMD_ENDPOINTS)

    def set_oscquery_values(self, values: dict):
        for key, value in values.items():
            self.oscquery_client.set_value(key, value)

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
        # self.set_dmx_players()

        # Check local cues
        self.check_local_cues(self.script.cuelist)

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
        if not cuelist.contents:
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
            mixer_ports = PORT_HANDLER.assign_ports(['audio_mixer'])
            PORT_HANDLER.add_config_ports(mixer_ports)
            
            # Get node UUID for mixer naming
            node_uuid = self.cm.node_conf.get('uuid', 'default_node')
            
            # Start the audio mixer
            try:
                PLAYER_HANDLER.start_audio_mixer(
                    audio_outputs=audio_outputs,
                    port=mixer_ports['audio_mixer'],
                    node_uuid=node_uuid
                )
                Logger.info(f'Audio mixer started successfully for node {node_uuid}')
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
        # self.set_oscquery_values({
        #     '/engine/status/running': 0 #,
        #     # '/engine/command/go': ''
        # })
        Logger.info(f'Script {self.script.name} loaded and ready to be played')

    def get_config_ports(self):
        """Create a dict of ports from the config"""
        k = [i for i in self.cm.node_conf.keys() if 'port' in i and is_int(self.cm.node_conf[i])]
        v = [int(self.cm.node_conf[i]) for i in k]
        return dict(zip(k, v))

    def go_script(self, value):
        if self.get_status('running') == 1:
            return

        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return

        # Signal go start
        Logger.info(f'GO command received. Starting script {self.script.unix_name}')
        self.set_status('running', 1)

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
        else:
            self.ongoing_cue = cue_to_go
            CUE_HANDLER.go(
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
            self.oscquery_client.set_value('/engine/status/currentcue', self.ongoing_cue.id)
            self.oscquery_client.set_value('/engine/status/nextcue', next_cue)


## MISCELLANEOUS FUNCTIONS ##

# helper functions
def is_int(value: any) -> bool:
    """Check if a value is an integer"""
    try:
        int(value)
        return True
    except ValueError:
        return False
