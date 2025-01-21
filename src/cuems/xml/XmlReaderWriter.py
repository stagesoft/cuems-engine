# DEV: Move to cuems-utils
""" For the moment it works with pip3 install xmlschema==1.2.2
 """

import os

from ..log import logger
from .CMLCuemsConverter import CMLCuemsConverter
from .DictParser import CuemsParser
from .XmlBuilder import XmlBuilder

class CuemsXml():
    def __init__(self, schema, xmlfile=None, namespace={'cms':'http://stagelab.net/cuems'}, xml_root_tag='CuemsProject'):
        self.converter = CMLCuemsConverter
        self.schema_object = None
        self._xmlfile = None
        self._schema = None
        self.schema = schema
        self.xmlfile = xmlfile
        self.xmldata = None
        self.namespace = namespace
        self.xml_root_tag = xml_root_tag
        
    
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

    def write(self, xml_data, ):
        self.schema_object.validate(xml_data)
        xml_data.write(self.xmlfile, encoding="utf-8", xml_declaration=True)

    def write_from_dict(self, project_dict):
        project_object = CuemsParser(project_dict).parse()
        xml_data = XmlBuilder(project_object, namespace=self.namespace, xsd_path=self.schema, xml_root_tag=self.xml_root_tag).build()
        self.write(xml_data)

    def write_from_object(self, project_object):
        xml_data = XmlBuilder(project_object, namespace=self.namespace, xsd_path=self.schema, xml_root_tag=self.xml_root_tag).build()
        self.write(xml_data)


class XmlReader(CuemsXml):
 

    def read(self):
        xml_dict = self.schema_object.to_dict(self.xmlfile, validation='strict',  strip_namespaces=False)
        # remove namespace info from xml 
        try:
            del xml_dict['xmlns:cms']
            del xml_dict['xmlns:xsi']
            del xml_dict['xsi:schemaLocation']
        except KeyError:
            logger.warning('Error triying to remove namespace info on read')

        return xml_dict

    def read_to_objects(self):
        xml_dict = self.read()
        return CuemsParser(xml_dict).parse()
