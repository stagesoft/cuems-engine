
from cuemsengine.log import logger
from cuemsengine.cuems_editor.CuemsWsServer import CuemsWsServer

from multiprocessing import Queue
import time
import uuid
import os



settings_dict = {}
settings_dict['session_uuid'] = str(uuid.uuid1())
settings_dict['library_path'] = '/opt/cuems_library'
settings_dict['tmp_path'] = '/tmp/cuems'
settings_dict['database_name'] = 'project-manager.db'


mappings_dict = {'number_of_nodes': 1, 'default_audio_input': '0367f391-ebf4-48b2-9f26-000000000001_system:capture_1', 'default_audio_output': '0367f391-ebf4-48b2-9f26-000000000001_system:playback_1', 'default_video_input': None, 'default_video_output': '0367f391-ebf4-48b2-9f26-000000000001_0', 'default_dmx_input': None, 'default_dmx_output': None, 'nodes': [{'uuid': '0367f391-ebf4-48b2-9f26-000000000001', 'mac': '2cf05d21cca3', 'audio': {'outputs': [{'name': 'system:playback_1', 'mappings': [{'mapped_to': 'system:playback_1'}]}, {'name': 'system:playback_2', 'mappings': [{'mapped_to': 'system:playback_2'}]}], 'inputs': [{'name': 'system:capture_1', 'mappings': [{'mapped_to': 'system:capture_1'}]}, {'name': 'system:capture_2', 'mappings': [{'mapped_to': 'system:capture_2'}]}]}, 'video': {'outputs': [{'name': '0', 'mappings': [{'mapped_to': '0'}]}]}, 'dmx': None}]}

try:
    if not os.path.exists(settings_dict['tmp_path']):
        os.mkdir(settings_dict['tmp_path'])
        logger.info('creating tmp upload folder {}'.format(settings_dict['tmp_path']))
except Exception as e:
    print("error: {} {}".format(type(e), e))




server = CuemsWsServer(settings_dict, mappings_dict)
logger.info('start server')
time.sleep(5)
server.start(9092)


#server.stop()
