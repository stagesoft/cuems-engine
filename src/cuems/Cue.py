from .CTimecode import CTimecode
from .Outputs import Outputs
from .log import logger
import uuid as uuid_module

class Cue(dict):
    def __init__(self, offset=None, init_dict = None, uuid=None ):
        if uuid is None:
            super().__setitem__('uuid', str(uuid_module.uuid1())) # TODO: Check safe and choose uuid version (4? 5?)
        self.offset = offset
        if self.offset:
            self.timecode = True
        else:
            self.timecode = False

        if init_dict is not None:
            super().__init__(init_dict)
        self.armed = False
        self.init_arm = False
        self.exec_options = {'prewait':None, 'autofollow':False, 'autocontinue':False, 'postwait':False}

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
    def offset(self):
        return super().__getitem__('offset')

    @offset.setter #TODO: let te timecode object handle this
    def offset(self, offset):
        if isinstance(offset, CTimecode):
            super().__setitem__('offset', offset)
        elif isinstance(offset, (int, float)):
            corrected_seconds = CTimecode(start_seconds=offset)
            corrected_seconds.frames = corrected_seconds.frames + 1
            super().__setitem__('offset', corrected_seconds) #TODO: discuss this
        elif isinstance(offset, str):
            super().__setitem__('offset', CTimecode(offset))
        elif isinstance(offset, dict):
            dict_timecode = offset.pop('CTimecode', None)
            if dict_timecode is None:
                super().__setitem__('offset', None)
            else:
                super().__setitem__('offset', CTimecode(dict_timecode))
        elif offset == None:
            super().__setitem__('offset', CTimecode('00:00:00:00'))
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

    @property
    def exec_options(self):
        return super().__getitem__('exec_options')

    @exec_options.setter
    def exec_options(self, exec_options):
        super().__setitem__('exec_options', exec_options)

    @property
    def autocontinue(self):
        return super().__getitem__('exec_options[autocontinue]')

    @autocontinue.setter
    def autocontinue(self, autocontinue):
        super().__setitem__('exec_options[autocontinue]', autocontinue)

    @property
    def autofollow(self):
        return super().__getitem__('exec_options[autofollow]')

    @autofollow.setter
    def autofollow(self, autofollow):
        super().__setitem__('exec_options[autofollow]', autofollow)

    @property
    def pre_wait(self):
        return super().__getitem__('exec_options[pre_wait]')

    @pre_wait.setter
    def pre_wait(self, pre_wait):
        super().__setitem__('exec_options[pre_wait]', pre_wait)

    @property
    def post_wait(self):
        return super().__getitem__('exec_options[post_wait]')

    @post_wait.setter
    def post_wait(self, post_wait):
        super().__setitem__('exec_options[post_wait]', post_wait)

    @property
    def timecode(self):
        return super().__getitem__('timecode')

    @timecode.setter
    def timecode(self, timecode):
        super().__setitem__('timecode', timecode)

    @property
    def loop(self):
        return super().__getitem__('loop')

    @loop.setter
    def loop(self, loop):
        super().__setitem__('loop', loop)

    @property
    def init_arm(self):
        return super().__getitem__('init_arm')

    @init_arm.setter
    def init_arm(self, init_arm):
        super().__setitem__('init_arm', init_arm)

    @property
    def armed(self):
        return super().__getitem__('armed')

    @armed.setter
    def armed(self, armed):
        super().__setitem__('armed', armed)

    def arm(self, conf, queue):
        logger.info('Standard Cue has not yet an arming method')
        self.armed = True

    def disarm(self, conf, queue):
        logger.info('Standard Cue has not yet an disarming method')
        self.armed = False

