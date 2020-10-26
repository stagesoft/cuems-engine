from .CueList import CueList
import uuid as uuid_module
from .cuems_editor.CuemsUtils import date_now_iso_utc

class CuemsScript(dict):
    def __init__(self, uuid=None, name=None, date=None, cuelist=None):
        if uuid is None:
            super().__setitem__('uuid', str(uuid_module.uuid1()))
        else:
            super().__setitem__('uuid', uuid)
        super().__setitem__('name', name)
        if date is None:
            date = date_now_iso_utc()

        super().__setitem__('created', date)
        super().__setitem__('modified', date)
        super().__setitem__('cuelist', cuelist)
        
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

    @property
    def description(self):
        return super().__getitem__('description')

    @description.setter
    def description(self, description):
        super().__setitem__('description', description)

    @property
    def created(self):
        return super().__getitem__('created')

    @created.setter
    def created(self, created):
        super().__setitem__('created', created)

    @property
    def modified(self):
        return super().__getitem__('modified')

    @modified.setter
    def modified(self, modified):
        super().__setitem__('modified', modified)

    @property
    def cuelist(self):
        return super().__getitem__('cuelist')

    @cuelist.setter
    def cuelist(self, cuelist):
        if isinstance(cuelist, CueList):
            super().__setitem__('cuelist', cuelist)
        else:
            raise NotImplementedError

    def get_media(self):
        media_dict = dict()
        if self.cuelist is not None:
            for cue in self.cuelist.contents:
                if cue.media:
                    media_dict[cue.media] = type(cue)

        return media_dict

    def find(self, uuid):
        return self.cuelist.find(uuid)
