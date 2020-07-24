import xml.etree.ElementTree as ET

from log import *

from CueList import CueList

PARSER_SUFFIX = 'XmlBuilder'

class XmlBuilder():
    def __init__(self, _object):
        self._object = _object
        self.xml_tree = None
        
    def get_builder_class(self, _object):
        class_name = type(_object).__name__
        builder_name = class_name + PARSER_SUFFIX
        try:
            builder_class = globals()[builder_name]
        except KeyError as err:
            logger.error("Could not find class {0}".format(err))
            builder_class =None
        return builder_class
    
    def build(self):
        builder_class = self.get_builder_class(self._object)
        self.xml_tree = builder_class(self.xml_tree, self._object).build()
        return self.xml_tree
    
class CueListXmlBuilder(XmlBuilder):
    def __init__(self, xml_tree, _object):
        self._object = _object
        self.xml_tree = xml_tree 
        self.class_name = type(_object).__name__

        
    def build(self):
        self.xml_tree = ET.Element(self.class_name)
        for cuelist_item in self._object:
            builder_class = self.get_builder_class(cuelist_item)
            self.xml_tree = builder_class(self.xml_tree, cuelist_item).build()
        return self.xml_tree
        
class CueXmlBuilder(CueListXmlBuilder):
    def __init__(self, xml_tree, _object):
        self.xml_tree = xml_tree
        self._object = _object
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object).__name__)
        for key, value in self._object.items():
            cue_subelement = ET.SubElement(cue_element, str(key))
            if isinstance(value, (str, bool, int, float)):
                cue_subelement.text = str(value)
            else:
                builder_class = self.get_builder_class(value)
                sub_object = builder_class(cue_subelement, value).build()
        return self.xml_tree
    
class AudioCueXmlBuilder(CueXmlBuilder):
    def __init__(self, xml_tree, _object):
        super().__init__(xml_tree, _object)
    
class DmxCueXmlBuilder(CueXmlBuilder):
    def __init__(self, xml_tree, _object):
        super().__init__(xml_tree, _object)

class DmxSceneXmlBuilder(CueXmlBuilder):
    def __init__(self, xml_tree, _object):
        super().__init__(xml_tree, _object)
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object).__name__)
        universe_list = list(self._object.items())
        for universe in universe_list:
            builder_class = self.get_builder_class(universe[1])
            sub_object = builder_class(cue_element, universe).build()
            
        return self.xml_tree

class DmxUniverseXmlBuilder(CueXmlBuilder):
    def __init__(self, xml_tree, _object):
        super().__init__(xml_tree, _object)
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object[1]).__name__, id=str(self._object[0]))
        channel_list = list(self._object[1].items())
        for channel in channel_list:
            builder_class = self.get_builder_class(channel[1])
            sub_object = builder_class(cue_element, channel).build()
        return self.xml_tree
    
class DmxChannelXmlBuilder(CueXmlBuilder):
    def __init__(self, xml_tree, _object):
        super().__init__(xml_tree, _object)
    
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object[1]).__name__, id=str(self._object[0]))
        cue_element.text = str(self._object[1])
        
class CTimecodeXmlBuilder(CueXmlBuilder):
    def __init__(self, xml_tree, _object):
        super().__init__(xml_tree, _object)
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object).__name__)
        cue_element.text = str(self._object)
        return self.xml_tree
    
class NoneTypeXmlBuilder(CueXmlBuilder):
    def __init__(self, xml_tree, _object):
        super().__init__(xml_tree, _object)
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object).__name__)
        cue_element.text = str(self._object)
        return self.xml_tree