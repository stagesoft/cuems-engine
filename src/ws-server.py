
from cuems.log import logger 
from cuems.cuems_editor.CuemsWsServer import CuemsWsServer

from multiprocessing import Queue
import time

q = Queue()

def f(text):
    q.put(text)

server = CuemsWsServer(q)
logger.info('start server')
server.start(9092)

f('playing')

time.sleep(5)
f('cue 2 50%')
time.sleep(1)
f('cue 2 55%')

time.sleep(1)
f('cue 2 60%')
f('cue 3 5%')
f('cue 4 60%')
f('cue 5 5%')
f('cue 6 60%')
f('cue 7 5%')
f('cue 8 60%')
f('cue 9 5%')
f('cue 10 60%')
f('cue 11 5%')
f('cue 12 60%')
f('cue 13 5%')
f('cue 14 60%')
f('cue 15 5%')


time.sleep(20)
f('cue 2 80%')

#server.stop()
