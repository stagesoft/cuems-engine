from ..CTimecode import CTimecode
from .CueOutput import AudioCueOutput, VideoCueOutput, DmxCueOutput
from ....dev.Media import Media
from ..log import logger
import uuid as uuid_module
from time import sleep
from threading import Thread

class Cue(dict):
    def __init__(self, init_dict = None):
        if init_dict:
            super().__init__(init_dict)
            
        self._target_object = None
        self._conf = None
        self._armed_list = None
        self._start_mtc = CTimecode()
        self._end_mtc = CTimecode()
        self._end_reached = False
        self._go_thread = None
        self._stop_requested = False
        self._local = False

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
    def media(self):
        return super().__getitem__('Media')

    @media.setter
    def media(self, media):
        super().__setitem__('Media', media)

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

    def arm(self, conf, ossia, armed_list, init = False):
        self._conf = conf
        self._armed_list = armed_list

        if not self.enabled:
            if self.loaded and self in self._armed_list:
                self.disarm(ossia)
            return False
        elif self.loaded and not init:
            if not self in self._armed_list:
                self._armed_list.append(self)
            return True

        if self.post_go == 'go':
            self._target_object.arm(self._conf, ossia, self._armed_list, init)

        return True

    def go(self, ossia, mtc):
        if not self.loaded:
            logger.error(f'{self.__class__.__name__} {self.uuid} not loaded to go...')
            raise Exception(f'{self.__class__.__name__} {self.uuid} not loaded to go')

        else:
            # THREADED GO
            thread = Thread(name = f'GO:{self.__class__.__name__}:{self.uuid}', target = self.go_thread, args = [ossia, mtc])
            thread.start()

    def go_thread(self, ossia, mtc):
        # ARM NEXT TARGET
        if self._target_object:
            self._target_object.arm(self._conf, ossia, self._armed_list)

        # PREWAIT
        if self.prewait > 0:
            sleep(self.prewait.milliseconds / 1000)

        # PLAY WHATEVER A SIMPLE CUE WOULD PLAY

        # POSTWAIT
        if self.postwait > 0:
            sleep(self.postwait.milliseconds / 1000)

        # POST-GO GO
        if self.post_go == 'go':
            self._target_object.go(ossia, mtc)

        if self in self._armed_list:
            self.disarm(ossia)


    def disarm(self, ossia = None):
        if self.loaded is True:
            self.loaded = False

            if self in self._armed_list:
                self._armed_list.remove(self)

            return True
        else:
            return False

    def get_next_cue(self):
        if self.target:
            if self.post_go == 'pause':
                return self._target_object
            else:
                return self._target_object.get_next_cue()
        else:
            return None

    def check_mappings(self, settings):
        return True

    def stop(self):
        pass
