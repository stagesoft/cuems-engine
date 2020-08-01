from CueList import CueList
from Cue import Cue
from Outputs import CueOutputs, AudioCueOutputs, DmxCueOutputs
from AudioCue import AudioCue
from DmxCue import DmxCue, DmxScene, DmxUniverse, DmxChannel
from CTimecode import CTimecode
from log import logger

PARSER_SUFFIX = 'Parser'

class CuemsParser():
    def __init__(self, init_dict):
        self.init_dict=init_dict

    def get_parser_class(self, class_string):
        parser_name = class_string + PARSER_SUFFIX
        try:
            parser_class = globals()[parser_name]
        except KeyError as err:
            logger.error("Could not find class {0}".format(err))
            parser_class =None
        return parser_class

    def get_class(self, caller_class):
        class_name = type(caller_class).__name__
        if class_name.endswith(PARSER_SUFFIX):
            class_name = class_name[:-6]
        try:
            _class = globals()[class_name]
        except KeyError as err:
            logger.error("Could not find class {0}".format(err))
            _class = None

        return _class

    def parse(self):
        parser_class = self.get_parser_class(next(iter(self.init_dict.keys())))
        print(self.init_dict)
        print(parser_class)
        item_obj = parser_class(init_dict=next(iter(self.init_dict.values()))).parse()
        return item_obj

class CueListParser(CuemsParser):
    def __init__(self, init_dict, cuelist=None):
        if cuelist is None:
            self.cuelist = CueList()
        else:
            self.cuelist = cuelist
        self.init_dict=init_dict
        
        
    
    def parse(self):
        for class_string, class_items_list in self.init_dict.items():   
            for class_item in class_items_list:
                parser_class = self.get_parser_class(class_string)
                item_obj = parser_class(init_dict=class_item).parse()
                self.cuelist.append(item_obj)
        return self.cuelist
    
    

class CueParser(CueListParser):
    def __init__(self, init_dict):
        self.init_dict = init_dict
        self._class = self.get_class(self)
        self.item = self._class(self.init_dict)
    
    def parse(self):
        for dict_key, dict_value in self.init_dict.items():
            if type(dict_value) is dict:
                parser_class = self.get_parser_class(list(dict_value)[0])
                class_dict = list(dict_value.values())[0]
                self.item[dict_key] = parser_class(init_dict=class_dict).parse()
            else:
                self.item[dict_key] = dict_value
        
        return self.item

class AudioCueParser(CueParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)

class DmxCueParser(CueParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)


class DmxSceneParser(CueParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():   
            for class_item in class_item_list:
                parser_class = self.get_parser_class(class_string)
                item_obj = parser_class(init_dict=class_item).parse()
                self.item.set_universe(item_obj, class_item['id'])
        return self.item

class DmxUniverseParser(CueParser):
    def __init__(self, init_dict):
        self.init_dict = init_dict
        self._class = self.get_class(self)
        self.item = self._class()

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():
            if class_string != 'id':
                for class_item in class_item_list:
                    parser_class = self.get_parser_class(class_string)
                    item_obj = parser_class(init_dict=class_item).parse()
                    self.item.set_channel(class_item['id'], item_obj)
        return self.item

class DmxChannelParser(CueParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)

    def parse(self):
        self.item.value = self.init_dict['&']
        return self.item

class GenericSubObjectParser(CueParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)
    
    def parse(self):
        _class = self.get_class(self)
        self.item = _class(self.init_dict)
        return self.item

class CTimecodeParser(GenericSubObjectParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)

class CueOutputsParser(GenericSubObjectParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)

class AudioCueOutputsParser(GenericSubObjectParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)

class DmxCueOutputsParser(GenericSubObjectParser):
    def __init__(self, init_dict):
        super().__init__(init_dict)

class NoneTypeParser():
    def __init__(self, init_dict):
        pass

    def parse(self):
        return None