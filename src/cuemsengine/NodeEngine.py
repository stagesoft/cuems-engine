from cuemsutils.log import Logger, logged

from .BaseEngine import BaseEngine
from .cues.CueHandler import CueHandler
from .players import AudioPlayer, DmxPlayer, VideoPlayer

class NodeEngine(BaseEngine):
    """This engine manages players for each node
    It is responsible for:
      - Starting and stopping players
      - Monitoring player status
      - Restarting players
      - Updating player configurations
      - Handling player failures
      - Providing a clean interface for starting and stopping players
      - Providing a clean interface for monitoring player status
    
    Communicates with the ControllerEngine via OSCQuery
    Interacts with Player objects via OSC
    """

    def __init__(self):
        super().__init__()
        self.cue_handler = CueHandler()
        self.set_video_players()
        self.run()

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

    # Check functions
    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        try:
            if self.cm.node_hw_outputs['video_outputs']:
                for index, item in enumerate(self.cm.node_hw_outputs['video_outputs']):
                    # Select the OSC port number for our new videoplayer
                    port = self.cm.osc_port_index['start']
                    while port in self.cm.osc_port_index['used']:
                        port += 2

                    self.cm.osc_port_index['used'].append(port)

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

                    self._video_players[player_id]['player'].start()

                    # And dinamically attach it to the ossia for remote control it
                    self._video_players[player_id]['route'] = f'/players/videoplayer-{index}'

                    OSC_VIDEOPLAYER_CONF = {
                        '/jadeo/xscale' : [ossia.ValueType.Float, None],
                        '/jadeo/yscale' : [ossia.ValueType.Float, None], 
                        '/jadeo/corners' : [ossia.ValueType.List, None],
                        '/jadeo/corner1' : [ossia.ValueType.List, None],
                        '/jadeo/corner2' : [ossia.ValueType.List, None],
                        '/jadeo/corner3' : [ossia.ValueType.List, None],
                        '/jadeo/corner4' : [ossia.ValueType.List, None],
                        '/jadeo/start' : [ossia.ValueType.Int, None],
                        '/jadeo/load' : [ossia.ValueType.String, None],
                        '/jadeo/cmd' : [ossia.ValueType.String, None],
                        '/jadeo/quit' : [ossia.ValueType.Int, None],
                        '/jadeo/offset' : [ossia.ValueType.String, None],
                        '/jadeo/offset.1' : [ossia.ValueType.Int, None],
                        '/jadeo/midi/connect' : [ossia.ValueType.String, None],
                        '/jadeo/midi/disconnect' : [ossia.ValueType.Int, None]
                    }

                    self.ossia_server.add_player_nodes(
                        PlayerOSCConfData(
                            device_name=self._video_players[player_id]['route'], 
                            host=self.cm.node_conf['osc_dest_host'], 
                            in_port=port,
                            out_port=port + 1,
                            dictionary=OSC_VIDEOPLAYER_CONF
                        )
                    )
            else:
                Logger.info('No video outputs detected.')
        except Exception as e:
            Logger.exception(f'Exception raise when checking vidio outputs: {e}.')

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

    def check_dmx_devs(self):
        pass
