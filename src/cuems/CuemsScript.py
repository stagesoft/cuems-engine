from .CueList import CueList
import uuid

class CuemsScript(dict):
    def __init__(self, timecode_cuelist=None, floating_cuelist=None):
        super().__setitem__('uuid', str(uuid.uuid1())) # TODO: Check safe and choose uuid version (4? 5?)
        super().__setitem__('timecode_cuelist', timecode_cuelist)
        super().__setitem__('floating_cuelist', floating_cuelist)
        

        # self.timecode_list = timecode_list
        # self.floating_list = floating_list
    
    @property
    def timecode_cuelist(self):
        return super().__getitem__('timecode_cuelist')

    @timecode_cuelist.setter
    def timecode_cuelist(self, cuelist):
        if isinstance(cuelist, CueList):
            super().__setitem__('timecode_cuelist', cuelist)
        else:
            raise NotImplementedError

    @property
    def floating_cuelist(self):
        return super().__getitem__('floating_cuelist')

    @floating_cuelist.setter
    def floating_cuelist(self, cuelist):
        if isinstance(cuelist, CueList):
            super().__setitem__('floating_cuelist', cuelist)
        else:
            raise NotImplementedError
