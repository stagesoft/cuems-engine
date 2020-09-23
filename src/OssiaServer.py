#import pyossia as ossia
import pyossia as ossia
import time
import threading
import re

from VideoPlayer import NodeVideoPlayers
from AudioPlayer import NodeAudioPlayers
from log import logger

class OssiaServer():
    server_running = False
    pattern = re.compile(r'/(\w*)(\d)/(\w*)(\d)/(\w*)')
    engine_nodes = dict()
    audio_nodes = dict()
    video_nodes = dict()

    def __init__(self, node_config):
        self.local_device = ossia.LocalDevice('Node {}'.format(node_config['id']))
        self.local_device.create_oscquery_server(node_config['osc_out_port'], node_config['osc_in_port'], False)

        self.local_device.create_osc_server('localhost', 7800, 7801, True)

        logger.info('OscQuery device listening on port {}'.format(node_config['osc_in_port']))

        self.local_messageq = ossia.GlobalMessageQueue(self.local_device)

        self.add_engine_nodes()
        self.add_audio_nodes()
        self.add_video_nodes()

    def start(self):
        self.server_running = True

        self.thread = threading.Thread(target=self.threaded_loop, name='Ossia OSCQ Loop')
        self.thread.start()

    def stop(self):
        self.server_running = False
        self.thread.join()
        

    def threaded_loop(self):
        while self.server_running:
            message = self.local_messageq.pop()

            if (message != None):
                parameter, value = message
                if str(parameter.node) == '/engine/running':
                    logger.info('!!!')
                    if value == True:
                        logger.info('STARTING engine through OSCQuery')
                    else:
                        logger.info('STOPPING engine through OSCQuery')
                elif str(parameter.node) == '/engine/starting':
                    if value:
                        logger.info('STARTING engine through OSCQuery')
                elif str(parameter.node) == '/engine/paused':
                    if self.engine_nodes['/engine/running'].parameter.value:
                        if value:
                            if self.engine_nodes['/engine/running'].parameter.value:
                                self.engine_nodes['/engine/running'].parameter.value = False
                                logger.info('PAUSING engine through OSCQuery')                        
                        else:
                            if not self.engine_nodes['/engine/running'].parameter.value:
                                logger.info('UNPAUSING engine through OSCQuery')
                                self.engine_nodes['/engine/running'].parameter.value = True
                                
            time.sleep(0.01)

    def add_engine_nodes(self):
        node_list = ['/engine/running', '/engine/starting', '/engine/paused']

        for each in node_list:
            enode = self.local_device.add_node(each)
            enode.create_parameter(ossia.ValueType.Bool)
            enode.parameter.access_mode = ossia.AccessMode.Bi
            enode.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
            enode.parameter.value = False
            self.engine_nodes[each] = enode

    def add_audio_nodes(self):
        pass

    def add_video_nodes(self):
        pass
