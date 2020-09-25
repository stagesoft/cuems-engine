
from .Cue import Cue

class CueList(list):
    
    def __init__(self, *args):
        super().__init__(*args)
    
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
        super().__iadd__(other)
        self.sort(key=self.__sorting)
        return self

    def times(self):
        timelist = list()
        for cue in self:
            timelist.append(cue.time)
        return timelist

    def append(self, item):
        if not isinstance(item, Cue):
            raise TypeError('item is not of type %s' % Cue)
        super().append(item)  #append the item to itself (the list)

    def extend(self, other):
        super().extend(other)
