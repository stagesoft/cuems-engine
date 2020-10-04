#%%
from cuems import Cue
from cuems import AudioCue
from cuems import DmxCue
from cuems import CuemsScript
from cuems import CueList
from cuems import CTimecode
from cuems import Settings
from cuems import CuemsParser
from cuems.XmlBuilder import XmlBuilder
from cuems import XmlReader, XmlWriter



c = Cue(33, {'type': 'mtc', 'loop': 'False', 'media': "file.ext"})
c.outputs = {'id': 5, 'bla':'ble'}
c2 = Cue(None, {'type': 'floating', 'loop': 'False'})
c2.outputs = {'physiscal': 1, 'virtual': 3}
c3 = Cue(5, {'type': 'virtual', 'loop': 'False'})
c3.outputs = {'id': 3}
ac = AudioCue(45, {'type': 'virtual','loop': 'True'} )
ac.outputs = {'stereo': 1}
d_c = DmxCue(time=23, scene={0:{0:10, 1:50}, 1:{20:23, 21:255}, 2:{5:10, 6:23, 7:125, 8:200}})
d_c.outputs = {'universe0': 3}
g = Cue(33, {'type': 'mtc', 'loop': 'False'})

custom_cue_list = CueList([c, c2])
custom_cue_list.append(ac)

custom_cue_list + [d_c, c3, g]
float_cue_list = CueList([d_c, c3])

float_cuelist = CueList([ac, c3 ])
script = CuemsScript(timecode_cuelist=custom_cue_list, floating_cuelist=float_cue_list)
script.name = "Test Script"
script['date']= "the date of todayclea"
print('OBJECT:')
print(script)

xml_data = XmlBuilder(script).build()

writer = XmlWriter(schema = '/home/ion/src/cuems/python/osc-control/src/cuems/cues.xsd', xmlfile = '/home/ion/src/cuems/python/osc-control/src/cuems/cues.xml')

writer.write(xml_data)

reader = XmlReader(schema = '/home/ion/src/cuems/python/osc-control/src/cuems/cues.xsd', xmlfile = '/home/ion/src/cuems/python/osc-control/src/cuems/cues.xml')
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
