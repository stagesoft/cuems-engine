
from os import path
from pyossia import ossia

from .Cue import Cue
from .AudioPlayer import AudioPlayer
from .OssiaServer import QueueOSCData
from .log import logger

class AudioCue(Cue):
    def __init__(self, time=None, init_dict=None):
        super().__init__(time, init_dict)
        self.offset_route = '/offset'

    @property
    def master_vol(self):
        return super().__getitem__('master_vol')

    @master_vol.setter
    def master_vol(self, master_vol):
        super().__setitem__('master_vol', master_vol)

    @property
    def outputs(self):
        return super().__getitem__('Outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('Outputs', outputs)


    def review_offset(self, timecode):
        return -(float(timecode.milliseconds))

    def init_arm(self, conf, queue):
        if self.loaded is True and self.disabled is not True:
            self.arm(conf, queue)

    def arm(self, conf, queue, init = False):
        if self.disabled or (self.loaded != init and self.timecode == init):
            if self.disabled and self.loaded:
                self.disarm(conf, queue)
            return False

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

            return True
        else:
            return False

