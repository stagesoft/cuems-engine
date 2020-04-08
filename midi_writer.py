from midiutil.MidiFile import MIDIFile
from numpy import interp
from collections import defaultdict
import random

import pprint


class DmxToMidi():

    def __init__(self):
        self.file = None
        self.track = None
        self.time = None
        self._dmx_channel = dict()
        self._channel = [0] * 16
        self._controller = [0] * 128
        self.events = dict()
        self._midifile = MIDIFile(numTracks=1, removeDuplicates=False,  deinterleave=True)
        track = 0
        time = 0
        self._midifile.addTrackName(track, time, "Sample Track")
        self._midifile.addTempo(track, time, 480)

    def channel(self, num):
        return self._dmx_channel[num]

    def channel_set(self, num, value):
        if value > 255:
            value = 255
        self._dmx_channel[num] = value

    def channel_setall(self, value):
        for channel in range(512):
            self._dmx_channel[channel] = value

    def add_event(self, time, fadetime=0):
        if time in self.events:
            merge_dmx_channel = {**self.events[time]["dmx"], **self._dmx_channel}
            self.events[time] = {'fadetime': fadetime,
            'dmx': dict(merge_dmx_channel)}
        else:
            self.events[time] = {'fadetime': fadetime,
                'dmx': dict(self._dmx_channel)}
        self._dmx_channel.clear()

    def print_events(self, time=None):
        print(self.events)

    def dmx_to_midi(self, dmx_list):
        
        #dmx_midi_matrix = [[0 for i in range(128)] for j in range(16)]
        dmx_midi_matrix = defaultdict(dict)
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

d = DmxToMidi()

d.channel_setall(0)
d.add_event(0)

d.channel_set(1, 255)
d.add_event(1)
d.channel_set(2, 255)
d.add_event(2)
d.channel_set(3, 255)
d.add_event(2)


time = 3.9

for x in range(256):
    for y in range(100):
        d.channel_set(y,x)
    time = round(time +0.1, 2)
    d.add_event(time)
time = 3.9

for x in range(256):
    for y in range(101,200):
        d.channel_set(y,x)
    time = round(time +0.3, 2)
    d.add_event(time)
time = 3.9

for x in range(256):
    for y in range(201,300):
        d.channel_set(y,x)
    time = round(time +0.6, 2)
    d.add_event(time)

time = 3.9

for x in range(256,-1,-1):
    for y in range(301,400):
        d.channel_set(y,x)
    time = round(time +0.2, 2)
    d.add_event(time)

time = 3.9

for x in range(256,-1,-1):
    for y in range(401,512):
        d.channel_set(y,x)
    time = round(time +0.5, 2)
    d.add_event(time)




# d.print_events()
d.write()
