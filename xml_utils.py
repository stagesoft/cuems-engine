import xml.etree.ElementTree as ET
import datetime  as DT
import config
#tree = ET.parse('settings.xml')
#root = tree.getroot()

def write(settings_dict):
    a = ET.Element('a')
    a.tag = "Settings"
    a.attrib['date'] = str(DT.datetime.now())
    


    for node, node_id_dict in settings_dict.items():

        for node_id, values_dict in node_id_dict.items():

            b= ET.SubElement(a, node, id = node_id)

            for key, value in values_dict.items():
                c= ET.SubElement(b, key)
                c.text = str(value)

    ET.dump(a)
    tree=ET.ElementTree(a)
    tree.write('write_test.xml')

def read():
    settings = {}
    tree = ET.parse('test.xml')
    root = tree.getroot()
    for child in root:
        if not child.tag in settings:
            settings.update({child.tag : {} })
        
        settings[child.tag][child.attrib['id']] = {}
        for child_ in child:
            settings[child.tag][child.attrib['id']].update({child_.tag : child_.text})

    print(settings)
    return settings

write(read())
