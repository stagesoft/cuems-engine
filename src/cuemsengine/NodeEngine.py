from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine
from .cues.CueHandler import CueHandler
from .tools.CuemsDeploy import CuemsDeploy
from .players import AudioPlayer, DmxPlayer, VideoPlayer
from .osc import ValueType

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
        self.set_video_players()
        self.run()

    def load_project(self, project):
        """Load the project files to the node"""
        # Obtain the project files
        self.deploy_project(project)
        self.cm.load_project_config(project)
        self.read_script(project)
        self.deploy_media(project)

        # Start cue dependencies
        self.set_video_players()

        # Confirm the project is loaded
        self.set_show_lock_file()
        self.set_status('load', project)
        Logger.info(f'Project {project} loaded')

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

    def deploy_project(self, project):
        """Deploy the project files to the node"""
        self.deploy_manager.sync_files(project, 'project')

    def deploy_media(self, project):
        """Deploy the media files to the node"""
        if not self.script:
            Logger.error('No script loaded')
            return
        file_names = self.script.get_own_media(config=self.cm)
        self.deploy_manager.sync_files(project, 'media', file_names)

    # Check functions
    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        try:
            if self.cm.node_hw_outputs['video_outputs']:
                for index, item in enumerate(self.cm.node_hw_outputs['video_outputs']):
                    # Select the OSC port number for our new videoplayer
                    port = self.cm.node_conf['osc_in_port_base'] + index * 2
                    # port = self.cm.osc_port_index['start']
                    # while port in self.cm.osc_port_index['used']:
                    #     port += 2

                    # self.cm.osc_port_index['used'].append(port)

                    player_id = item
                    self._video_players[player_id] = dict()

                    try:
                        # Assign a videoplayer object
                        self._video_players[player_id]['player'] = VideoPlayer(
                            port,
                            item,
                            self.cm.node_conf['videoplayer']['path'],
                            self.cm.node_conf['videoplayer']['args'],
                            ''
                        )
                    except Exception as e:
                        raise e

                    # self._video_players[player_id]['player'].start()

                    # # And dinamically attach it to the ossia for remote control it
                    # self._video_players[player_id]['route'] = f'/players/videoplayer-{index}'

                    # OSC_VIDEOPLAYER_CONF = {
                    #     '/jadeo/xscale' : [ValueType.Float, None],
                    #     '/jadeo/yscale' : [ValueType.Float, None], 
                    #     '/jadeo/corners' : [ValueType.List, None],
                    #     '/jadeo/corner1' : [ValueType.List, None],
                    #     '/jadeo/corner2' : [ValueType.List, None],
                    #     '/jadeo/corner3' : [ValueType.List, None],
                    #     '/jadeo/corner4' : [ValueType.List, None],
                    #     '/jadeo/start' : [ValueType.Int, None],
                    #     '/jadeo/load' : [ValueType.String, None],
                    #     '/jadeo/cmd' : [ValueType.String, None],
                    #     '/jadeo/quit' : [ValueType.Int, None],
                    #     '/jadeo/offset' : [ValueType.String, None],
                    #     '/jadeo/offset.1' : [ValueType.Int, None],
                    #     '/jadeo/midi/connect' : [ValueType.String, None],
                    #     '/jadeo/midi/disconnect' : [ValueType.Int, None]
                    # }

                    # self.ossia_server.add_player_nodes(
                    #     PlayerOSCConfData(
                    #         device_name=self._video_players[player_id]['route'], 
                    #         host=self.cm.node_conf['osc_dest_host'], 
                    #         in_port=port,
                    #         out_port=port + 1,
                    #         dictionary=OSC_VIDEOPLAYER_CONF
                    #     )
                    # )
            else:
                Logger.info('No video outputs detected.')
        except Exception as e:
            Logger.exception(f'Exception raise when checking video outputs: {e}.')
    
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
            key = f'{dev["route"]}/jadeo/cmd'
            try:
                self.ossia_server.osc_player_registered_nodes[key][0].value = 'quit'
            except Exception as e:
                Logger.exception(e)

    def disconnect_video_devs(self):
        for dev in self._video_players.values():
            try:
                key = f'{dev["route"]}/jadeo/cmd'
                self.ossia_server.osc_player_registered_nodes[key][0].value = 'midi disconnect'
            except KeyError:
                Logger.exception(f'Key error (cmd midi disconnect) in disconnect all method {key}')

    def unload_video_devs(self):
        for dev in self._video_players.values():
            try:
                key = f'{dev["route"]}/jadeo/load'
                # ossia._oscquery_registered_nodes[key][0].value = str(path.join(self._conf.library_path, 'media', self.media.file_name))
                self.ossia_server.osc_player_registered_nodes[key][0].value = ''
            except Exception as e:
                Logger.debug(f'Exception while unloading video players: {e}')
