import uuid as uuid_module
from .Cue import Cue
from .CTimecode import CTimecode


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
        
        return None

    def arm(self, conf, queue, init = False):
        if self.disabled != True and (self.loaded == init or self.timecode != init):
            return_list = {}

            for item in self.contents:
                # We arm the item if :
                # - is not disabled
                # AND
                # - is loaded at init or is not really loaded or it is forced to load
                if item.disabled != True and item.loaded == init:
                    return_list += item.arm(conf, queue)

            return return_list
        else:
            return None

    def disarm(self, conf, queue):
        return_list = {}

        for item in self.contents:
            if item.loaded == True:
                return_list += item.arm(conf, queue)

        return return_list