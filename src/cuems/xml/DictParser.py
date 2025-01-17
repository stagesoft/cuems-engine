# DEV: Move to cuems-utils
import distutils.util

from ..CuemsScript import CuemsScript
from ..cues.CueList import CueList
from ..cues.Cue import Cue
from ....dev.Media import Media, region
from ..UI_properties import UI_properties
from ..cues.CueOutput import CueOutput, AudioCueOutput, VideoCueOutput, DmxCueOutput
from ..cues.AudioCue import AudioCue
from ..cues.VideoCue import VideoCue
from ..cues.ActionCue import ActionCue
from ..cues.DmxCue import DmxCue, DmxScene, DmxUniverse, DmxChannel
from ..cues.ActionCue import ActionCue
from ..CTimecode import CTimecode
from ..log import logger
from ..cuems_nodeconf.CuemsNode import CuemsNodeDict, CuemsNode

PARSER_SUFFIX = 'Parser'
GENERIC_PARSER = 'GenericParser'

class GenericDict(dict):
    pass

class CuemsParser():
    def __init__(self, init_dict):
        self.init_dict=init_dict

    def get_parser_class(self, class_string):
        parser_name = class_string + PARSER_SUFFIX
        try:
            parser_class = (globals()[parser_name], class_string)
        except KeyError as err:
            # logger.debug("Could not find class {0}, reverting to generic parser class".format(err))
            parser_class = (globals()[GENERIC_PARSER], class_string)
        return parser_class

    def get_class(self, class_string):
        
        try:
            _class = globals()[class_string]
        except KeyError as err:
            # logger.debug("Could not find class {0}".format(err))
            _class = GenericDict
        return _class

    def get_first_key(self, _dict):
        return list(_dict.keys())[0]


    def get_contained_dict(self, _dict):
        return list(_dict.values())[0]

    def convert_string_to_value(self, _string):
        bool_strings = ['true', 'false']
        null_strings = ['none', 'null']
        if isinstance(_string, str):
            if (_string.lower() in bool_strings):
                return bool(distutils.util.strtobool(_string.lower()))
            elif (_string.lower() in null_strings):
                return None
            elif (_string.isdigit()):
                return int(_string)
            else:
                try:
                    return float(_string)
                except ValueError:
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
        self.class_string = class_string
        self._class = self.get_class(class_string)
        self.item_csp = self._class()
    
    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            if type(dict_value) is dict:
                if (len(list(dict_value))> 0):
                    parser_class, class_string = self.get_parser_class(dict_key)
                    self.item_csp[dict_key.lower()] = parser_class(init_dict=dict_value, class_string=class_string).parse()
                    
            else:
                dict_value = self.convert_string_to_value(dict_value)
                self.item_csp[dict_key] = dict_value
                
        return self.item_csp

class CueListParser(CuemsScriptParser):
    def __init__(self, init_dict, class_string):
        self.init_dict = init_dict
        self.class_string = class_string
        self._class = self.get_class(class_string)
        self.item_clp = self._class()
        
    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            if isinstance(dict_value, list):
                local_list = []
                for cue in dict_value:
                    parser_class, unused_class_string = self.get_parser_class(self.get_first_key(cue))
                    item_obj = parser_class(init_dict=self.get_contained_dict(cue), class_string=self.get_first_key(cue)).parse()
                    local_list.append(item_obj)

                self.item_clp['contents'] = local_list
            elif isinstance(dict_value, dict):
                key_parser_class, key_class_string = self.get_parser_class(dict_key)
                if key_parser_class == GenericParser:
                    value_parser_class, value_class_string = self.get_parser_class(self.get_first_key(dict_value))
                
                if value_parser_class == GenericParser:
                    self.item_clp[dict_key] = key_parser_class(init_dict=dict_value, class_string=key_class_string).parse()
                else:
                    self.item_clp[dict_key] = value_parser_class(init_dict=dict_value, class_string=value_class_string).parse()

            else:
                dict_value = self.convert_string_to_value(dict_value)
                self.item_clp[dict_key] = dict_value
                
        return self.item_clp

