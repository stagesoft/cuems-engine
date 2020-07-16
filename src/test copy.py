#%%
from Cue import Cue
from AudioCue import AudioCue
from DmxCue import DmxCue
from CueList import CueList
from CTimecode import CTimecode
from Settings import Settings
from CueParser import CueListParser

import json
import jsonpickle

jsonpickle.set_preferred_backend('json')
jsonpickle.set_encoder_options('json', sort_keys=False)

c = Cue(33, {'type': 'virtual', 'loop': False})
c2 = Cue(None, {'type': 'floating', 'loop': False})
c3 = Cue(5, {'type': 'virtual', 'loop': False})
ac = AudioCue(45, {'type': 'virtual','loop': False} )
d_c = DmxCue(time=23, scene={0:{0:10, 1:50}, 1:{20:23, 21:255}, 2:{5:10, 6:23, 7:125, 8:200}})


cue_list = [c, c2, ac, d_c]

custom_cue_list = CueList([c, c2])
custom_cue_list.append(ac)

custom_cue_list + [d_c, c3]
custom_cue_list.extend([d_c, c3])
print(c)
print(custom_cue_list)

blu= Settings(schema="cues.xsd", xmlfile="cues.xml")
blu.data2xml(custom_cue_list)

blu.write()
readed_dict=blu.read()
print(readed_dict)
store = CueListParser(readed_dict).parse()
print("--------------------")
print(store)
print("--------------------")
for o in store:
    print(type(o))
    print(o)
    if isinstance(o, DmxCue):
        print(o.scene.universe(0).channel(0))
# %%

