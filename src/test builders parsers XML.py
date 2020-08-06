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



c = Cue(33, {'type': 'mtc', 'loop': 'False'})
c.outputs = {'id': 5, 'bla':'ble'}
c2 = Cue(None, {'type': 'floating', 'loop': 'False'})
c2.outputs = {'physiscal': 1, 'virtual': 3}
c3 = Cue(5, {'type': 'virtual', 'loop': 'False'})
c3.outputs = {'id': 3}
ac = AudioCue(45, {'type': 'virtual','loop': 'True'} )
ac.outputs = {'stereo': 1}
d_c = DmxCue(time=23, scene={0:{0:10, 1:50}, 1:{20:23, 21:255}, 2:{5:10, 6:23, 7:125, 8:200}})
d_c.outputs = {'universe0': 3}


custom_cue_list = CueList([c, c2])
custom_cue_list.append(ac)

custom_cue_list + [d_c, c3]
float_cue_list = CueList([d_c, c3])

float_cuelist = CueList([ac, c3 ])
script = CuemsScript(custom_cue_list, float_cue_list)
print('OBJECT:')
print(script)

xml_data = XmlBuilder(script).build()

writer = XmlWriter(schema = 'cues.xsd', xmlfile = 'cues.xml')
writer.write(xml_data)

reader = XmlReader(schema = 'cues.xsd', xmlfile = 'cues.xml')
xml_dict = reader.read()
print("-------++++++---------")
print('DICT from XML:')
print(xml_dict)
print("-------++++++---------")
store = CuemsParser(xml_dict).parse()
print("--------------------")
print('Re-build object from xml:')
print(store)
print("--------------------")

if str(script) == str(store):
    print('original object and rebuilt object are EQUAL :)')
else:
    print('original object and rebuilt object are NOT equal :(')

print("-----^^^^^^^^------")
print("*******************")
print('JSON:')
print(json.dumps(xml_dict))
print("*******************")
for o in store.timecode_cuelist:
    print(type(o))
    print(o)
    if isinstance(o, DmxCue):
        print('Dmx scene, universe0, channel0, value : {}'.format(o.scene.universe(0).channel(0)))
for o in store.floating_cuelist:
    print(type(o))
    print(o)
    if isinstance(o, DmxCue):
        print('Dmx scene universe0, channel0 value:{}'.format(o.scene.universe(0).channel(0)))

        

# %%
