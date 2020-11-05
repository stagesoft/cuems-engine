""" For the moment it works with pip3 install xmlschema==1.1.2
 """

import xml.etree.ElementTree as ET
import xmlschema
import datetime  as DT
import os
from .log import logger

from .CTimecode import CTimecode

from .CMLCuemsConverter import CMLCuemsConverter

class Settings(dict):
    def __init__(self, schema = None, xmlfile = None, *arg, **kw):
      super().__init__(*arg, **kw)
      self.loaded = False
      self.schema = schema
      self.xmlfile = xmlfile
      self.xmldata = None
      if self.schema is not None and self.xmlfile is not None:
          self.read()
    
    def __backup(self):
        if os.path.isfile(self.xmlfile):
            logger.info("File exist")
            try:
                os.rename(self.xmlfile, "{}.back".format(self.xmlfile))
            except OSError:
                logger.error("Cannot create settings backup")
        else:
            logger.error("Settings file not found")
    
    @property
    def schema(self):
        return self._schema
        

    @schema.setter
    def schema(self, path):
        if os.path.isfile(path):
            self._schema = path
        else:
            raise FileNotFoundError("Schema file not found")


    @property
    def xmlfile(self):
        return self._xmlfile

    @xmlfile.setter
    def xmlfile(self, path):
        #if os.path.isfile(path): #TODO: clean this and backup
        self._xmlfile = path
        #else:
        #    raise FileNotFoundError("xml file not found")



    def write(self):

       # self.__backup()
        ET.ElementTree(self.xmldata).write(self.xmlfile)

    def validate(self):
        schema_file = open(self.schema)
        schema = xmlschema.XMLSchema11(schema_file, base_url='')
        xml_file = open(self.xmlfile)
        return schema.validate(xml_file)

    def read(self):
        try:
            schema_file = open(self.schema)
        except FileNotFoundError:
            logger.error(f'{self.schema} XSD file not found')

        schema = xmlschema.XMLSchema11(schema_file, base_url='', converter=CMLCuemsConverter)
        # schema = xmlschema.XMLSchema(schema_file, base_url='')

        try:
            xml_file = open(self.xmlfile)
        except FileNotFoundError:
            logger.error(f'{self.xmlfile} XML file not found')

        xml_dict = schema.to_dict(xml_file, dict_class=dict, list_class=list, validation='strict',  strip_namespaces=True, attr_prefix='')

        super().__init__(xml_dict)
        self.loaded = True
        return self

    def data2xml(self, obj):
        xml_tree = ET.Element(type(obj).__name__)
        self.xmldata = self.buildxml(xml_tree, obj)

    def buildxml(self, xml_tree, d): #TODO: clean variable names, simplify¿
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(k, str):
                    s = ET.SubElement(xml_tree, k)
                    
                elif isinstance(k, (dict)):
                    s = ET.SubElement(xml_tree, type(k).__name__)
                    s.text = k
                elif isinstance(k, (int, float)):
                    s = ET.SubElement(xml_tree, type(v).__name__, id=str(k))
                    if not isinstance(v, dict):
                        s.text =str(v)
                else:
                    s = ET.SubElement(xml_tree, type(k).__name__)
                
                if isinstance(v, (type(None), CTimecode, dict, list, tuple, int, float, str)): #TODO: filter without using explicit classes (like CTimecode)
                    self.buildxml(s, v)
        elif isinstance(d, tuple) or isinstance(d, list):
            for v in d:
                s = ET.SubElement(xml_tree, type(v).__name__)
                self.buildxml(s, v)
        elif isinstance(d, str):
            xml_tree.text = d
        elif isinstance(d, (float, int)):
      #  elif type(d) is int:
            xml_tree.text = str(d)
        else:
            s = ET.SubElement(xml_tree, type(d).__name__)
            self.buildxml(s, str(d))
        return xml_tree
