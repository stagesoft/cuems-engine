#import pyossia as ossia
import pyossia as ossia
import time
import threading

#from VideoPlayer import NodeVideoPlayers
#from AudioPlayer import NodeAudioPlayers
from .log import logger

class OssiaServer(threading.Thread):
    def __init__(self, node_config, queue):
        super().__init__(name='ossia')
        self.server_running = True

        self.conf_queue = queue
        # Main thread queue attendant loop
        self.conf_queue_loop = threading.Thread(target=self.conf_queue_consumer, name='mtqueueconsumer')
        self.conf_queue_loop.start()

        # OSC nodes dicts
        self.osc_registered_nodes = dict()

        # Ossia Device and OSCQuery server creation
        self.oscquery_device = ossia.LocalDevice(f'node_{node_config["id"]:03}_oscquery')
        self.oscquery_device.create_oscquery_server(    node_config['oscquery_port'], 
                                                        node_config['oscquery_out_port'], 
                                                        False)
        logger.info(f'OscQuery device listening on port {node_config["oscquery_port"]}')

        # OSC messages queue
        self.oscquery_messageq = ossia.MessageQueue(self.oscquery_device)

    def start(self):
        self.server_running = True

        # Message loop
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
                if self.osc_registered_nodes[str(parameter.node)][1] is not None:
                    self.osc_registered_nodes[str(parameter.node)][1](value=value)
                '''
                try:                
                    self.engine_osc_nodes[str(parameter.node)][0].parameter.value = value
                except KeyError:
                    logger.info(f'OSC device has no {str(parameter.node)} node')
                except SystemError:
                    pass
                '''

                oscq_message = self.oscquery_messageq.pop()
            
            time.sleep(0.001)

    def conf_queue_consumer(self):
        while self.server_running:
            item = self.conf_queue.get()
            if item[0] == 'add':
                self.add_nodes(item[1])
            elif item[0] == 'remove':
                self.add_nodes(item[1])
            self.conf_queue.task_done()
            time.sleep(0.004)

    def add_nodes(self, nodes_dict):
        for route, conf in nodes_dict.items():
            temp_node = self.oscquery_device.add_node(route)
            temp_node.create_parameter(conf[0])
            temp_node.parameter.access_mode = ossia.AccessMode.Bi
            temp_node.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
            self.oscquery_messageq.register(temp_node.parameter)
            
            self.osc_registered_nodes[route] = [temp_node, conf[1]]
        logger.info(f'OSC Nodes registered: {nodes_dict}')

    def remove_nodes(self, nodes_dict):
        for route, conf in nodes_dict.items():
            try:
                self.osc_registered_nodes.pop(route)
            except:
                pass