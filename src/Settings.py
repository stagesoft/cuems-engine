import xml.etree.ElementTree as ET
import xmlschema
import datetime  as DT
import os
import json
from log import *


import sys

class CMLCuemsConverter(xmlschema.XMLSchemaConverter):
 
      
    def element_decode(self, data, xsd_element, xsd_type=None, level=0):
        xsd_type = xsd_type or xsd_element.type
        preserve_root = self.preserve_root
        if xsd_type.is_simple() or xsd_type.has_simple_content():
            if preserve_root:
                return self.dict([(self.map_qname(data.tag), data.text)])
            else:
                return data.text if data.text != '' else None
        else:
            result_dict = self.dict()
            list_types = list if self.list is list else (self.list, list)
            for name, value, xsd_child in self.map_content(data.content):
                if preserve_root:
                    try:
                        if len(value) == 1:
                            value = value[name]
                    except (TypeError, KeyError):
                        pass

                try:
                    result_dict[name].append(value)
                except KeyError:
                    if isinstance(value, list_types):
                        result_dict[name] = self.list([value])
                    else:
                        result_dict[name] = value
                except AttributeError:
                    result_dict[name] = self.list([result_dict[name], value])

            for k, v in result_dict.items():
                if isinstance(v, (self.list, list)) and len(v) == 1:
                    value = v.pop()
                    v.extend(value)

            if preserve_root:
                return self.dict([(self.map_qname(data.tag), result_dict)])
            else:
                return result_dict if result_dict else None


class Settings(dict):

    def __init__(self,schema=None,xmlfile=None,*arg,**kw):
      super().__init__(*arg, **kw)
      self.loaded = False
      self.schema = schema
      self.xmlfile = xmlfile
      self.xmldata = None
      
    
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
        #if os.path.isfile(path): #TODO: clean this and backup
        self._xmlfile = path
        #else:
        #    raise FileNotFoundError("xml file not found")



    def write(self):

       # self.__backup()
        ET.ElementTree(self.xmldata).write(self.xmlfile)

    def validate(self):
        schema_file = open(self.schema)
        schema = xmlschema.XMLSchema(schema_file, base_url='/home/ion/src/cuems/python/python-osc-ossia/')
        xml_file = open(self.xmlfile)
        return schema.validate(xml_file)

    def read(self):
        schema_file = open(self.schema)
        #schema = xmlschema.XMLSchema(schema_file, converter=xmlschema.JsonMLConverter)
        schema = xmlschema.XMLSchema(schema_file, base_url='/home/ion/src/cuems/python/python-osc-ossia/')

        xml_file = open(self.xmlfile)
        xml_dict = schema.to_dict(xml_file, dict_class=dict, list_class=list, validation='strict',  strip_namespaces=True)
        json_str=json.dumps(xml_dict)
        logging.debug(xml_dict)
        logging.debug(json_str)
        super().__init__(xml_dict)
       # super().__init__(schema.to_dict(xml_file, converter=CMLCuemsConverter, validation='strict'))
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
                    
                else:
                    s = ET.SubElement(xml_tree, type(k).__name__)
                
                # order only nested dictionaries, not the root one TODO: try to implement order in dmx classes so is not need here
                if isinstance(v, dict):
                    v = {k: v[k] for k in sorted(v)}

                self.buildxml(s, v)
        elif isinstance(d, tuple) or isinstance(d, list):
            for v in d:
                s = ET.SubElement(xml_tree, 'i')
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
