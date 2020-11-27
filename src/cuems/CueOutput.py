from .log import logger

class CueOutput(dict):
    def __init__(self, init_dict = None):
        if init_dict is not None:
            super().__init__(init_dict)

class AudioCueOutput(CueOutput):
    pass

class VideoCueOutput(CueOutput):
    pass

class DmxCueOutput(CueOutput):
    pass
