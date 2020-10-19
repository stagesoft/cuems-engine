from .CTimecode import CTimecode
from .Outputs import Outputs
from .log import logger
import uuid as uuid_module

class Cue(dict):
    def __init__(self, offset=None, init_dict = None, uuid=None ):
        if uuid is None:
            super().__setitem__('uuid', str(uuid_module.uuid4())) # TODO: Check safe and choose uuid version (4? 5?)
        
        if offset is not None:
            super().__setitem__('timecode', True)
            if  isinstance(offset, CTimecode):
                super().__setitem__('offset', offset)
            else:
                super().__setitem__('offset', CTimecode(start_seconds=offset))
        else:
            super().__setitem__('timecode', False)
        
        if init_dict is not None:
            super().__init__(init_dict)

    @classmethod
    def from_dict(cls, init_dict):
        return cls(init_dict =  init_dict)

    @property
    def uuid(self):
        return super().__getitem__('uuid')

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
            super().__setitem__('offset', corrected_seconds) #TODO: discuss this
        elif isinstance(offset, str):
            super().__setitem__('offset', CTimecode(offset))
        elif isinstance(offset, dict):
            dict_timecode = offset.pop('CTimecode', None)
            super().__setitem__('time', corrected_seconds) #TODO: discuss this
        elif isinstance(time, str):
            super().__setitem__('time', CTimecode(time))
        elif isinstance(time, dict):
            dict_timecode = time.pop('CTimecode', None)
            if dict_timecode is None:
                super().__setitem__('offset', None)
                super().__setitem__('time', None)
            else:
                super().__setitem__('time', CTimecode(dict_timecode))
        elif time == None:
            super().__setitem__('time', None)
        else:
            raise NotImplementedError #TODO: disscuss raised error

    @property
    def media(self):
        try:
            return super().__getitem__('media')
        except KeyError:
            logger.debug('{} {} with no media'.format(type(self), self.uuid))

    @media.setter
    def media(self, media):
        super().__setitem__('media', media)

    def type(self):
        return type(self)


    def __setitem__(self, key, value):
        if key == 'offset':
            self.offset = value
        else:
            super().__setitem__(key, value)


