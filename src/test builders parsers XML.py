#%%
from cuems.cues.Cue import Cue
from cuems.cues.AudioCue import AudioCue
from cuems.cues.DmxCue import DmxCue
from cuems.CuemsScript import CuemsScript
from cuems.cues.CueList import CueList
from cuems.CTimecode import CTimecode
from cuems.Settings import Settings
from cuems.xml.DictParser import CuemsParser
from cuems.XmlBuilder import XmlBuilder
from cuems.XmlReaderWriter import XmlReader, XmlWriter

import xml.etree.ElementTree as ET



c = Cue(33, {'loop': False})
c2 = Cue(None, { 'loop': False})
c3 = Cue(5, {'loop': False})
ac = AudioCue(45, {'loop': True, 'media': 'file.ext', 'master_vol': 66} )

#ac.outputs = {'stereo': 1}
#d_c = DmxCue(time=23, scene={0:{0:10, 1:50}, 1:{20:23, 21:255}, 2:{5:10, 6:23, 7:125, 8:200}}, init_dict={'loop' : True})
#d_c.outputs = {'universe0': 3}
g = Cue(33, {'loop': False})

#custom_cue_list = CueList([c, c2])
custom_cue_list = CueList( c )
custom_cue_list.append(c2)
custom_cue_list.append(ac)
#custom_cue_list.append(d_c)


script = CuemsScript(cuelist=custom_cue_list)
script.name = "Test Script"
print('OBJECT:')
print(script)

xml_data = XmlBuilder(script, {'cms':'http://stagelab.net/cuems'}, '/etc/cuems/script.xsd').build()


writer = XmlWriter(schema = '/home/ion/src/cuems/python/cuems-engine/src/cuems/cues.xsd', xmlfile = '/home/ion/src/cuems/python/cuems-engine/src/cuems/cues.xml')

writer.write(xml_data)

reader = XmlReader(schema = '/home/ion/src/cuems/python/cuems-engine/src/cuems/cues.xsd', xmlfile = '/home/ion/src/cuems/python/cuems-engine/src/cuems/cues.xml')
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



print('xxxxxxxxxxxxxxxxxxxx')
for o in store.cuelist.contents:
    print(type(o))
    print(o)
    if isinstance(o, DmxCue):
        print('Dmx scene, universe0, channel0, value : {}'.format(o.scene.universe(0).channel(0)))


# %%
