from os import path
from pyossia import ossia
from .Cue import Cue
from .VideoPlayer import VideoPlayer
from .OssiaServer import QueueOSCData
class VideoCue(Cue):
    def __init__(self, time=None, init_dict=None):
      super().__init__(time, init_dict)
      self.offset_route = '/jadeo/offset'

    @property
    def player(self):
        return super().__getitem__('player')

    @player.setter
    def player(self, player):
        super().__setitem__('player', player)

    @property
    def osc_route(self):
        return super().__getitem__('osc_route')

    @osc_route.setter
    def osc_route(self, osc_route):
        super().__setitem__('osc_route', osc_route)

    @property
    def offset_route(self):
        return super().__getitem__('offset_route')

    @offset_route.setter
    def offset_route(self, offset_route):
        super().__setitem__('offset_route', offset_route)

    def review_offset(self, timecode):
        return -(int(timecode.frames))

    @property
    def armed(self):
        return super().__getitem__('armed')

    @armed.setter
    def armed(self, armed):
        super().__setitem__('armed', armed)

    def arm(self, conf, queue):
        # Assign its own videoplayer object
        self.player = VideoPlayer(  conf.players_port_index['video'], 
                                    self.outputs,
                                    conf.node_conf['videoplayer']['path'],
                                    str(conf.node_conf['videoplayer']['args']),
                                    str(path.join(conf.library_path, 'media', self.media)))

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
                                    conf.players_port_index['video'],
                                    conf.players_port_index['video'] + 1, 
                                    OSC_VIDEOPLAYER_CONF))

        conf.players_port_index['video'] = conf.players_port_index['video'] + 2

        self.armed = True

    def disarm(self, cm, queue):
        self.armed = False

