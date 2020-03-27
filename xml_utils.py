import xml.etree.ElementTree as ET
import datetime  as DT
#tree = ET.parse('settings.xml')
#root = tree.getroot()



a = ET.Element('a')
a.tag = "Settings"
a.attrib['date'] = str(DT.datetime.now())
a.text = "blu"
b = ET.SubElement(a, 'b')
b.tag = "inner"
b.text = "contenido"
ET.dump(a)
tree=ET.ElementTree(a)
tree.write('test.xml')
