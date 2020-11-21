from .log import logger

class CueOutput(dict):
    def __init__(self, init_dict = None):
        super().__init__(init_dict)
    
class AudioCueOutput(CueOutput):
    def __init__(self, init_dict = None):
        super().__init__(init_dict)

class VideoCueOutput(CueOutput):
    def __init__(self, init_dict = None):
        super().__init__(init_dict)

class DmxCueOutput(CueOutput):
    def __init__(self, init_dict = None):
        super().__init__(init_dict)