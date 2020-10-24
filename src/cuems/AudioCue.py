
from os import path
from pyossia import ossia

from .Cue import Cue
from .AudioPlayer import AudioPlayer
from .OssiaServer import QueueOSCData

class AudioCue(Cue):
    def __init__(self, time=None, init_dict=None):
        super().__init__(time, init_dict)
        self.offset_route = '/offset'

    @property
    def media(self):
        return super().__getitem__('media')

    @media.setter
    def media(self, media):
        super().__setitem__('media', media)

    @property
    def master_vol(self):
        return super().__getitem__('master_vol')

    @master_vol.setter
    def master_vol(self, master_vol):
        super().__setitem__('master_vol', master_vol)

    @property
    def outputs(self):
        return super().__getitem__('outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('outputs', outputs)

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
        return -(float(timecode.milliseconds))

    def arm(self, conf, queue):
        # Assign its own audioplayer object
        try:
            self.player = AudioPlayer(  conf.players_port_index, 
                                        conf.node_conf['audioplayer']['path'],
                                        str(conf.node_conf['audioplayer']['args']),
                                        str(path.join(conf.library_path, 'media', self.media['file_name'])))
        except Exception as e:
            raise e

        self.player.start()

        # And dinamically attach it to the ossia for remote control it
        OSC_AUDIOPLAYER_CONF = {'/quit' : [ossia.ValueType.Impulse, None],
                                '/load' : [ossia.ValueType.String, None], 
                                '/vol0' : [ossia.ValueType.Float, None],
                                '/vol1' : [ossia.ValueType.Float, None],
                                '/volmaster' : [ossia.ValueType.Float, None],
                                self.offset_route : [ossia.ValueType.Float, None],
                                '/play' : [ossia.ValueType.Impulse, None],
                                '/stop' : [ossia.ValueType.Impulse, None],
                                '/stoponlost' : [ossia.ValueType.Bool, None],
                                '/mtcfollow' : [ossia.ValueType.Bool, None],
                                '/check' : [ossia.ValueType.Impulse, None]
                                }

        self.osc_route = f'/node{conf.node_conf["id"]:03}/audioplayer-{self.uuid}'

        queue.put(   QueueOSCData(  'add', 
                                    self.osc_route, 
                                    conf.node_conf['osc_dest_host'], 
                                    self.player.port,
                                    self.player.port + 1, 
                                    OSC_AUDIOPLAYER_CONF))

        self.loaded = True

    def disarm(self, cm, queue):
        self.player.kill()
        cm.osc_port_index['used'].pop(self.player.port)
        del self.player
        self.loaded = False

