
from os import path

from .Cue import Cue
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
        return super().__getitem__('outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('outputs', outputs)


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

     