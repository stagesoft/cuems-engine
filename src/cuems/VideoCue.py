from os import path
from .Cue import Cue
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

