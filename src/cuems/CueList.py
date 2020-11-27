import uuid as uuid_module
from time import sleep
from threading import Thread
from .Cue import Cue
from .CTimecode import CTimecode
from .log import logger


class CueList(Cue):
    def __init__(self, init_dict = None):
        if init_dict:
            super().__init__(init_dict)

    @property    
    def contents(self):
        return super().__getitem__('contents')

    @contents.setter
    def contents(self, contents):
        super().__setitem__('contents', contents)

    @property
    def uuid(self):
        return super().__getitem__('uuid')
    
    def __add__(self, other):
        new_contents = self['contents'].copy()
        new_contents.append(other)
        return new_contents

    def __iadd__(self, other):
        self['contents'].__iadd__(other)
        return self

    def times(self):
        timelist = list()
        for item in self['contents']:
            timelist.append(item.offset)
        return timelist

    def find(self, uuid):
        if self.uuid == uuid:
            return self
        else:
            for item in self.contents:
                if item.uuid == uuid:
                    return item
                elif isinstance(item, CueList):
                    recursive = item.find(uuid)
                    if recursive != None:
                        return recursive
            
        return None

    def get_media(self):
        media_dict = dict()
        for item in self.contents:
            if isinstance(item, CueList):
                media_dict.update( item.get_media() )
            else:
                try:
                    if item['Media']:
                        media_dict[item.uuid] = [item['Media']['file_name'], item.__class__.__name__]
                except KeyError:
                        media_dict[item.uuid] = {'media' : None, 'type' : item.__class__.__name__}
        
        return media_dict

    def arm(self, conf, ossia_queue, armed_list, init = False):
        self.conf = conf
        self.armed_list = armed_list

        if self.enabled and self.loaded == init:
            if not self in armed_list:
                self.contents[0].arm(self.conf, ossia_queue, self.armed_list, init)

                self.loaded = True

                armed_list.append(self)

            if self.post_go == 'go':
                self._target_object.arm(self.conf, ossia_queue, self.armed_list, init)

            return True
        else:
            return False

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
            self._target_object.arm(self.conf, ossia, self.armed_list)

        # PREWAIT
        if self.prewait > 0:
            sleep(self.prewait.milliseconds / 1000)

        # PLAY : specific go the first cue in the list
        try:
            if self.contents:
                self.contents[0].go(ossia, mtc)
        except Exception as e:
            logger.exception(e)

        # POSTWAIT
        if self.postwait > 0:
            sleep(self.postwait.milliseconds / 1000)

        if self.post_go == 'go':
            self._target_object.go(ossia, mtc)

        try:
            while self._player.is_alive():
                sleep(0.05)
        except AttributeError:
            return
        
        if self in self.armed_list:
            self.disarm(ossia.conf_queue)

    def disarm(self, ossia_queue):
        for item in self.contents:
            if item.loaded and item in self.armed_list:
                item.disarm(ossia_queue)

        if self.post_go == 'go':
            self._target_object.disarm(ossia_queue)

        try:
            if self in self.armed_list:
                self.armed_list.remove(self)
        except:
            pass
        
        self.loaded = False

    def get_next_cue(self):
        cue_to_return = None
        if self.contents:
            if self.contents[0].post_go == 'pause':
                cue_to_return = self.contents[0]._target_object
            else:
                cue_to_return = self.contents[0].get_next_cue()
            
            if cue_to_return:
                return cue_to_return       

        if self.target:
            if self.post_go == 'pause':
                return self._target_object
            else:
                return self._target_object.get_next_cue()
        else:
            return None

