
from os import path
from pyossia import ossia
from time import sleep
from threading import Thread

from .Cue import Cue
# from .AudioPlayer import AudioPlayer
# from .OssiaServer import PlayerOSCConfData
from .log import logger

class ActionCue(Cue):
    def __init__(self, init_dict = None):
        if init_dict:
            super().__init__(init_dict)
            
        self._action_target_object = None

    @property
    def action_type(self):
        return super().__getitem__('action_type')

    @action_type.setter
    def action_type(self, action_type):
        super().__setitem__('action_type', action_type)

    @property
    def action_target(self):
        return super().__getitem__('action_target')

    @action_target.setter
    def action_target(self, action_target):
        super().__setitem__('action_target', action_target)

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

        self.loaded = True
        if not self in self._armed_list:
            self._armed_list.append(self)

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
        if self._target_object is not None:
            self._target_object.arm(self._conf, ossia, self._armed_list)

        # PREWAIT
        if self.prewait > 0:
            sleep(self.prewait.milliseconds / 1000)

        # PLAY : specific audio cue stuff
        if self.action_type == 'load':
            self._action_target_object.arm(self._conf, ossia, self._armed_list)
        elif self.action_type == 'unload':
            self._action_target_object.disarm(ossia)
        elif self.action_type == 'play':
            self._action_target_object.go(ossia, mtc)
        elif self.action_type == 'pause':
            pass
        elif self.action_type == 'stop':
            pass
        elif self.action_type == 'enable':
            self._action_target_object.enabled = True
        elif self.action_type == 'disable':
            self._action_target_object.enabled = False
        elif self.action_type == 'fade_in':
            self._action_target_object.enabled = False
        elif self.action_type == 'fade_out':
            self._action_target_object.enabled = False
        elif self.action_type == 'wait':
            self._action_target_object.enabled = False
        elif self.action_type == 'go_to':
            self._action_target_object.enabled = False
        elif self.action_type == 'pause_project':
            self._action_target_object.enabled = False
        elif self.action_type == 'resume_project':
            self._action_target_object.enabled = False

        # POSTWAIT
        if self.postwait > 0:
            sleep(self.postwait.milliseconds / 1000)

        # POST-GO GO
        if self.post_go == 'go':
            self._target_object.go(ossia, mtc)

        # DISARM
        if self in self._armed_list:
            self.disarm(ossia)

    def disarm(self, ossia_server = None):
        if self.loaded is True:
            try:
                if self in self._armed_list:
                    self._armed_list.remove(self)
            except:
                pass

            self.loaded = False

            return True
        else:
            return False

