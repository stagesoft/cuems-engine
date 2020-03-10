from timecode import Timecode
from mido import Message




msg = Message('quarter_frame', note=60)










tc1 = Timecode('25', '00:00:00:00')
tc2 = Timecode('25', '00:00:00:10')
tc3 = tc1 + tc2
print(tc3)
print(tc3.frames)
print(tc3.frameratepip)
assert tc3.framerate == '25'
assert tc3.frames == 12
assert tc3 == '00:00:00:11'