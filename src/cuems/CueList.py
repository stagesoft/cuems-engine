
from .Cue import Cue
from .CTimecode import CTimecode
class CueList(dict):
    
    def __init__(self, *args):
        super().__init__(*args)

        self.timecode = False
        self.time = CTimecode()
        self.contents = list()
            
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

    '''
    def __iadd__(self, other):
        super().__iadd__(other)
        self.sort(key=self.__sorting)
        return self
    '''

    def times(self):
        timelist = list()
        for cue in self:
            timelist.append(cue.time)
        return timelist

    '''
    def append(self, item):
        super().append(item)  #append the item to itself (the list)

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