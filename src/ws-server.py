
from cuems.log import logger
from cuems.cuems_editor.CuemsWsServer import CuemsWsServer

from multiprocessing import Queue
import time
import uuid
import os

engine_queue = Queue()
editor_queue = Queue()

settings_dict = {}
settings_dict['session_uuid'] = str(uuid.uuid1())
settings_dict['library_path'] = '/opt/cuems_library'
settings_dict['tmp_upload_path'] = '/tmp/cuemsuploads'
settings_dict['database_name'] = 'project-manager.db'


try:
    if not os.path.exists(settings_dict['tmp_upload_path']):
        os.mkdir(settings_dict['tmp_upload_path'])
        logger.info('creating tmp upload folder {}'.format(settings_dict['tmp_upload_path']))
except Exception as e:
    print("error: {} {}".format(type(e), e))

def f(text):
    editor_queue.put(text)


server = CuemsWsServer(engine_queue, editor_queue, settings_dict)
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
time.sleep(1)
f('cue 5 5%')
time.sleep(2)
f('cue 6 60%')
time.sleep(2)
f('cue 7 5%')
time.sleep(1)
f('cue 8 60%')
time.sleep(1)
f('cue 9 5%')
time.sleep(2)
f('cue 10 60%')
time.sleep(2)
f('cue 11 5%')
time.sleep(2)
f('cue 12 60%')
time.sleep(2)
f('cue 13 5%')
time.sleep(2)
f('cue 14 60%')
f('cue 15 5%')


time.sleep(20)
f('cue 2 80%')

#server.stop()
