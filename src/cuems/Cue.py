from .CTimecode import CTimecode
from .Outputs import Outputs
from .Media import Media
from .log import logger
import uuid as uuid_module

class Cue(dict):
    def __init__(self, offset=None, init_dict = None, uuid=None ):
        if uuid is None:
            super().__setitem__('uuid', str(uuid_module.uuid4())) # TODO: Check safe and choose uuid version (4? 5?)
        
        if init_dict is not None:
            super().__init__(init_dict)

    @classmethod
    def from_dict(cls, init_dict):
        return cls(init_dict = init_dict)

    @property
    def uuid(self):
        return super().__getitem__('uuid')

    @uuid.setter
    def uuid(self, uuid):
        super().__setitem__('uuid', uuid)

    @property
    def id(self):
        return super().__getitem__('id')

    @id.setter
    def id(self, id):
        super().__setitem__('id', id)

    @property
    def name(self):
        return super().__getitem__('name')

    @name.setter
    def name(self, name):
        super().__setitem__('name', name)

    @property
    def description(self):
        return super().__getitem__('description')

    @description.setter
    def description(self, description):
        super().__setitem__('description', description)

    @property
    def disabled(self):
        return super().__getitem__('disabled')

    @disabled.setter
    def disabled(self, disabled):
        super().__setitem__('disabled', disabled)

    @property
    def loaded(self):
        return super().__getitem__('loaded')

    @loaded.setter
    def loaded(self, loaded):
        super().__setitem__('loaded', loaded)

    @property
    def timecode(self):
        return super().__getitem__('timecode')

    @timecode.setter
    def timecode(self, timecode):
        super().__setitem__('timecode', timecode)

    @property
    def offset(self):
        return super().__getitem__('offset')

    @offset.setter
    def offset(self, offset):
        super().__setitem__('offset', offset)

    @property
    def loop(self):
        return super().__getitem__('loop')

    @loop.setter
    def loop(self, loop):
        super().__setitem__('loop', loop)

    @property
    def prewait(self):
        return super().__getitem__('prewait')

    @prewait.setter
    def prewait(self, prewait):
        super().__setitem__('prewait', prewait)

    @property
    def postwait(self):
        return super().__getitem__('postwait')

    @postwait.setter
    def postwait(self, postwait):
        super().__setitem__('postwait', postwait)

    @property
    def post_action(self):
        return super().__getitem__('post_action')

    @post_action.setter
    def post_action(self, post_action):
        super().__setitem__('post_action', post_action)

    @property
    def target(self):
        return super().__getitem__('target')

    @target.setter
    def target(self, target):
        super().__setitem__('target', target)

    @property
    def ui_properties(self):
        return super().__getitem__('ui_properties')

    @ui_properties.setter
    def ui_properties(self, ui_properties):
        super().__setitem__('ui_properties', ui_properties)

    @property
    def media(self):
        return super().__getitem__('Media')

    @media.setter
    def media(self, media):
        super().__setitem__('Media', media)

    def type(self):
        return type(self)

    def __setitem__(self, key, value):
        if (key in ['offset', 'prewait', 'postwait']) and (value not in (None, "")):
            if isinstance(value, CTimecode):
                ctime_value = value
            else:
                if isinstance(value, (int, float)):
                    ctime_value = CTimecode(start_seconds = value)
                    ctime_value.frames = ctime_value.frames + 1
                elif isinstance(value, str):
                    ctime_value = CTimecode(value)
                elif isinstance(value, dict):
                    dict_timecode = value.pop('CTimecode', None)
                    if dict_timecode is None:
                        ctime_value = CTimecode()
                    else:
                        ctime_value = CTimecode(dict_timecode)

            super().__setitem__(key, ctime_value)

        else:
            super().__setitem__(key, value)

    def arm(self, conf, queue, init = False):
        if self.disabled != True and self.loaded == init:
            self.loaded = True

            return self.uuid
        else:
            return None

    def disarm(self, conf, queue):
        if self.loaded is True:
            self.loaded = False

            return self.uuid
        else:
            return None