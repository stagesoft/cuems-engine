#import pyossia as ossia
import pyossia as ossia
import time
import threading

#from VideoPlayer import NodeVideoPlayers
#from AudioPlayer import NodeAudioPlayers
from .log import logger

class OssiaServer(threading.Thread):
    def __init__(self, node_id, in_port, out_port, queue):
        super().__init__(name='ossia')
        self.server_running = True

        self.conf_queue = queue
        # Main thread queue attendant loop
        self.conf_queue_loop = threading.Thread(target=self.conf_queue_consumer, name='mtqueueconsumer')
        self.conf_queue_loop.start()

        # OSC nodes dicts
        # for the oscquery connection
        self.oscquery_registered_nodes = dict()
        # and for the dinamically registered osc devices
        self.osc_devices = dict()
        self.osc_registered_nodes = dict()

        # Ossia Device and OSCQuery server creation
        self.oscquery_device = ossia.LocalDevice(f'node_{node_id:03}_oscquery')
        self.oscquery_device.create_oscquery_server(    in_port, 
                                                        out_port, 
                                                        False)
        logger.info(f'OscQuery device listening on port {in_port}')

        # OSC messages queue
        self.oscquery_messageq = ossia.MessageQueue(self.oscquery_device)

    def start(self):
        self.server_running = True

        # Message loop
        self.thread = threading.Thread(target=self.threaded_loop, name='OSCQuery')
        self.thread.start()

    def stop(self):
        self.server_running = False
        while not self.conf_queue.empty():
            self.conf_queue.get()
        self.thread.join()
        self.conf_queue_loop.join()
        
    def threaded_loop(self):
        while self.server_running:
            oscq_message = self.oscquery_messageq.pop()
            while (oscq_message != None):
                parameter, value = oscq_message
                if self.oscquery_registered_nodes[str(parameter.node)][1] is not None:
                    self.oscquery_registered_nodes[str(parameter.node)][1](value=value)
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
            if not self.conf_queue.empty():
                item = self.conf_queue.get()
                if item.action == 'add':
                    self.add_nodes(item)
                elif item.action == 'remove':
                    self.remove_nodes(item)
                self.conf_queue.task_done()
            time.sleep(0.004)

    def add_nodes(self, qdata):
        if isinstance(qdata, QueueOSCData):
            self.osc_devices[qdata.device_name] = ossia.ossia.OSCDevice(
                                                        f'remoteAudioPlayer{qdata.device_name}', 
                                                        qdata.host, 
                                                        qdata.in_port, 
                                                        qdata.out_port)
            for route, conf in qdata.items():
                temp_node = self.osc_devices[qdata.device_name].add_node(route)
                # conf[0] holds the OSC type of data
                temp_node.create_parameter(conf[0])
                temp_node.parameter.access_mode = ossia.AccessMode.Bi
                temp_node.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On

                # conf[1] holds the method to call when received such a route
                self.osc_registered_nodes[qdata.device_name + route] = [temp_node, conf[1]]

            # logger.info(f'OSC Nodes listening on {qdata.in_port}: {self.osc_registered_nodes[qdata.device_name + route]}')
        elif isinstance(qdata, QueueData):
            for route, conf in qdata.items():
                temp_node = self.oscquery_device.add_node(route)
                temp_node.create_parameter(conf[0])
                temp_node.parameter.access_mode = ossia.AccessMode.Bi
                temp_node.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
                self.oscquery_messageq.register(temp_node.parameter)
                
                self.oscquery_registered_nodes[route] = [temp_node, conf[1]]

            # logger.info(f'OSCQuery Nodes registered: {qdata}')

    def remove_nodes(self, qdata):
        if isinstance(qdata, QueueOSCData):
            self.osc_devices.pop(qdata.device_name)
            for route, conf in qdata.items():
                self.osc_registered_nodes.pop(qdata.device_name + route)

        elif isinstance(qdata, QueueData):
            for route, conf in qdata.items():
                try:
                    self.oscquery_registered_nodes.pop(route)
                except:
                    pass

class QueueData(dict):
    def __init__(self, action, dictionary):
        self.action = action
        super().__init__(dictionary)

class QueueOSCData(QueueData):
    def __init__(self, action, device_name, host = '', in_port = 0, out_port = 0, dictionary = {}):
        self.device_name = device_name
        self.host = host
        self.in_port = in_port
        self.out_port = out_port
        super().__init__(action, dictionary)