import xml.etree.ElementTree as ET
import datetime  as DT
import os
from log import *



class Settings(dict):

    def __init__(self,filename, *arg,**kw):
      super(Settings, self).__init__(*arg, **kw)
      self.loaded = False
      self.filename = filename

    def __backup(self):
        if os.path.isfile(self.filename):
            logging.debug("File exist")
            try:
                os.rename(self.filename, "{}.back".format(self.filename))
            except OSError:
                logging.debug("cannot create settings backup")
        else:
            logging.debug("settings file not found")


    def is_loaded(self):
        return self.loaded


    def write(self):
        a = ET.Element('a')
        a.tag = "Settings"
        a.attrib['date'] = str(DT.datetime.now())
        


        for node, node_id_dict in self.items():

            for node_id, values_dict in node_id_dict.items():

                b= ET.SubElement(a, node, id = node_id)

                for key, value in values_dict.items():
                    c= ET.SubElement(b, key)
                    c.text = str(value)

        tree=ET.ElementTree(a)
        self.__backup()
        tree.write(self.filename)

    def read(self):
        tree = ET.parse(self.filename)
        root = tree.getroot()
        for child in root:
            if not child.tag in self:
                self.update({child.tag : {} })
            
            self[child.tag][child.attrib['id']] = {}
            for child_ in child:
                self[child.tag][child.attrib['id']].update({child_.tag : child_.text})
        self.loaded = True
        return self