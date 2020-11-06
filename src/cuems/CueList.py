import uuid as uuid_module
from time import sleep
from threading import Thread
from .Cue import Cue
from .CTimecode import CTimecode
from .log import logger


class CueList(Cue):
    
    def __init__(self, contents=[], offset=None):
        empty_keys = {"uuid":"", "id":"", "name": "", "description": "", "enabled": "", "loaded": "", "timecode": "", "offset": "", "loop": "", "prewait": "", "postwait": "", "post_go" : "", "target" : "", "ui_properties": "", "contents": []}
        super().__init__(init_dict=empty_keys)
        super().__setitem__('uuid', str(uuid_module.uuid1()))
        if isinstance(contents, list):
            super().__setitem__('contents', contents)
        else:
            super().__setitem__('contents', [contents])

    @property    
    def contents(self):
        return super().__getitem__('contents')

    @contents.setter
    def contents(self, contents):
        super().__setitem__('contents', contents)
    
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
                for item in self.contents:
                    # We arm the item if :
                    # - is enabled
                    # AND
                    # - is marked as loaded at init
                    item.arm(self.conf, ossia_queue, self.armed_list, init)

                self.loaded = True

                armed_list.append(self)

            if self.post_go == 'go':
                self._target_object.arm(self.conf, ossia_queue, self.armed_list)

            return True
        else:
            return False

    def go(self, ossia, mtc):
        if not self.loaded:
            logger.error(f'{self.__class__.__name__} {self.uuid} not loaded to go...')
            raise Exception(f'{self.__class__.__name__} {self.uuid} not loaded to go')

        else:
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
        try:
            for item in self.contents:
                item.go(ossia, mtc)
        except Exception as e:
            logger.exception(e)

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
