""" For the moment it works with pip3 install xmlschema==1.1.2
 """

import xml.etree.ElementTree as ET
import xmlschema
import datetime  as DT
import os
import json
from log import *

from CTimecode import CTimecode

from CMLCuemsConverter import CMLCuemsConverter
class CuemsXml():
    def __init__(self,schema=None,xmlfile=None):
        self.converter = CMLCuemsConverter
        self.schema_object = None
        self._xmlfile = None
        self.schema = schema
        self.xmlfile = xmlfile
        self.xmldata = None
        
    
    @property
    def schema(self):
        return self._schema
        

    @schema.setter
    def schema(self, path):
        if path is not None:
            if os.path.isfile(path):
                self._schema = path
                schema_file = open(self.schema)
                self.schema_object = xmlschema.XMLSchema(schema_file, converter=self.converter)
            else:
                raise FileNotFoundError("schema file not found")


    @property
    def xmlfile(self):
        return self._xmlfile

    @xmlfile.setter
    def xmlfile(self, path):
        if os.path.isfile(path): #TODO: clean this and backup
            self._xmlfile = path
        else:
            logging.debug("xml file {} not found, creating new".format(self.xmlfile))
            self._xmlfile = path
            
    def validate(self):
        xml_file = open(self.xmlfile)
        return self.schema_object.validate(xml_file)
    
class XmlWriter(CuemsXml):

    def __init__(self,schema=None,xmlfile=None):
      super().__init__(schema, xmlfile)


    def write(self, xmldata):

       # self.__backup()
        ET.ElementTree(xmldata).write(self.xmlfile)

class XmlReader(CuemsXml):
    def __init__(self,schema=None,xmlfile=None):
      super().__init__(schema, xmlfile)

    def read(self):
        xml_file = open(self.xmlfile)
        xml_dict = self.schema_object.to_dict(xml_file, validation='strict',  strip_namespaces=True)
        return xml_dict
