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

    def arm(self, conf, queue):
        for item in self.contents:
            if item.timecode == False:
                item.arm(conf, queue)