import uuid as uuid_module
from .Cue import Cue
from .CTimecode import CTimecode


class CueList(Cue):
    
    def __init__(self, contents=[], offset=None):
        super().__setitem__('uuid', str(uuid_module.uuid1()))
        if offset is not None:
            super().__setitem__('timecode', True)
            if  isinstance(offset, CTimecode):
                super().__setitem__('offset', offset)
            else:
                super().__setitem__('offset', CTimecode(start_timecode=offset))
        else:
            super().__setitem__('timecode', False)

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
        
    
    def __sorting(self, cue):
        if cue.offset is None: # TODO: change this to somthing not so ugly
            return -99999
        else:
            return cue.offset
    
    def __add__(self, other):
        new_contents = self['contents'].copy()
        new_contents.append(other)
        new_contents.sort(key=self.__sorting)
        return new_contents

    def __iadd__(self, other):
        self['contents'].__iadd__(other)
        self['contents'].sort(key=self.__sorting)
        return self

    def times(self):
        timelist = list()
        for item in self['contents']:
            timelist.append(item.offset)
        return timelist

    def find(self, uuid):
        for item in self['contents']:
            if isinstance(item, Cue):
                if item.uuid == uuid:
                    return item
            else:
                return item.find(uuid)
        
        return None
