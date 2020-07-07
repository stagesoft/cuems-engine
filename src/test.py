#%%
from Cue import Cue
from AudioCue import AudioCue
from DmxCue import DmxCue
from CueList import CueList
from CTimecode import CTimecode
from Settings import Settings

import json
import jsonpickle

jsonpickle.set_preferred_backend('json')
jsonpickle.set_encoder_options('json', sort_keys=False)

c = Cue(33, {'type': 'virtual', 'loop': False})
c2 = Cue(None, {'type': 'floating', 'loop': False})
c3 = Cue(5, {'type': 'virtual', 'loop': False})
ac = AudioCue(45, {'loop': False, 'channels': 2} )
d_c = DmxCue(time=23, dmxscene={0:{0:10, 1:50}})

print(c2)

cue_list = [c, c2, ac, d_c]

custom_cue_list = CueList([c, c2])
print(custom_cue_list.times())
custom_cue_list.append(ac)

custom_cue_list + [d_c, c3]
custom_cue_list.extend([d_c, c3])
print(custom_cue_list)
print(custom_cue_list.times())

frozen = jsonpickle.encode(custom_cue_list)
objs = jsonpickle.decode(frozen)
print(frozen)


# %%
