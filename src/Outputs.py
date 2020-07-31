from log import *

OUTPUTS_SUFFIX = 'Outputs'

class Outputs():
    def __init__(self, caller_class, outputs_params):
        class_name = type(caller_class).__name__
        class_name = class_name + OUTPUTS_SUFFIX
        self._obj = None
        try:
            _class = globals()[class_name]
            self._obj =   _class(outputs_params)
        except KeyError as err:
            logger.error("Could not find class {0}".format(err))
            _class = None

    def assign(self):
        return self._obj

class CueOutputs(dict):
    def __init__(self, outputs_params):
        if isinstance(outputs_params, dict):
            super().__init__(outputs_params)
        else:
            super().__setitem__('output_id', outputs_params)
    
    def __str__(self):
        return super().__str__()

class AudioCueOutputs(CueOutputs):
    def __init__(self, outputs_params):
        super().__init__(outputs_params)

class VideoCueOutputs(CueOutputs):
    def __init__(self, outputs_params):
        super().__init__(outputs_params)

class DmxCueOutputs(CueOutputs):
    def __init__(self, outputs_params):
        super().__init__(outputs_params)