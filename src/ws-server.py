from cuems.log import logger
from cuems.cuems_editor.CuemsWsServer import CuemsWsServer

from multiprocessing import Queue
import time
import uuid
import os

q = Queue()

settings_dict = {}
settings_dict['session_uuid'] = str(uuid.uuid1())
settings_dict['library_path'] = '/home/stagelab/cuems_library'
settings_dict['tmp_upload_path'] = '/tmp/cuemsuploads'
settings_dict['database_name'] = 'project-manager.db'


try:
    if not os.path.exists(settings_dict['tmp_upload_path']):
        os.mkdir(settings_dict['tmp_upload_path'])
        logger.info('creating tmp upload folder {}'.format(settings_dict['tmp_upload_path']))
except Exception as e:
    print("error: {} {}".format(type(e), e))



server = CuemsWsServer(q, settings_dict)
logger.info('start server')
server.start(9092)
