from .log import logger
from .CueList import CueList
import uuid as uuid_module
from .cuems_editor.CuemsUtils import date_now_iso_utc

class CuemsScript(dict):
    def __init__(self, init_dict = None):
        if init_dict:
            super().__init__(init_dict)       

    @property
    def uuid(self):
        return super().__getitem__('uuid')

    @uuid.setter
    def uuid(self, uuid):
        super().__setitem__('uuid', uuid)

    @property
    def unix_name(self):
        return super().__getitem__('unix_name')

    @unix_name.setter
    def unix_name(self, unix_name):
        super().__setitem__('unix_name', unix_name)

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

    # returns a dict of UNIQUE media (no duplicates)

    def get_media(self, cuelist = None):
        '''Gets all the media files list present on a cuelist.'''
        media_dict = dict()

        # If no cuelist is specified we are looking inside our own
        # script object, so our cuelist is our self cuelist
        if not cuelist:
            cuelist = self.cuelist

        if cuelist.contents:
            for cue in cuelist.contents:
                if type(cue)==CueList:
                    # If the cue is a cuelist, let's recurse
                    media_dict.update(self.get_media(cuelist=cue))
                else:
                    try:
                        if cue.media:
                            media_dict[cue.media.file_name] = type(cue)
                    except KeyError:
                        pass
                        # logger.debug("cue with no media")
        return media_dict

    def get_own_media(self, cuelist = None, config = None):
        '''Gets the media files list present on the script which are 
        related to the specified node uuid, usually our local UUID,
        as we are looking for our own needed media files'''

        media_dict = dict()

        # If no cuelist is specified we are looking inside our own
        # script object, so our cuelist is our self cuelist
        if not cuelist:
            cuelist = self.cuelist

        if cuelist.contents:
            for cue in cuelist.contents:
                if type(cue)==CueList:
                    # If the cue is a cuelist, let's recurse
                    media_dict.update(self.get_own_media(cuelist=cue, config=config))
                else:
                    try:
                        if cue.media:
                            cue.check_mappings(config)
                            if cue._local:
                                media_dict[cue.media.file_name] = type(cue)
                    except KeyError:
                        pass
                        # logger.debug("cue with no media")
        return media_dict

    def find(self, uuid):
        return self.cuelist.find(uuid)
