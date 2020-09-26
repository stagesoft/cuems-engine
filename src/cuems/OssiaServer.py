#import pyossia as ossia
import pyossia as ossia
import time
import threading

#from VideoPlayer import NodeVideoPlayers
#from AudioPlayer import NodeAudioPlayers
from log import logger

class OssiaServer():
    def __init__(self, node_config):
        self.server_running = False
        self.engine_oscquery_nodes = dict()
        self.engine_osc_nodes = dict()
        self.audio_nodes = dict()
        self.video_nodes = dict()

        self.oscquery_device = ossia.LocalDevice(f'node_{node_config["id"]:03}_oscquery')
        self.oscquery_device.create_oscquery_server(node_config['osc_in_port'], node_config['osc_out_port'], False)
        logger.info(f'\t\tOscQuery device listening on port {node_config["osc_in_port"]}')

        self.oscquery_messageq = ossia.MessageQueue(self.oscquery_device)

        self.engine_osc_device = ossia.ossia_python.OSCDevice(f'node_{node_config["id"]:03}', '127.0.0.1', 7800, 7801)

        self.init_engine_nodes()
        self.init_audio_nodes()
        self.init_video_nodes()

    def start(self):
        self.server_running = True

        self.thread = threading.Thread(target=self.threaded_loop, name='OssiaServer')
        self.thread.start()

    def stop(self):
        self.server_running = False
        self.thread.join()
        
    def threaded_loop(self):
        while self.server_running:
            oscq_message = self.oscquery_messageq.pop()
            while (oscq_message != None):
                parameter, value = oscq_message
                logger.info(f'OSCQuery received : {str(parameter.node)} {str(value)}')

                try:                
                    self.engine_osc_nodes[str(parameter.node)].parameter.value = value
                except KeyError:
                    logger.info(f'OSC device has no {str(parameter.node)} node')

                oscq_message = self.oscquery_messageq.pop()

            time.sleep(0.01)

    def init_engine_nodes(self):
        node_list = ['/engine/running', '/engine/starting', '/engine/paused']

        enode = self.oscquery_device.add_node('/engine')
        enode.create_parameter(ossia.ValueType.Impulse)
        enode.parameter.access_mode = ossia.AccessMode.Bi
        enode.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
        self.oscquery_messageq.register(enode.parameter)
        self.engine_oscquery_nodes['/engine'] = enode

        for each in node_list:
            enode = self.oscquery_device.add_node(each)
            enode.create_parameter(ossia.ValueType.Bool)
            enode.parameter.access_mode = ossia.AccessMode.Bi
            enode.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
            enode.parameter.default_value = False
            self.oscquery_messageq.register(enode.parameter)
            self.engine_oscquery_nodes[each] = enode

            enodeOSC = self.engine_osc_device.add_node(each)
            enodeOSC.create_parameter(ossia.ValueType.Bool)
            enodeOSC.parameter.access_mode = ossia.AccessMode.Bi
            enodeOSC.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
            enodeOSC.parameter.default_value = False
            self.engine_osc_nodes[each] = enodeOSC

    def add_engine_node(self, node):
        pass

    def remove_engine_node(self, node):
        pass

    def init_audio_nodes(self):
        pass

    def add_audio_node(self, node):
        pass

    def remove_audio_node(self, node):
        pass

    def init_video_nodes(self):
        pass

    def add_video_node(self, node):
        pass

    def remove_video_node(self, node):
        pass
