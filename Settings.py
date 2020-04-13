import xml.etree.ElementTree as ET
import xmlschema
import datetime  as DT
import os
from log import *


import sys


class Settings(dict):

    def __init__(self,schema=None,xmlfile=None,*arg,**kw):
      super().__init__(*arg, **kw)
      self.loaded = False
      self._xmlfile = None
      self._schema = None
      self.schema = schema
      self.xmlfile = xmlfile
      
    
    def __backup(self):
        if os.path.isfile(self.xmlfile):
            logging.debug("File exist")
            try:
                os.rename(self.xmlfile, "{}.back".format(self.xmlfile))
            except OSError:
                logging.debug("cannot create settings backup")
        else:
            logging.debug("settings file not found")
    
    @property
    def schema(self):
        return self._schema
        

    @schema.setter
    def schema(self, path):
        if os.path.isfile(path):
            self._schema = path
        else:
            raise FileNotFoundError("schema file not found")


    @property
    def xmlfile(self):
        return self._xmlfile

    @xmlfile.setter
    def xmlfile(self, path):
        if os.path.isfile(path):
            self._xmlfile = path
        #else:
        #    raise FileNotFoundError("xml file not found")



    # def write(self):
    #     a = ET.Element('a')
    #     a.tag = "Settings"
    #     a.attrib['date'] = str(DT.datetime.now())
        


    #     for node, node_id_dict in self.items():

    #         for node_id, values_dict in node_id_dict.items():

    #             b= ET.SubElement(a, node, id = node_id)

    #             for key, value in values_dict.items():
    #                 c= ET.SubElement(b, key)
    #                 c.text = str(value)

    #     tree=ET.ElementTree(a)
    #     self.__backup()
    #     tree.write(self._xmlfile)

    def validate(self):
        schema_file = open(self.schema)
        schema = xmlschema.XMLSchema(schema_file, base_url='/home/ion/src/cuems/python/python-osc-ossia/')
        xml_file = open(self.xmlfile)
        return schema.validate(xml_file)

    def read(self):
        schema_file = open(self.schema)
        schema = xmlschema.XMLSchema(schema_file, base_url='/home/ion/src/cuems/python/python-osc-ossia/')
        xml_file = open(self.xmlfile)        
        super().__init__(schema.to_dict(xml_file, validation='strict'))
        self.loaded = True
        return self

    def data2xml(self, name='data'):
        r = ET.Element(name)
        return ET.tostring(self.buildxml(r, super()))

    def buildxml(self, r, d):
        if isinstance(d, dict):
            for k, v in d.iteritems():
                s = ET.SubElement(r, k)
                self.buildxml(s, v)
        elif isinstance(d, tuple) or isinstance(d, list):
            for v in d:
                s = ET.SubElement(r, 'i')
                self.buildxml(s, v)
        elif isinstance(d, str):
            r.text = d
        else:
            r.text = str(d)
        return r