class GenericParser(CuemsScriptParser): 
    def __init__(self, init_dict, class_string):
        self.init_dict = init_dict
        self.class_string = class_string
        self._class = self.get_class(class_string)
        self.item_gp = self._class()
        
    def parse(self):
        if self._class == GenericDict:
            self.item_gp = self.init_dict

        elif isinstance(self.init_dict, dict):
            for dict_key, dict_value in self.init_dict.items():
                if isinstance (dict_value, dict):
                    key_parser_class, key_class_string = self.get_parser_class(dict_key)
                    if key_parser_class == GenericParser:
                        value_parser_class, value_class_string = self.get_parser_class(self.get_first_key(dict_value))

                    if value_parser_class == GenericParser:
                        self.item_gp[dict_key] = key_parser_class(init_dict=dict_value, class_string=key_class_string).parse()
                    else:
                        self.item_gp[dict_key] = value_parser_class(init_dict=dict_value, class_string=value_class_string).parse()
                elif isinstance(dict_value, list):
                    local_list = []
                    parser_class, class_string = self.get_parser_class(dict_key)
                    for list_item in dict_value:

                        item_obj = parser_class(init_dict=list_item, class_string=class_string).parse()
                        local_list.append(item_obj)
                    self.item_gp[dict_key] = local_list
                else:
                    dict_value = self.convert_string_to_value(dict_value)
                    self.item_gp[dict_key] = dict_value

        return self.item_gp

class DmxSceneParser(GenericParser):
    pass

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():   
            for class_item in class_item_list:
                parser_class, class_string = self.get_parser_class(class_string)
                item_obj = parser_class(init_dict=class_item, class_string=class_string).parse()
                self.item_gp.set_universe(item_obj, class_item['id'])
        return self.item_gp

class DmxUniverseParser(GenericParser):

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():
            if class_string != 'id':
                for class_item in class_item_list:
                    parser_class, class_string = self.get_parser_class(class_string)
                    item_obj = parser_class(init_dict=class_item, class_string=class_string).parse()
                    self.item_gp.set_channel(class_item['id'], item_obj)
        return self.item_gp

class DmxChannelParser(GenericParser):

    def parse(self):
        self.item_gp.value = self.init_dict['&']
        return self.item_gp

class GenericSubObjectParser(GenericParser):
    
    def parse(self):
        self.item_gp = self._class(self.init_dict)
        return self.item_gp

class CTimecodeParser(GenericSubObjectParser):  

    def parse(self):
        self.item_gp = self.init_dict
        return self.item_gp


class OutputsParser(GenericParser):
    def __init__(self, init_dict, class_string, parent_class=None):
        self.init_dict = init_dict

    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            self._class = self.get_class(dict_key)
            self.item_op = self._class(dict_value)

        return self.item_op

class regionsParser(GenericParser):
    def __init__(self, init_dict, class_string, parent_class=None):
        self.init_dict = init_dict
        self.class_string = class_string
        self._class = self.get_class(class_string)
        self.item_rp = self._class()
        
    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            key_parser_class, key_class_string = self.get_parser_class(dict_key)
            self.item_rp = key_parser_class(init_dict=dict_value, class_string=key_class_string).parse()

        return self.item_rp

class AudioCueOutputParser(OutputsParser):
    pass

class VideoCueOutputParser(OutputsParser):
    pass
class DmxCueOutputParser(OutputsParser):
    pass

class CuemsNodeDictParser(OutputsParser):
    def parse(self):
        self.item_rp = list()
        for item in self.init_dict:
            for dict_key, dict_value in item.items():
                key_parser_class, key_class_string = self.get_parser_class(dict_key)
                self.item_rp.append(key_parser_class(init_dict=dict_value, class_string=key_class_string).parse()) 

        return self.item_rp

class CuemsNodeParser(GenericParser):
    pass

class NoneTypeParser():
    def __init__(self, init_dict, class_string):
        pass

    def parse(self):
        return None
