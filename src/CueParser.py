from CueList import CueList
from Cue import Cue
from AudioCue import AudioCue
from DmxCue import DmxCue, DmxScene, DmxUniverse, DmxChannel

class CueListParser():
    def __init__(self, init_dict, cuelist=None):
        if cuelist is None:
            self.cuelist = CueList()
        else:
            self.cuelist = cuelist
        self.init_dict=init_dict
        
        
    
    def parse(self):
        for class_string, class_items_list in self.init_dict.items():   
            for class_item in class_items_list:
            #    print(globals()[key])
            #    print(list_value)
                parser_class = self.get_parser_class(class_string)
                item_obj = parser_class(init_dict=class_item).parse()
                self.cuelist.append(item_obj)
        return self.cuelist
    
    def get_parser_class(self, class_string):
        parser_name = class_string + 'Parser'
        parser_class = globals()[parser_name]
        return parser_class

class CueParser(CueListParser):
    def __init__(self, init_dict):
        self.init_dict = init_dict
        self._class = globals()['Cue']
    
    def parse(self):
        self.item = self._class(init_dict = self.init_dict)
        if self.init_dict['time'] != None:
            self.item.time = self.init_dict['time']
        return self.item

class AudioCueParser(CueParser):
    def __init__(self, init_dict):
        self.init_dict = init_dict
        self._class = globals()['AudioCue']

class DmxCueParser(CueParser):
    def __init__(self, init_dict):
        self.init_dict = init_dict
        self._class = globals()['DmxCue']
        dmxscene = init_dict.pop('dmx_scene', None)
        self.dmxscene = dmxscene

    def parse(self):
        if self.dmxscene is not None:
            self.item = self._class(init_dict = self.init_dict)
            self.item.scene = DmxSceneParser(init_dict=self.dmxscene).parse()
        if self.init_dict['time'] != None:
            self.item.time = self.init_dict['time']
        return self.item

class DmxSceneParser(CueParser):
    def __init__(self, init_dict):
        self.init_dict=init_dict
        self.item = DmxScene()

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():   
            for class_item in class_item_list:
            #    print(globals()[key])
            #    print(list_value)
                parser_class = self.get_parser_class(class_string)
                item_obj = parser_class(init_dict=class_item).parse()
                self.item.set_universe(item_obj, class_item['@id'])
        return self.item

class DmxUniverseParser(CueParser):
    def __init__(self, init_dict):
        self.init_dict=init_dict
        self.item = DmxUniverse()

    def parse(self):
        for class_string, class_item_list in self.init_dict.items():
            if class_string != '@id':
                for class_item in class_item_list:
                #    print(globals()[key])
                #    print(list_value)
                    parser_class = self.get_parser_class(class_string)
                    item_obj = parser_class(init_dict=class_item).parse()
                    self.item.set_channel(class_item['@id'], item_obj)
        return self.item

class DmxChannelParser(CueParser):
    def __init__(self, init_dict):
        self.init_dict=init_dict
        self.item = DmxChannel()

    def parse(self):
        self.item.value = self.init_dict['$']
        return self.item