from midiutil.MidiFile import MIDIFile
from numpy import interp
from CTimecode import CTimecode

from DmxCue import *

import random

import pprint


class DmxSceneList():

    def __init__(self):
        self.file = None
        self.track = None
        self.time = None

        self._controller = [0] * 128
        self.events = dict()
        self._midifile = MIDIFile(numTracks=1, removeDuplicates=False,  deinterleave=True)
        track = 0
        time = 0
        self._midifile.addTrackName(track, time, "Sample Track")
        self._midifile.addTempo(track, time, 480)


    def add_event(self, time, dmxscene, in_time, out_time):
        if time in self.events:
            merge_dmx_scene = {**self.events[time]["dmx_scene"], **dmxscene}
            self.events[time] = {'in_time': in_time, 'out_time' : out_time,
            'dmx_scene': dict(merge_dmx_scene)}
        else:
            self.events[time] = {'in_time': in_time, 'out_time' : out_time,
                'dmx_scene': dict(dmxscene)}

    def print_events(self, time=None):
        print(self.events)

    def dmx_to_midi(self, dmx_list):
        
        #dmx_midi_matrix = [[0 for i in range(128)] for j in range(16)]
        dmx_midi_matrix = dict()
        for channel, value in dmx_list.items():

            cc_value = int(interp(value, [0, 255], [0, 127]))
            if channel <= 127:
                dmx_midi_matrix[0][channel] = cc_value
            elif 127 < channel <= 255:
                dmx_midi_matrix[1][channel - 128] = cc_value
            elif 255 < channel <= 383:
                dmx_midi_matrix[2][channel - 256] = cc_value
            elif 383 < channel <= 511:
                dmx_midi_matrix[3][channel - 384] = cc_value
        return dmx_midi_matrix

    def write(self):
        for time, data in sorted(self.events.items()):
            dmx_midi_matrix = self.dmx_to_midi(data["dmx"])
            for chan_num, channel in dmx_midi_matrix.items():
                if chan_num > 0:
                    time = round(time + 0.01, 3)
                for cc, cc_value in channel.items():
                    self._midifile.addControllerEvent(0, chan_num, time, cc, cc_value)
                    print("time: {}, channel: {}, cc_number: {}, value: {}".format(time, chan_num, cc, cc_value))
                
                 
        # And write it to disk.
        binfile = open("class.mid", 'wb')
        self._midifile.writeFile(binfile)
        binfile.close()




#scene = DmxScene({0:{0:0, 4:4, 1:230}, 3:DmxUniverse().setall(30)})
scene = DmxScene({0:{0:0, 4:4, 1:230}, 3:DmxUniverse().set_channel(2,30).set_channel(0, 10)})


scene2 = DmxScene({1:DmxUniverse({0:20, 1:20})})
#universe_full2 = DmxUniverse().setall(255)
#scene2.set_universe(universe_full2, 2)


universe = DmxUniverse({0:10, 1:15, 2:15})

universe[3]=255


scene.set_universe(universe, 1)

#universe_full = DmxUniverse().setall(255)

#scene.set_universe(universe_full, 2)
#scene.merge_universe(scene[0], 1)


#scene_list = DmxSceneList()
#scene_list.add_event(CTimecode('00:00:01:00'), scene, 2, 3)

#scene_list.add_event(CTimecode(frames=51), scene2, 12, 13)
#scene_list.print_events()

a = CTimecode('00:00:01:00')
b = CTimecode(frames=26)
c = CTimecode('00:00:01:00', framerate=30)

assert a == a
assert a == b
assert a != c

cue = Cue(60)
print(cue)
cue2 = Cue('00:01:00:00')
print(cue2)
print(cue2['time'])

print(cue['time'])
assert cue['time'] == cue2['time']

dc = DmxCue(CTimecode('00:00:06:00'), scene, in_time=2, out_time=3)
print(dc)

scene[0].set_channel(0, 255)
print(universe)
scene[0].update({0:99, 1:99, 2:99, 3:99, 4:99})


assert dc.time == dc['time']

from Settings import Settings

s = Settings('settings.xsd', 'dmx.xml', dc)
s.data2xml(dc)
s.write()

sr = Settings('dmx.xsd', 'dmx.xml')
sr.read()
print(sr)

print("------------")

#print(sr['dmx_scene']['DmxUniverse'][0]['DmxChannel'][0]['$'])
DmxUniverse()



rc = DmxCue(sr['time']['CTimecode'], DmxScene({0: {0: 0, 4: 4, 1: 230}, 3: {2: 30, 0: 10}, 1: {0: 10, 1: 15, 2: 15, 3: 255}}), in_time=sr['in_time'], out_time=sr['out_time'])
print(rc)