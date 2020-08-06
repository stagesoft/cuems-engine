from CTimecode import CTimecode
from Outputs import Outputs
import uuid
class Cue(dict):
    def __init__(self, time=None, init_dict = None):
        super().__setitem__('uuid', str(uuid.uuid4())) # TODO: Check safe and choose uuid version (4? 5?)
        #TODO: do not generate uuid if geting dict from xml, now we generate it and then overwrite it so we allwais have one
        self.time = time
        if init_dict is not None:
            super().__init__(init_dict)

    @classmethod
    def from_dict(cls, init_dict):
        return cls(init_dict =  init_dict)

    @property
    def outputs(self):
        return super().__getitem__('outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('outputs', Outputs(self, outputs).assign())
    
    @property
    def time(self):
        return super().__getitem__('time')

    @time.setter #TODO: let te timecode object handle this
    def time(self, time):
        if isinstance(time, CTimecode):
            super().__setitem__('time', time)
        elif isinstance(time, (int, float)):
            corrected_seconds = CTimecode(start_seconds=time)
            corrected_seconds.frames = corrected_seconds.frames + 1
            super().__setitem__('time', corrected_seconds) #TODO: discuss this
        elif isinstance(time, str):
            super().__setitem__('time', CTimecode(time))
        elif isinstance(time, dict):
            dict_timecode = time.pop('CTimecode', None)
            if dict_timecode is None:
                super().__setitem__('time', None)
            else:
                super().__setitem__('time', CTimecode(dict_timecode))
        elif time == None:
            super().__setitem__('time', None)
        else:
            raise NotImplementedError #TODO: disscuss raised error

    def type(self):
        return type(self)


    def __setitem__(self, key, value):
        if key == 'time':
            self.time = value
        else:
            super().__setitem__(key, value)


