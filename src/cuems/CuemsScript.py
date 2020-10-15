from .Cue import Cue
from .CueList import CueList, TimecodeCueList, FloatingCueList
import uuid as uuid_module

class CuemsScript(dict):
    def __init__(self, uuid=None, name=None, date=None, timecode_cuelist=None, floating_cuelist=None ):
        if uuid is None:
            super().__setitem__('uuid', str(uuid_module.uuid1()))
        else:
            super().__setitem__('uuid', uuid)
        super().__setitem__('name', name)
        super().__setitem__('date', date)
        # super().__setitem__('timecode_cuelist', timecode_cuelist)
        # super().__setitem__('floating_cuelist', floating_cuelist)
        # self.timecode_list = timecode_list
        # self.floating_list = floating_list

    @property
    def uuid(self):
        return super().__getitem__('uuid')

    @uuid.setter
    def uuid(self, uuid):
        super().__setitem__('uuid', uuid)

    @property
    def name(self):
        return super().__getitem__('name')

    @name.setter
    def name(self, name):
        super().__setitem__('name', name)

    '''
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
    '''

    def get_media(self):
        media_dict = dict()
        '''
        if self.timecode_cuelist is not None:
            for cue in self.timecode_cuelist:
                if cue.media:
                    media_dict[cue.media] = type(cue)

        if self.floating_cuelist is not None:
            for cue in self.floating_cuelist:
                if cue.media:
                    media_dict[cue.media] = type(cue)
        '''

        for item in self:
            if isinstance(item, Cue):
                media_dict[item.media] = type(item)
            elif isinstance(item, CueList):
                media_dict = {media_dict, CuemsScript.get_media(item)}

        return media_dict

    def find(self, uuid):
        if uuid == self.uuid:
            return self
        else:
            for item in self:
                if item.uuid == uuid:
                    return item

        return None
        
