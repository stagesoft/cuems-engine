#import pyossia as ossia
import pyossia as ossia
import time
import threading

#from VideoPlayer import NodeVideoPlayers
#from AudioPlayer import NodeAudioPlayers
from .log import logger

class OssiaServer():
    def __init__(self, node_config, osc_bridge_config):
        self.server_running = False
        self.engine_oscquery_nodes = dict()
        self.engine_osc_nodes = dict()
        self.audio_nodes = dict()
        self.video_nodes = dict()

        self.oscquery_device = ossia.LocalDevice(f'node_{node_config["id"]:03}_oscquery')
        self.oscquery_device.create_oscquery_server(    node_config['oscquery_port'], 
                                                        node_config['oscquery_out_port'], 
                                                        False)
        logger.info(f'OscQuery device listening on port {node_config["oscquery_port"]}')

        self.oscquery_messageq = ossia.MessageQueue(self.oscquery_device)

        '''
        self.engine_osc_device = ossia.ossia_python.OSCDevice(  f'node_{node_config["id"]:03}',
                                                                node_config['osc_dest_host'], 
                                                                node_config['engine_osc_in_port'], 
                                                                node_config['engine_osc_out_port'] )
        '''

        self.init_engine_nodes(osc_bridge_config)
        self.init_audio_nodes()
        self.init_video_nodes()

    def start(self):
        self.server_running = True

        self.thread = threading.Thread(target=self.threaded_loop, name='OSCQueryLoop')
        self.thread.start()

    def stop(self):
        self.server_running = False
        self.thread.join()
        
    def threaded_loop(self):
        while self.server_running:
            oscq_message = self.oscquery_messageq.pop()
            while (oscq_message != None):
                parameter, value = oscq_message
                self.engine_oscquery_nodes[str(parameter.node)][1](value=value)
                '''
                try:                
                    self.engine_osc_nodes[str(parameter.node)][0].parameter.value = value
                except KeyError:
                    logger.info(f'OSC device has no {str(parameter.node)} node')
                except SystemError:
                    pass
                '''
                oscq_message = self.oscquery_messageq.pop()

    def init_engine_nodes(self, osc_bridge_config):
        '''
        node_dict = {   '/engine':ossia.ValueType.Impulse,
                        '/engine/go':ossia.ValueType.String,
                        '/engine/pause':ossia.ValueType.Impulse,
                        '/engine/stop':ossia.ValueType.Impulse,
                        '/engine/resetall':ossia.ValueType.Impulse,
                        '/engine/preload':ossia.ValueType.String,
                        '/engine/timecode':ossia.ValueType.Int
                    }
        '''

        for route, conf in osc_bridge_config.items():
            enode = self.oscquery_device.add_node(route)
            enode.create_parameter(conf[0])
            enode.parameter.access_mode = ossia.AccessMode.Bi
            enode.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
            self.oscquery_messageq.register(enode.parameter)
            
            self.engine_oscquery_nodes[route] = [enode, conf[1]]

            '''
            enodeOSC = self.engine_osc_device.add_node(route)
            enodeOSC.create_parameter(param)
            enodeOSC.parameter.access_mode = ossia.AccessMode.Bi
            enodeOSC.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
            self.engine_osc_nodes[route] = enodeOSC
            '''

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

    def test_method(self):
        pass
