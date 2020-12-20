from subprocess import Popen, PIPE, STDOUT, CalledProcessError
from jack import Client

# Calling audioplayer-cuems in a subprocess
video_outputs = []
try:
    p = Popen(['xrandr','--listactivemonitors'], stdout=PIPE, stderr=STDOUT)
    stdout_lines_iterator = iter(p.stdout.readline, b'')
    while p.poll() is None:
        for line in stdout_lines_iterator:
            decoded = line.decode('utf-8')
            video_outputs.append(decoded[1:decoded.find(':')])
except:
    xrander_output = None

del video_outputs[0]

print(video_outputs)

jc = Client('hw_discover')
audio_outputs = jc.get_ports(is_audio=True, is_physical=True, is_input=True)

print(audio_outputs)