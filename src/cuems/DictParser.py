import distutils.util

from .CuemsScript import CuemsScript
from .CueList import CueList
from .Cue import Cue
from .Outputs import *
from .AudioCue import AudioCue
from .DmxCue import DmxCue, DmxScene, DmxUniverse, DmxChannel
from .CTimecode import CTimecode
from .log import logger

PARSER_SUFFIX = 'Parser'
GENERIC_PARSER = 'GenericCueParser'

class CuemsParser():
    def __init__(self, init_dict):
        self.init_dict=init_dict

    def get_parser_class(self, class_string):
        parser_name = class_string + PARSER_SUFFIX
        try:
            parser_class = (globals()[parser_name], class_string)
        except KeyError as err:
            logger.debug("Could not find class {0}, reverting to generic parser class".format(err))
            parser_class = (globals()[GENERIC_PARSER], class_string)
        return parser_class

    def get_class(self, class_string):
        
        try:
            _class = globals()[class_string]
        except KeyError as err:
            logger.debug("Could not find class {0}".format(err))
            _class = None

        return _class

    def get_first_key(self, _dict):
        return list(_dict.keys())[0]


    def get_contained_dict(self, _dict):
        return list(_dict.values())[0]

    def convert_string_to_value(self, _string):
        if isinstance(_string, str):
            if (_string=='True' or _string=='False'):
                return bool(distutils.util.strtobool(_string))
            elif (_string.isdigit()):
                return int(_string)
            else:
                return _string
        else:
            return _string

    def parse(self):
        parser_class, class_string = self.get_parser_class(self.get_first_key(self.init_dict))
        item_obj = parser_class(init_dict=self.get_contained_dict(self.init_dict), class_string=class_string).parse()
        return item_obj

class CuemsScriptParser(CuemsParser):
    def __init__(self, init_dict, class_string):
        self.init_dict = init_dict
        self._class = self.get_class(class_string)
        self.item = self._class()
    
    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            if type(dict_value) is dict:
                if (len(list(dict_value))> 0):
                    parser_class, class_string = self.get_parser_class(dict_key)
                    self.item[dict_key.lower()] = parser_class(init_dict=dict_value, class_string=class_string).parse()
                    
            else:
                dict_value = self.convert_string_to_value(dict_value)
                self.item[dict_key] = dict_value
                
        return self.item

class CueListParser(CuemsScriptParser):
        
    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            if isinstance(dict_value, list):
                for cue in dict_value:
                    parser_class, unused_class_string = self.get_parser_class(self.get_first_key(cue))
                    item_obj = parser_class(init_dict=self.get_contained_dict(cue), class_string=self.get_first_key(cue)).parse()
                    self.item['contents'].append(item_obj)
            else:
                dict_value = self.convert_string_to_value(dict_value)
                self.item[dict_key] = dict_value
                
            
        return self.item

class GenericCueParser(CuemsScriptParser): 

    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            if type(dict_value) is dict:
                parser_class, class_string = self.get_parser_class(self.get_first_key(dict_value))
                self.item[dict_key] = parser_class(init_dict=self.get_contained_dict(dict_value), class_string=class_string).parse()
            else:
                dict_value = self.convert_string_to_value(dict_value)
                self.item[dict_key] = dict_value
        
        return self.item


class DmxSceneParser(GenericCueParser):
    pass

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():   
            for class_item in class_item_list:
                parser_class, class_string = self.get_parser_class(class_string)
                item_obj = parser_class(init_dict=class_item, class_string=class_string).parse()
                self.item.set_universe(item_obj, class_item['id'])
        return self.item

class DmxUniverseParser(GenericCueParser):

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():
            if class_string != 'id':
                for class_item in class_item_list:
                    parser_class, class_string = self.get_parser_class(class_string)
                    item_obj = parser_class(init_dict=class_item, class_string=class_string).parse()
                    self.item.set_channel(class_item['id'], item_obj)
        return self.item

class DmxChannelParser(GenericCueParser):

    def parse(self):
        self.item.value = self.init_dict['&']
        return self.item

class GenericSubObjectParser(GenericCueParser):
    
    def parse(self):
        self.item = self._class(self.init_dict)
        return self.item

class CTimecodeParser(GenericSubObjectParser):
    pass

class CueOutputsParser(GenericSubObjectParser):
    pass


class AudioCueOutputsParser(GenericSubObjectParser):
    pass

class DmxCueOutputsParser(GenericSubObjectParser):
    pass

class NoneTypeParser():
    def __init__(self, init_dict, class_string):
        pass

    def parse(self):
        return None