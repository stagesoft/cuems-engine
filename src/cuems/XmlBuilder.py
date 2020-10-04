import xml.etree.ElementTree as ET

from .log import logger



PARSER_SUFFIX = 'XmlBuilder'
GENERIC_BUILDER = 'GenericCueXmlBuilder'

class XmlBuilder():
    def __init__(self, _object, xml_tree = None):
        self._object = _object
        self.xml_tree = xml_tree
        self.class_name = type(_object).__name__

    def get_builder_class(self, _object):
        object_class_name = type(_object).__name__
        builder_class_name = object_class_name + PARSER_SUFFIX
        try:
            builder_class = globals()[builder_class_name]
        except KeyError as err:
            logger.debug("Could not find class {0}, reverting to generic builder class".format(err))
            builder_class = globals()[GENERIC_BUILDER]
        return builder_class
    
    def build(self):
        self.xml_tree = ET.Element('CueMs')
        builder_class = self.get_builder_class(self._object)
        self.xml_tree = builder_class(self._object, xml_tree = self.xml_tree).build()
        return self.xml_tree

class CuemsScriptXmlBuilder(XmlBuilder):

    def build(self):
        cue_element = ET.SubElement(self.xml_tree, self.class_name)
        for key, value in self._object.items():
            cue_subelement = ET.SubElement(cue_element, str(key))
            if isinstance(value, (str, bool, int, float)):
                cue_subelement.text = str(value)
            else:
                builder_class = self.get_builder_class(value)
                sub_object_element = builder_class(value, xml_tree = cue_subelement).build()
        return self.xml_tree

class CueListXmlBuilder(XmlBuilder):

    
    def build(self):
        cuelist_element = ET.SubElement(self.xml_tree, self.class_name)
        for cuelist_item in self._object:
            builder_class = self.get_builder_class(cuelist_item)
            self.xml_tree = builder_class(cuelist_item, xml_tree = cuelist_element).build()
        return self.xml_tree
    
        
class GenericCueXmlBuilder(XmlBuilder):
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, self.class_name)
        for key, value in self._object.items():
            cue_subelement = ET.SubElement(cue_element, str(key))
            if isinstance(value, (str, bool, int, float)):
                cue_subelement.text = str(value)
            else:
                builder_class = self.get_builder_class(value)
                sub_object_element = builder_class(value, xml_tree = cue_subelement).build()
        return self.xml_tree

class DmxSceneXmlBuilder(XmlBuilder):
 
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, self.class_name)
        universe_list = list(self._object.items())
        for universe in universe_list:
            builder_class = self.get_builder_class(universe[1])
            sub_object_element = builder_class(universe, xml_tree = cue_element).build()
            
        return self.xml_tree

class DmxUniverseXmlBuilder(XmlBuilder):
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object[1]).__name__, id=str(self._object[0]))
        channel_list = list(self._object[1].items())
        for channel in channel_list:
            builder_class = self.get_builder_class(channel[1])
            sub_object_element = builder_class(channel, xml_tree = cue_element).build()
        return self.xml_tree
    
class DmxChannelXmlBuilder(XmlBuilder):
    
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object[1]).__name__, id=str(self._object[0]))
        cue_element.text = str(self._object[1])

class GenericSubObjectXmlBuilder(XmlBuilder):
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, self.class_name)
        cue_element.text = str(self._object)
        return self.xml_tree

class CTimecodeXmlBuilder(GenericSubObjectXmlBuilder):
    pass

class CueOutputsXmlBuilder(XmlBuilder):

    def build(self):
        cue_element = ET.SubElement(self.xml_tree, self.class_name)

        if isinstance(self._object, dict):
            for key, item in self._object.items():
                cue_sub_element = ET.SubElement(cue_element, key)
                cue_sub_element.text = str(item)

        else:
            cue_element.text = str(self._object)
        return self.xml_tree

class AudioCueOutputsXmlBuilder(CueOutputsXmlBuilder):
    pass

class DmxCueOutputsXmlBuilder(CueOutputsXmlBuilder):
    pass
    
class NoneTypeXmlBuilder(GenericSubObjectXmlBuilder):
    pass
