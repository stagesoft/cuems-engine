from log import *

OUTPUTS_SUFFIX = 'Outputs'

class Outputs():
    def __init__(self, caller_class, init_dict = None):
        class_name = type(caller_class).__name__
        class_name = class_name + OUTPUTS_SUFFIX
        self._obj = None
        try:
            _class = globals()[class_name]
            self._obj =   _class(init_dict = init_dict)
        except KeyError as err:
            logger.error("Could not find class {0}".format(err))
            _class = None

    def assign(self):
        return self._obj

class CueOutputs(dict):
    def __init__(self, init_dict = None):
        if init_dict is not None:
            if isinstance(init_dict, dict):
                for key, item in init_dict.items():
                    super().__setitem__(key, item)
            else:
                super().__setitem__('id', init_dict)

        else:
            super().__init__()


    
    def __str__(self):
        return super().__str__()

class AudioCueOutputs(CueOutputs):
    def __init__(self, init_dict = None):
        super().__init__(init_dict)

class VideoCueOutputs(CueOutputs):
    def __init__(self, init_dict = None):
        super().__init__(init_dict)

class DmxCueOutputs(CueOutputs):
    def __init__(self, init_dict = None):
        super().__init__(init_dict)