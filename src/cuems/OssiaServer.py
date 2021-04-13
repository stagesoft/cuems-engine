#import pyossia as ossia
import pyossia as ossia
import time
import threading

#from VideoPlayer import NodeVideoPlayers
#from AudioPlayer import NodeAudioPlayers
from .log import logger

class OssiaServer(threading.Thread):
    def __init__(self, node_id, ws_port, osc_port, queue, master = False):
        super().__init__(target=self.threaded_loop, name='OSCMsgQueuesLoop')
        self.server_running = True

        # Threaded configuration queue and loop
        self.conf_queue = queue
        # Main thread conf queue attendant loop
        self.conf_queue_loop = threading.Thread(target=self.conf_queue_consumer, name='mtqueueconsumer')
        self.conf_queue_loop.start()

        # Ossia Local OSCQuery device and server creation
        self.node_id = node_id
        if master:
            local_device_name = f'{self.node_id}_master_root'
        else:
            local_device_name = f'{self.node_id}_slave_root'

        self._oscquery_local_device = ossia.LocalDevice(local_device_name)
        self._oscquery_local_device.create_oscquery_server(    osc_port, 
                                                        ws_port, 
                                                        True)
        logger.info(f'OscQuery device listening websocket on port {ws_port} and listening OSC on port {osc_port}')

        # Local OSC messages queue
        self._oscquery_local_messageq = ossia.MessageQueue(self._oscquery_local_device)

        # OSC nodes information
        # for the local OSCQuery connection
        self._oscquery_registered_nodes = dict()

        # for the dinamically registered OSC player devices
        self.osc_player_devices = dict()
        self.osc_player_registered_nodes = dict()

        # for the dinamically registered OSC player devices
        self.oscquery_slave_devices = dict()
        self.oscquery_slave_registered_nodes = dict()

        # Remote devices OSC message queues list
        self.oscquery_slave_messageqs = dict()

        self.start()

    def stop(self):
        self.server_running = False
        while not self.conf_queue.empty():
            self.conf_queue.get()
        self.conf_queue_loop.join()
        
    def threaded_loop(self):
        while self.server_running:
            # Loop for the local queue
            oscq_message = self._oscquery_local_messageq.pop()
            while (oscq_message != None):
                parameter, value = oscq_message
                logger.debug(f'############# OSC message on the local loop: node = {str(parameter.node)}, value = {value}')
                try:
                    # if the message has a route to any of the local players...
                    if str(parameter.node) in self.osc_player_registered_nodes.keys():
                        self.osc_player_registered_nodes[str(parameter.node)][0].parameter.value = value

                    # if the message has a route to any of the slaves oscquery nodes...
                    if str(parameter.node) in self.oscquery_slave_registered_nodes.keys():
                        self.oscquery_slave_registered_nodes[str(parameter.node)][0].parameter.value = value
                except KeyError:
                    logger.info(f'OSC device has no {str(parameter.node)} node')
                except Exception as e:
                    logger.exception(e)

                try:
                    if self._oscquery_registered_nodes[str(parameter.node)][1] is not None:
                        # if the node has a callback, let's call it
                        self._oscquery_registered_nodes[str(parameter.node)][1](value=value)
                except KeyError:
                    logger.info(f'OSCQuery local device has no {str(parameter.node)} node')
                except Exception as e:
                    logger.exception(e)

                oscq_message = self._oscquery_local_messageq.pop()
            
            '''
            for queue in self.oscquery_slave_messageqs.values():
                # Loop for the remote queues
                oscq_message = queue.pop()
                while (oscq_message != None):
                    parameter, value = oscq_message
                    logger.debug(f'############# OSC message on the remote loop: node = {str(parameter.node)}, value = {value}')
                    try:
                        # if the message has a route to any of the local oscquery nodes...
                        if str(parameter.node) in self._oscquery_registered_nodes.keys():
                            self._oscquery_registered_nodes[str(parameter.node)][0].parameter.value = value
                    except KeyError:
                        logger.info(f'OSCQuery remote device has no {str(parameter.node)} node')
                    except Exception as e:
                        logger.exception(e)

                    try:
                        if self.oscquery_slave_registered_nodes[str(parameter.node)][1] is not None:
                            # if the node has a callback, let's call it
                            self.oscquery_slave_registered_nodes[str(parameter.node)][1](value=value)
                    except KeyError:
                        logger.info(f'OSC has no {str(parameter.node)} node')
                    except Exception as e:
                        logger.exception(e)

                    for device in self.oscquery_slave_devices.values():
                        device.update()

                    oscq_message = queue.pop()
                '''

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
        if isinstance(qdata, QueuePlayerOSCData):
            # REGISTERING A PLAYER
            self.osc_player_devices[qdata.device_name] = ossia.ossia.OSCDevice(
                                                        f'{qdata.device_name}', 
                                                        qdata.host, 
                                                        qdata.in_port, 
                                                        qdata.out_port)
            for route, conf in qdata.items():
                temp_node = self.osc_player_devices[qdata.device_name].add_node(self.node_id + route)

                # conf[0] holds the OSC type of data
                temp_node.create_parameter(conf[0])
                temp_node.parameter.access_mode = ossia.AccessMode.Bi
                temp_node.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On

                # conf[1] holds the method to call when received such a route
                self.osc_player_registered_nodes[qdata.device_name + route] = [temp_node, conf[1]]

            ############ Register also the node on the local oscquery device tree
            for route, conf in qdata.items():
                temp_node = self._oscquery_local_device.add_node(qdata.device_name + route)
                temp_node.create_parameter(conf[0])
                temp_node.parameter.access_mode = ossia.AccessMode.Bi
                temp_node.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
                self._oscquery_local_messageq.register(temp_node.parameter)
                
                self._oscquery_registered_nodes[qdata.device_name + route] = [temp_node, conf[1]]

            # logger.info(f'OSC Nodes listening on {qdata.in_port}: {self.osc_player_registered_nodes[qdata.device_name + route]}')

        elif isinstance(qdata, QueueSlaveOSCQueryData):
            # REGISTERING A SLAVE OSCQUERY
            self.oscquery_slave_devices[qdata.device_name] = ossia.ossia.OSCQueryDevice(qdata.device_name, 
                                                                                        f'{qdata.host}:{qdata.ws_port}', 
                                                                                        qdata.osc_port)

            self.oscquery_slave_devices[qdata.device_name].update()

            self.oscquery_slave_messageqs[qdata.device_name] = ossia.MessageQueue(self.oscquery_slave_devices[qdata.device_name])

            self.recursive_slave_nodes_register(self.oscquery_slave_devices[qdata.device_name].root_node, qdata.device_name)

            # logger.info(f'OSC Nodes listening on {qdata.in_port}: {self.osc_player_registered_nodes[qdata.device_name + route]}')

        elif isinstance(qdata, QueueMasterOSCQueryData):
            # REGISTERING LOCAL OSCQUERY STUFF
            for route, conf in qdata.items():
                temp_node = self._oscquery_local_device.add_node(f'/{self.node_id}{route}')
                temp_node.create_parameter(conf[0])
                temp_node.parameter.access_mode = ossia.AccessMode.Bi
                temp_node.parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
                self._oscquery_local_messageq.register(temp_node.parameter)
                
                self._oscquery_registered_nodes[f'/{self.node_id}{route}'] = [temp_node, conf[1]]

            # logger.info(f'OSCQuery Nodes registered: {qdata}')

    def recursive_slave_nodes_register(self, node, dev_name):
        if node.parameter:
            # Let's register in the messageq the remote oscquery node parameter
            self.oscquery_slave_messageqs[dev_name].register(node.parameter)

            self.oscquery_slave_registered_nodes[str(node)] = [node, None]

            ############ Register also the node on the local oscquery device tree
            try:
                temp_node = self._oscquery_local_device.add_node(str(node))
                temp_node.create_parameter(node.parameter.value_type)
                temp_node.parameter.access_mode = node.parameter.access_mode
                temp_node.parameter.repetition_filter = node.parameter.repetition_filter
                
                self._oscquery_local_messageq.register(temp_node.parameter)

                self._oscquery_registered_nodes[str(node)] = [node, None]
            except Exception as e:
                logger.exceptio(e)

        # logger.info(f'OSC Nodes listening on {qdata.in_port}: {self.osc_player_registered_nodes[qdata.device_name + route]}')

        for child in node.children():
            self.recursive_slave_nodes_register(child, dev_name)

    def remove_nodes(self, qdata):
        if isinstance(qdata, QueueOSCData):
            self.osc_player_devices.pop(qdata.device_name)
            for route, _ in qdata.items():
                self.osc_player_registered_nodes.pop(qdata.device_name + route)
            for route, _ in qdata.items():
                self._oscquery_registered_nodes.pop(qdata.device_name + route)

        elif isinstance(qdata, QueueData):
            for route, _ in qdata.items():
                try:
                    self._oscquery_registered_nodes.pop(route)
                except:
                    pass

class QueueData(dict):
    def __init__(self, action, dictionary):
        self.action = action
        super().__init__(dictionary)

class QueueMasterOSCQueryData(QueueData):
    pass
class QueuePlayerOSCData(QueueData):
    def __init__(self, action, device_name, host = '', in_port = 0, out_port = 0, dictionary = {}):
        self.device_name = device_name
        self.host = host
        self.in_port = in_port
        self.out_port = out_port
        super().__init__(action, dictionary)

class QueueSlaveOSCQueryData(QueueData):
    def __init__(self, action, device_name, host = '', ws_port = 0, osc_port = 0, dictionary = {}):
        self.device_name = device_name
        self.host = host
        self.ws_port = ws_port
        self.osc_port = osc_port
        super().__init__(action, dictionary)