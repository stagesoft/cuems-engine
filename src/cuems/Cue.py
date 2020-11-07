from .CTimecode import CTimecode
from .Outputs import Outputs
from .Media import Media
from .log import logger
import uuid as uuid_module
from time import sleep
from threading import Thread

class Cue(dict):
    def __init__(self, offset=None, init_dict = None, uuid=None ):
        if uuid is None:
            super().__setitem__('uuid', str(uuid_module.uuid4())) # TODO: Check safe and choose uuid version (4? 5?)
        
        if offset is not None:
            super().__setitem__('timecode', True)
            self.__setitem__('offset', offset)
        else:
            super().__setitem__('timecode', False)

        self._target_object = None
        
        if init_dict is not None:
            super().__init__(init_dict)

        self.conf = None
        self.armed_list = None

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
    def enabled(self):
        return super().__getitem__('enabled')

    @enabled.setter
    def enabled(self, enabled):
        super().__setitem__('enabled', enabled)

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
        self.__setitem__('offset', offset)

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
    def post_go(self):
        return super().__getitem__('post_go')

    @post_go.setter
    def post_go(self, post_go):
        super().__setitem__('post_go', post_go)

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
    def Media(self):
        return super().__getitem__('Media')

    @Media.setter
    def Media(self, Media):
        super().__setitem__('Media', Media)
    def target_object(self, target_object):
        self._target_object = target_object

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
                    elif isinstance(dict_timecode, int):
                        ctime_value = CTimecode(start_seconds = dict_timecode)
                    else:
                        ctime_value = CTimecode(dict_timecode)

            super().__setitem__(key, ctime_value)

        else:
            super().__setitem__(key, value)

    def arm(self, conf, ossia_queue, armed_list, init = False):
        self.conf = conf
        self.armed_list = armed_list

        if not self.enabled:
            if self.loaded and self in self.armed_list:
                self.disarm(ossia_queue)
            return False
        elif self.loaded and not init:
            if not self in self.armed_list:
                self.armed_list.append(self)
            return True

        return True

    def go(self, ossia, mtc):
        if not self.loaded:
            logger.error(f'{self.__class__.__name__} {self.uuid} not loaded to go...')
            raise Exception(f'{self.__class__.__name__} {self.uuid} not loaded to go')

        else:
            # ARM NEXT TARGET
            if self._target_object is not None:
                self._target_object.arm(self.conf, ossia.conf_queue, self.armed_list)

            # GO
            thread = Thread(name = f'GO:{self.__class__.__name__}:{self.uuid}', target = self.go_thread, args = [ossia, mtc])

            # PREWAIT
            if self.prewait > 0:
                sleep(self.prewait.milliseconds / 1000)

            # PLAY
            thread.start()

            # POSTWAIT
            if self.postwait > 0:
                sleep(self.postwait.milliseconds / 1000)

            if self.post_go == 'go':
                self._target_object.go(ossia, mtc)

    def go_thread(self, ossia, mtc):

        if self in self.armed_list:
            self.disarm(ossia.conf_queue)


    def disarm(self, ossia_queue):
        if self.loaded is True:
            self.loaded = False

            if self in self.armed_list:
                self.armed_list.remove(self)

            return True
        else:
            return False

    def get_next_cue(self):
        if self.target is None:
            return None
        else:
            if self.post_go == 'pause':
                return self._target_object
            else:
                return self._target_object.get_next_cue()