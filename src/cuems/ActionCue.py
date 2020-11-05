
from .Cue import Cue

class ActionCue(Cue):
    def __init__(self, time=None, init_dict=None):
        super().__init__(time, init_dict)
