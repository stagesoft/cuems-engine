#%%
from Cue import Cue
from AudioCue import AudioCue
from DmxCue import DmxCue
from CuemsScript import CuemsScript
from CueList import CueList
from CTimecode import CTimecode
from Settings import Settings
from DictParser import CuemsParser
from XmlBuilder import XmlBuilder
from XmlReaderWriter import XmlReader, XmlWriter

import json
import xml.etree.ElementTree as ET



c = Cue(33, {'type': 'mtc', 'loop': False})
c.outputs = 5
c2 = Cue(None, {'type': 'floating', 'loop': False})
c2.outputs = {'physiscal': 1, 'virtual': 3}
c3 = Cue(5, {'type': 'virtual', 'loop': False})
c3.outputs = 5
ac = AudioCue(45, {'type': 'virtual','loop': False} )
ac.outputs = {'stereo': 1}
d_c = DmxCue(time=23, scene={0:{0:10, 1:50}, 1:{20:23, 21:255}, 2:{5:10, 6:23, 7:125, 8:200}})
d_c.outputs = 4


custom_cue_list = CueList([c, c2])
custom_cue_list.append(ac)

custom_cue_list + [d_c, c3]
float_cue_list = CueList([d_c, c3])

float_cuelist = CueList([ac, c3 ])
script = CuemsScript(custom_cue_list, float_cue_list)
print(script)
print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
xml_data = XmlBuilder(script).build()
print(xml_data)
print('%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%')
writer = XmlWriter(schema = 'cues.xsd', xmlfile = 'cues.xml')
writer.write(xml_data)

reader = XmlReader(schema = 'cues.xsd', xmlfile = 'cues.xml')
xml_dict = reader.read()
print("-------++++++---------")
print(xml_dict)
print("-------++++++---------")
store = CuemsParser(xml_dict).parse()
print("--------------------")
print(store)
print("--------------------")
print("*******************")
print(json.dumps(xml_dict))
print("*******************")
for o in store:
    print(type(o))
    print(o)
    if isinstance(o, DmxCue):
        print(o.scene.universe(0).channel(0))

# %%


