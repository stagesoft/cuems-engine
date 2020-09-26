############################################################################
# A sample program to create a single-track MIDI file, add a note,
# and write to disk.
############################################################################

#Import the library
from midiutil.MidiFile import MIDIFile

# Create the MIDIFile Object
MyMIDI = MIDIFile(1)

# Add track name and tempo. The first argument to addTrackName and
# addTempo is the time to write the event.
track = 0
time = 0
MyMIDI.addTrackName(track,time,"Sample Track")
MyMIDI.addTempo(track,time, 120)

# Add a note. addNote expects the following information:
channel = range(1,16)
controller_number = range(0,127)
parameter = 50

# Now add the note.


for cc  in (controller_number):
    MyMIDI.addControllerEvent(track, 0, 0, cc, parameter)

for cc  in (controller_number):
    MyMIDI.addControllerEvent(track, 1, 0, cc, parameter)

parameter = 0
for cc  in (controller_number):
    MyMIDI.addControllerEvent(track, 0, 0.5, cc, parameter)

time = 1
for cc  in range(1,128):
    MyMIDI.addControllerEvent(track, 0, time, 0, cc)
    time = time + 0.01
time = 1
for cc  in range(1,128):
    MyMIDI.addControllerEvent(track, 0, time, 1, cc)
    time = time + 0.1
time = 2

for ch in range(2,40):
    for cc  in range(1,128):
        MyMIDI.addControllerEvent(track, 0, time, ch, cc)
        time = time + 0.06
    time = 2
time = 2
for ch in range(41,128):
    for cc  in range(1,128):
        MyMIDI.addControllerEvent(track, 0, time, ch, cc)
        time = time + 0.3
    time = 2
# And write it to disk.
binfile = open("output.mid", 'wb')
MyMIDI.writeFile(binfile)
binfile.close()