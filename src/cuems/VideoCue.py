from os import path
from pyossia import ossia
from .Cue import Cue
from .VideoPlayer import VideoPlayer
from .OssiaServer import QueueOSCData
from .log import logger
class VideoCue(Cue):
    def __init__(self, time=None, init_dict=None):
      super().__init__(time, init_dict)
      self.offset_route = '/jadeo/offset'


    @property
    def outputs(self):
        return super().__getitem__('outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('outputs', outputs)


    def review_offset(self, timecode):
        return -(int(timecode.frames))

    def arm(self, conf, queue, init = False):
        if self.disabled or (self.loaded != init and self.timecode == init):
            if self.disabled and self.loaded:
                self.disarm(conf, queue)
            return False

        # Assign its own videoplayer object
        self.player = VideoPlayer(  conf.players_port_index, 
                                    self.outputs,
                                    conf.node_conf['videoplayer']['path'],
                                    str(conf.node_conf['videoplayer']['args']),
                                    str(path.join(conf.library_path, 'media', self.media['file_name'])))

        self.player.start()

        # And dinamically attach it to the ossia for remote control it
        OSC_VIDEOPLAYER_CONF = {'/jadeo/xscale' : [ossia.ValueType.Float, None],
                                '/jadeo/yscale' : [ossia.ValueType.Float, None], 
                                '/jadeo/corners' : [ossia.ValueType.List, None],
                                '/jadeo/corner1' : [ossia.ValueType.List, None],
                                '/jadeo/corner2' : [ossia.ValueType.List, None],
                                '/jadeo/corner3' : [ossia.ValueType.List, None],
                                '/jadeo/corner4' : [ossia.ValueType.List, None],
                                '/jadeo/start' : [ossia.ValueType.Bool, None],
                                '/jadeo/load' : [ossia.ValueType.String, None],
                                '/jadeo/quit' : [ossia.ValueType.Bool, None],
                                '/jadeo/offset' : [ossia.ValueType.Int, None],
                                self.offset_route : [ossia.ValueType.String, None],
                                '/jadeo/midi/connect' : [ossia.ValueType.String, None],
                                '/jadeo/midi/disconnect' : [ossia.ValueType.Impulse, None]
                                }

        self.osc_route = f'/node{conf.node_conf["id"]:03}/videoplayer-{self.uuid}'

        queue.put(   QueueOSCData(  'add', 
                                    self.osc_route, 
                                    conf.node_conf['osc_dest_host'], 
                                    self.player.port,
                                    self.player.port + 1, 
                                    OSC_VIDEOPLAYER_CONF))

        self.loaded = True

        return True

    def disarm(self, cm, queue):
        if self.loaded is True:
            try:
                self.player.kill()
                cm.osc_port_index['used'].pop(self.player.port)
                del self.player
            except:
                logger.warning(f'Could not properly unload cue {self.uuid}')
            
            self.loaded = False

            return self.uuid
        else:
            return None

