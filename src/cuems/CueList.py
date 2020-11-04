import uuid as uuid_module
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
        
        return None

    def arm(self, conf, queue, armed_list, init = False):
        if self.enabled and self.loaded == init:
            if not self in armed_list:
                for item in self.contents:
                    # We arm the item if :
                    # - is enabled
                    # AND
                    # - is marked as loaded at init
                    item.arm(conf, queue, armed_list, init)

                self.loaded = True

                armed_list.append(self)

            if self.post_go == 'go':
                self._target_object.arm(conf, queue, armed_list)

            return True
        else:
            return False

    def go(self, ossia, mtc):
        for item in self.contents:
            item.go(ossia, mtc)

    def disarm(self, conf, queue, armed_list):
        for item in self.contents:
            if item.loaded == True:
                if not item.disarm(conf, queue, armed_list):
                    logger.error(f'Could not unload properly cue {item.uuid}')
                
                try:
                    armed_list.remove(item)
                except ValueError:
                    logger.error(f'Trying to disarm {item.uuid} was not on armed list')

        try:
            if self in armed_list:
                armed_list.remove(self)
        except:
            pass
        
        self.loaded = False
