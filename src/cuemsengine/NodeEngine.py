from cuemsutils.cues import CueList
from cuemsutils.log import Logger, logged
from cuemsutils.helpers import as_cuemsdict

from .ControllerEngine import CONTROLLER_HOST
from .core.BaseEngine import BaseEngine
from .cues.CueHandler import CueHandler
from .osc import ClientDevices, ValueType, ENGINE_CMD_ENDPOINTS, AUDIO_ENDPOINTS, VIDEO_ENDPOINTS, DMX_ENDPOINTS
from .osc.OssiaClient import OssiaClient
from .osc.helpers import include_function_endpoints
from .tools.CuemsDeploy import CuemsDeploy
from .tools.PortHandler import PortHandler
from .players import VideoPlayer, VideoClient

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
        self.deploy_manager = CuemsDeploy(
            library_path=self.cm.library_path,
            tmp_path=self.cm.tmp_path
        )
        self.cue_handler = CueHandler()
        self.port_handler = PortHandler()
        self.port_handler.set_ports(cue=None, ports=self.get_config_ports())
        

    #def start(self):
        self.set_oscquery()
        self.set_video_players()
    #    super().start()
        
    @logged
    def stop(self):
        self.stop_node_engine()
        super().stop()

    def stop_node_engine(self):
        """Stop the NodeEngine elements"""
        self.cue_handler.disarm_all()
        try:
            self.quit_video_devs()
            Logger.info('Quitted video devs')
        except Exception as e:
            Logger.warning(f'Exception raised when quitting video devs: {e}')
        self.disconnect_video_devs()
        self.unload_video_devs()

    # OSCQuery functions
    def set_oscquery(self):
        """Set the OSCQuery infrastructure"""
        Logger.info("Starting oscquery for Node")
        self.set_oscquery_client()
        self.apply_oscquery_commands()

    def set_oscquery_client(self, endpoints: dict = None):
        self.oscquery_client = OssiaClient(
            host = CONTROLLER_HOST,
            local_port = self.cm.node_conf['osc_in_port_base'],
            remote_port = self.cm.node_conf['oscquery_ws_port'],
            remote_type = ClientDevices.OSCQUERY,
            endpoints = endpoints
        )
        Logger.debug(f"OscQueryClient created: {self.oscquery_client}")

    def apply_oscquery_commands(self):
        cmd_dict = {
            'load': self.load_project,
            'loadcue': None, # self.load_cue,
            'go': self.go_script,
            'gocue': None, # self.go_cue_callback,
            'pause': None, # self.pause_callback,
            'stop': None, # self.stop_callback,
            'resetall': None, # self.reset_all_callback,
            'preload': None, # self.load_cue_callback,
            'unload': None, # self.unload_cue_callback,
            'hwdiscovery': None, # self.hw_discovery_callback,
            'deploy': None, # self.deploy_callback,
            'test': None # self.test_callback
        }
        endpoints = include_function_endpoints(
            ENGINE_CMD_ENDPOINTS,
            cmd_dict
        )
        self.oscquery_client.create_endpoints(endpoints)

    def set_oscquery_values(self, values: dict):
        for key, value in values.items():
            self.oscquery_client.set_value(key, value)

    # Project functions
    def load_project(self, project):
        """Load the project files to the node"""
        if self.get_status('load') == project:
            Logger.info(f'Project {project} already loaded')
            return

        # Obtain the project files
        self.deploy_project(project)
        self.cm.load_project_config(project)
        self.read_script(project)
        self.deploy_media(project)
        
        # Prepare the script to be played
        self.ready_script()

        # Start cue dependencies
        self.set_video_players()
        # self.set_dmx_players()
        # self.set_audio_players()

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
        for cue in cuelist.contents:
            # ignore return value found in check_mappings
            _ = cue.check_mappings(self.cm)
            if cue._local and cue.autoload:
                self.cue_handler.arm(cue, self.oscquery_client, True)
            if isinstance(cue, CueList):
                self.check_local_cues(cue)

    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        if not self.cm.node_hw_outputs['video_outputs']:
            Logger.info('No video outputs detected.')
            return
        
        try:
            for index, player_id in enumerate(self.cm.node_hw_outputs['video_outputs']):
                if player_id in self._video_players:
                    continue
                
                # Obtain new ports
                new_ports = self.update_config_ports([
                    f'video_player_{index}_in_port',
                    f'video_player_{index}_out_port'
                ])

                # Create the player object
                player = dict()
                player['route'] = f'/players/videoplayer-{index}'
                player['in_port'] = new_ports[f'video_player_{index}_in_port']
                player['out_port'] = new_ports[f'video_player_{index}_out_port']

                try:
                    # Assign a videoplayer process object
                    player['player'] = VideoPlayer(
                        player['in_port'],
                        player_id,
                        self.cm.node_conf['videoplayer']['path'],
                        self.cm.node_conf['videoplayer']['args'],
                        ''
                    )
                except Exception as e:
                    raise e

                # Assign an osc client to the player
                player['osc'] = VideoClient(player['in_port'], player['route'])
                
                # Store and start the player
                self._video_players[player_id] = player
                self._video_players[player_id]['player'].start()

        except Exception as e:
            Logger.exception(f'Exception raised when checking video outputs: {e}.')
    
    def get_player(self, cue):
        """Find the player for a given cue"""
        output_name = get_cue_output_name(cue)
        if output_name in self._video_players:
            return self._video_players[output_name]
        # elif output_name in self._audio_players:
        #     return self._audio_players[output_name]
        # elif output_name in self._dmx_players:
        #     return self._dmx_players[output_name]
        return None

    def check_dmx_devs(self):
        pass

    # Video functions
    def set_video_players(self):
        """Set the video players"""
        self._video_players = {}
        try:
            self.check_video_devs()
        except Exception as e:
            Logger.error(f'Error checking & starting video devices...')
            Logger.error(e)
            Logger.error(f'Exiting...')
            exit(-1)

    def quit_video_devs(self):
        for dev in self._video_players.values():
            try:
                dev['osc'].set_value('/jadeo/cmd', 'quit')
            except Exception as e:
                Logger.exception(e)

    def disconnect_video_devs(self):
        for dev in self._video_players.values():
            try:
                dev['osc'].set_value('/jadeo/cmd', 'midi disconnect')
            except Exception as e:
                Logger.exception(e)

    def unload_video_devs(self):
        for dev in self._video_players.values():
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
        self.cue_handler.disarm_all()
        self.cue_handler.arm(self.script.cuelist.contents[0], self.oscquery_client, True)
        
        Logger.info(f'Script {self.script.unix_name} loaded and ready to be played')

    def get_config_ports(self):
        """Create a dict of ports from the config"""
        k = [i for i in self.cm.node_conf.keys() if 'port' in i and is_int(self.cm.node_conf[i]) and self.cm.node_conf[i] >= 9090]
        v = [int(self.cm.node_conf[i]) for i in k]
        return dict(zip(k, v))

    def go_script(self, value):
        if self.get_status('go') == value:
            return

        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return

        if not self.ongoing_cue:
            cue_to_go = self.script.cuelist.contents[0]
        else:
            if self.next_cue_pointer:
                cue_to_go = self.next_cue_pointer
            else:
                Logger.info(f'Reached end of script. Last cue was {self.ongoing_cue.__class__.__name__} {self.ongoing_cue.uuid}')
                self.ready_script()
                return

        if not cue_to_go._local:
            Logger.info(f'Actual cue outside node space. CUE : {cue_to_go.uuid}')
            return

        if cue_to_go not in self.cue_handler._armed_cues:
            Logger.error(f'Trying to go a cue that is not yet loaded. CUE : {cue_to_go.uuid}')
        else:
            self.ongoing_cue = cue_to_go
            self.cue_handler.go(
                cue_to_go,
                self.get_player(cue_to_go)['osc'],
                self.mtc_listener
            )
            self.next_cue_pointer = self.ongoing_cue.get_next_cue()
            self.go_offset = self.mtc_listener.main_tc.milliseconds

            # OSCQuery status notification
            if self.next_cue_pointer:
                next_cue = self.next_cue_pointer.uuid
            else:
                next_cue = ""
            self.oscquery_client.set_value('/engine/status/currentcue', self.ongoing_cue.uuid)
            self.oscquery_client.set_value('/engine/status/nextcue', next_cue)

        self.set_status('go', value)

    def update_config_ports(self, names: list[str]):
        """Update the config ports"""
        new_ports = {}
        for name in names:
            new_ports[name] = self.port_handler.get_free_port()
        conf_ports = self.port_handler.get_ports(cue=None)
        conf_ports.update(new_ports)
        self.port_handler.remove_ports(cue=None)
        self.port_handler.set_ports(cue=None, ports=conf_ports)
        return new_ports

## MISCELLANEOUS FUNCTIONS ##

# helper functions
def is_int(value: any) -> bool:
    """Check if a value is an integer"""
    try:
        int(value)
        return True
    except ValueError:
        return False

def get_cue_output_name(cue):
    """Get the output name for a given cue"""
    outputs_key = cue.outputs.keys()[0]
    return cue.outputs[outputs_key]['output_name']
