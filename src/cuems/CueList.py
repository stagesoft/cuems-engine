import uuid as uuid_module
from .Cue import Cue
from .CTimecode import CTimecode


class CueList(dict):
    
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
        if cue.time is None: # TODO: change this to somthing not so ugly
            return -99999
        else:
            return cue.time
    
    def __add__(self, other):
        new_list = self.copy()
        new_list.extend(other)
        new_list.sort(key=self.__sorting)
        return new_list

    def __iadd__(self, other):
        self['contents'].__iadd__(other)
        self['contents'].sort(key=self.__sorting)
        return self

    def times(self):
        timelist = list()
        for cue in self['contents']:
            timelist.append(cue.time)
        return timelist

    '''
    def append(self, item):
        if not isinstance(item, Cue):
            raise TypeError('item is not of type %s' % Cue)
        self['contents'].append(item)  #append the item to itself (the list)

    def extend(self, other):
        super().extend(other)
    '''

    @property
    def timecode(self):
        return super().__getitem__('timecode')

    @timecode.setter
    def timecode(self, timecode):
        super().__setitem__('timecode', bool(timecode))
    
    @property
    def time(self):
        return super().__getitem__('time')

    @time.setter
    def time(self, time):
        super().__setitem__('time', time)
    
    @property
    def contents(self):
        return super().__getitem__('contents')

    @contents.setter
    def contents(self, contents):
        super().__setitem__('contents', contents)
    
    def find(self, uuid):
        for item in self:
            if isinstance(item, Cue):
                if item.uuid == uuid:
                    return item
            else:
                return item.find(uuid)
        
        return None

class TimecodeCueList(CueList):
    def __init__(self, *args):
        super().__init__(*args)

class FloatingCueList(CueList):
    def __init__(self, *args):
        super().__init__(*args)
