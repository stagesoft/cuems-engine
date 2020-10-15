""" For the moment it works with pip3 install xmlschema==1.1.2
 """

import xml.etree.ElementTree as ET
import xmlschema
import datetime  as DT
import os
import json

from .log import logger
from .CTimecode import CTimecode
from .CMLCuemsConverter import CMLCuemsConverter
from .DictParser import CuemsParser
from .XmlBuilder import XmlBuilder


class CuemsXml():
    def __init__(self,schema=None,xmlfile=None):
        self.converter = CMLCuemsConverter
        self.schema_object = None
        self._xmlfile = None
        self.schema = schema
        self.xmlfile = xmlfile
        self.xmldata = None
        self._schema = None
        
    
    @property
    def schema(self):
        return self._schema
        

    @schema.setter
    def schema(self, path):
        if path is not None:
            if os.path.isfile(path):
                self._schema = path
                self.schema_object = xmlschema.XMLSchema11(self._schema, converter=self.converter)
            else:
                raise FileNotFoundError("schema file not found")


    @property
    def xmlfile(self):
        return self._xmlfile

    @xmlfile.setter
    def xmlfile(self, path):
        self._xmlfile = path
            
    def validate(self):
        return self.schema_object.validate(self.xmlfile)
    
class XmlWriter(CuemsXml):

    def __init__(self,schema=None,xmlfile=None):
      super().__init__(schema, xmlfile)


    def write(self, xml_data, ):
        self.schema_object.validate(xml_data)
        ET.ElementTree(xml_data).write(self.xmlfile)

    def write_from_dict(self, project_dict):
        project_object = CuemsParser(project_dict).parse()
        xml_data = XmlBuilder(project_object).build()
        self.write(xml_data)

    def write_from_object(self, project_object):
        xml_data = XmlBuilder(project_object).build()
        self.write(xml_data)


class XmlReader(CuemsXml):
    def __init__(self,schema=None,xmlfile=None):
      super().__init__(schema, xmlfile)

    def read(self):
        xml_dict = self.schema_object.to_dict(self.xmlfile, validation='strict',  strip_namespaces=True)
        return xml_dict

    def read_to_objects(self):
        xml_dict = self.read()
        return CuemsParser(xml_dict).parse()