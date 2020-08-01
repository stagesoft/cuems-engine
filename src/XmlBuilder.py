import xml.etree.ElementTree as ET

from log import logger



PARSER_SUFFIX = 'XmlBuilder'

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
            logger.error("Could not find class {0}".format(err))
            builder_class =None
        return builder_class
    
    def build(self):
        builder_class = self.get_builder_class(self._object)
        self.xml_tree = builder_class(self._object, xml_tree = self.xml_tree).build()
        return self.xml_tree

class CuemsScriptXmlBuilder(XmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
        
    
    def build(self):
        print(self.class_name)
        self.xml_tree = ET.Element(self.class_name)
        for key, value in self._object.items():
            cue_subelement = ET.SubElement(self.xml_tree, str(key))
            if isinstance(value, (str, bool, int, float)):
                cue_subelement.text = str(value)
            else:
                builder_class = self.get_builder_class(value)
                sub_object_element = builder_class(value, xml_tree = cue_subelement).build()
        return self.xml_tree

class CueListXmlBuilder(CuemsScriptXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
    
    def build(self):
        print(self.class_name)
        cuelist_element = ET.SubElement(self.xml_tree, self.class_name)
        print(self._object)
        for cuelist_item in self._object:
            builder_class = self.get_builder_class(cuelist_item)
            self.xml_tree = builder_class(cuelist_item, xml_tree = cuelist_element).build()
        return self.xml_tree
    
        
class CueXmlBuilder(CueListXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
        
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
    
class AudioCueXmlBuilder(CueXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
    
class DmxCueXmlBuilder(CueXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)

class DmxSceneXmlBuilder(CueXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, self.class_name)
        universe_list = list(self._object.items())
        for universe in universe_list:
            builder_class = self.get_builder_class(universe[1])
            sub_object_element = builder_class(universe, xml_tree = cue_element).build()
            
        return self.xml_tree

class DmxUniverseXmlBuilder(CueXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object[1]).__name__, id=str(self._object[0]))
        channel_list = list(self._object[1].items())
        for channel in channel_list:
            builder_class = self.get_builder_class(channel[1])
            sub_object_element = builder_class(channel, xml_tree = cue_element).build()
        return self.xml_tree
    
class DmxChannelXmlBuilder(CueXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
    
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, type(self._object[1]).__name__, id=str(self._object[0]))
        cue_element.text = str(self._object[1])

class GenericSubObjectXmlBuilder(CueXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
        
    def build(self):
        cue_element = ET.SubElement(self.xml_tree, self.class_name)
        cue_element.text = str(self._object)
        return self.xml_tree

class CTimecodeXmlBuilder(GenericSubObjectXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)

class CueOutputsXmlBuilder(GenericSubObjectXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)

class AudioCueOutputsXmlBuilder(GenericSubObjectXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)

class DmxCueOutputsXmlBuilder(GenericSubObjectXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
    
class NoneTypeXmlBuilder(GenericSubObjectXmlBuilder):
    def __init__(self, _object, xml_tree):
        super().__init__(_object, xml_tree)
