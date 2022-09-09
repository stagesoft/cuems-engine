#import pyossia as ossia
import pyossia as ossia
import time
import threading
from queue import Queue

#from VideoPlayer import NodeVideoPlayers
#from AudioPlayer import NodeAudioPlayers
from .log import logger

''' NOT IMPLEMENTED YET
class LocalOSCQDevice():
    def __init__(self, name = 'LocalOSCQDevice', ws_port=9090, osc_port=9091, log=False):
        self._name = name
        self._ws_port = ws_port
        self._osc_port = osc_port
        self._device = ossia.LocalDevice(self.name)
        self._device.create_oscquery_server(self.osc_port, self.ws_port, log)
        logger.info(f'Local OscQuery device opened with ports: WS {ws_port} OSC {osc_port}')

        self.nodes = {}
        self.queue = ossia.MessageQueue(self._device)

class RemoteOSCQDevice():
    def __init__(self):
        self.device = None
        self.ws_port = None
        self.osc_port = None
        self.nodes = {}
        self.queue = ossia.MessageQueue(self._device)

class RemoteOSCDevice():
    def __init__(self):
        self.device = None
        self.in_port = None
        self.out_port = None
        self.nodes = {}
        self.queue = ossia.MessageQueue(self._device)
'''

class OssiaServer(threading.Thread):
    def __init__(self, node_id, ws_port, osc_port, master = False):
        super().__init__(target=self.threaded_meta_loop, name='OSCMsgQueuesLoop')
        self.server_running = True

        self.internal_queue_loop = threading.Thread(target=self.threaded_internal_loop, name='OSCInternalQueueLoop')
        self.local_queue_loop = threading.Thread(target=self.threaded_local_loop, name='OSCLocalQueueLoop')
        self.remote_queue_loop = threading.Thread(target=self.threaded_remote_loop, name='OSCRemoteQueueLoop')

        # Ossia Local OSCQuery device and server creation
        self.node_id = node_id
        self.master = master
        if self.master:
            local_device_name = f'{self.node_id}_master_root'
        else:
            local_device_name = f'{self.node_id}_slave_root'

        self._oscquery_local_device = ossia.LocalDevice(local_device_name)
        try:
            while not self._oscquery_local_device.create_oscquery_server(osc_port, ws_port, False):
                ws_port += 1
            logger.info(f'Local OscQuery device opened with ports: WS {ws_port} OSC {osc_port}')
        except Exception as e:
            logger.exception(e)

        # Internal OSC sending queue 
        self._oscquery_internal_messageq = Queue()
        # Local OSC messages queue
        self._oscquery_local_messageq = ossia.GlobalMessageQueue(self._oscquery_local_device)

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
        
        # Global Message queues for each device
        self.gmessageqs = list()
        # self.gmessageqs.append(ossia.GlobalMessageQueue(self._oscquery_local_device))

        self.start()

    def stop(self):
        self.server_running = False

    def threaded_meta_loop(self):
        self.internal_queue_loop.start()
        self.local_queue_loop.start()
        self.remote_queue_loop.start()
        # self.global_queue_loop.start()

    def send_message(self, route, value):
        self._oscquery_registered_nodes[route][0].value = value
        ossia_parameter = self._oscquery_registered_nodes[route][0]
        qmessage = ossia_parameter, value
        self._oscquery_internal_messageq.put(qmessage)


    def route_messages(self, parameter, value):
        
        # print(f'LOCAL QUEUE : param : {str(parameter.node)} value : {value}')

        # Try to copy the message on the appropriate nodes
        try:
            # if the message has a route to any of the local players...
            if str(parameter.node) in self.osc_player_registered_nodes.keys():
                self.osc_player_registered_nodes[str(parameter.node)][0].value = value
                # print(f'Message on the LOCAL queue copied to osc_player_registered_nodes - {str(parameter.node)} : {value}')
        except KeyError:
            logger.info(f'OSC device has no {str(parameter.node)} node')
        except Exception as e:
            logger.exception(e)

        # Try to copy the message on the appropriate nodes
        try:
            # if the message has a route to any of the local players...
            if str(parameter.node) in self.oscquery_slave_registered_nodes.keys():
                self.oscquery_slave_registered_nodes[str(parameter.node)][0].value = value
                # print(f'Message on the LOCAL queue copied to osc_player_registered_nodes - {str(parameter.node)} : {value}')
        except KeyError:
            logger.info(f'OSC device has no {str(parameter.node)} node')
        except Exception as e:
            logger.exception(e)

        if str(parameter.node)[:13] == '/engine/comms/':
            # If we are master we filter the comms OSC messages and
            # try to copy them to all the slaves directly
            # print(f'Copying comms to slaves / master...')
            for device in self.oscquery_slave_devices.keys():
                self.oscquery_slave_registered_nodes[f'/{device}{str(parameter.node)}'][0].value = value
                self._oscquery_registered_nodes[f'/{device}{str(parameter.node)}'][0].value = value

        # Try to call a callback for that node if there is any
        try:
            if self._oscquery_registered_nodes[str(parameter.node)][1]:
                # if the node has a callback, let's call it
                self._oscquery_registered_nodes[str(parameter.node)][1](value=value)
        except KeyError:
            logger.info(f'OSCQuery local device has no {str(parameter.node)} node')
        except Exception as e:
            logger.exception(e)


    def threaded_internal_loop(self):
        while self.server_running:
            # internally generated osc messages
            while not self._oscquery_internal_messageq.empty():
                internalq_message = self._oscquery_internal_messageq.get()
                parameter, value = internalq_message
                self.route_messages(parameter, value)

    
    def threaded_local_loop(self):
        while self.server_running:
            # Loop for the local queue
            oscq_message = self._oscquery_local_messageq.pop()
            while (oscq_message != None):
                parameter, value = oscq_message

                self.route_messages(parameter, value)

                oscq_message = self._oscquery_local_messageq.pop()
            
            time.sleep(0.001)

    def threaded_remote_loop(self):
        while self.server_running:
            for device, queue in self.oscquery_slave_messageqs.items():
                # Loop for the remote queues
                oscq_message = queue.pop()
                while (oscq_message != None):
                    parameter, value = oscq_message

                    # print(f'REMOTE QUEUE : device {device} param : {str(parameter.node)} value : {value}')

                    self._oscquery_registered_nodes[f'/{device}{str(parameter.node)}'][0].value = value if value else ''
                    self.oscquery_slave_registered_nodes[f'/{device}{str(parameter.node)}'][0].value = value if value else ''

                    if not self.master:
                        try:
                            self._oscquery_registered_nodes[str(parameter.node)][0].value = value
                        except KeyError:
                            pass

                    '''
                    try:
                        # Try to copy the message on the appropriate nodes
                        self._oscquery_registered_nodes[str(parameter.node)][0].value = value
                        # if the message has a route to any of the local players...
                        if str(parameter.node) in self.osc_player_registered_nodes.keys() and self.osc_player_registered_nodes[str(parameter.node)][0].value != value:
                            self.osc_player_registered_nodes[str(parameter.node)][0].value = value
                            print(f'Message on the REMOTE queue copied to osc_player_registered_nodes - {str(parameter.node)} : {value}')

                        # if the message has a route to any of the other nodes...
                        if str(parameter.node) in self.oscquery_slave_registered_nodes.keys() and self.oscquery_slave_registered_nodes[str(parameter.node)][0].value != value:
                            self.oscquery_slave_registered_nodes[str(parameter.node)][0].value = value
                            print(f'Message on the REMOTE queue copied to oscquery_slave_registered_nodes - {str(parameter.node)} : {value}')
                    except KeyError:
                        logger.info(f'OSC device has no {str(parameter.node)} node')
                    except Exception as e:
                        logger.exception(e)
                    '''


                    oscq_message = queue.pop()

            time.sleep(0.005)

    def add_player_nodes(self, data):
        if isinstance(data, PlayerOSCConfData):
            # REGISTERING A PLAYER
            self.osc_player_devices[data.device_name] = ossia.ossia.OSCDevice(
                                                        f'{data.device_name}', 
                                                        data.host, 
                                                        data.in_port, 
                                                        data.out_port)
            for route, conf in data.items():
                temp_node = self.osc_player_devices[data.device_name].add_node(route)
                temp_node.critical = True
                # conf[0] holds the OSC type of data

                parameter = temp_node.create_parameter(conf[0])
                parameter.access_mode = ossia.AccessMode.Bi
                parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
                # conf[1] holds the method to call when received such a route
                self.osc_player_registered_nodes[data.device_name + route] = [parameter, conf[1]]

                ############ Register also the node on the local oscquery device tree
                temp_node = self._oscquery_local_device.add_node(data.device_name + route)
                temp_node.critical = True
                # conf[0] holds the OSC type of data

                parameter = temp_node.create_parameter(conf[0])
                parameter.access_mode = ossia.AccessMode.Bi
                parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
                # self._oscquery_local_messageq.register(parameter)
                # conf[1] holds the method to call when received such a route
                self._oscquery_registered_nodes[data.device_name + route] = [parameter, conf[1]]

            # logger.info(f'OSC Nodes listening on {data.in_port}: {self.osc_player_registered_nodes[data.device_name + route]}')

    def add_master_node(self, data):
        ''' Just an alias to add_other_nodes to make code more readable
            But it also adds a small delay for the master node to do it a bit later
        '''
        time.sleep(1)
        self.add_other_nodes(data)

    def add_slave_nodes(self, data):
        ''' Just an alias to add_other_nodes to make code more readable
            But it also adds a small delay for the master node to do it a bit later
        '''
        self.add_other_nodes(data)

    def add_other_nodes(self, data):
        if isinstance(data, SlaveOSCQueryConfData):
            self.oscquery_slave_devices[data.device_name] = ossia.OSCQueryDevice(  data.device_name, 
                                                                                    f'ws://{data.host}:{data.ws_port}', 
                                                                                    data.osc_port)

            self.oscquery_slave_devices[data.device_name].update()
            # node_vec = self.oscquery_slave_devices[data.device_name].root_node.get_nodes()
            param_vec = self.oscquery_slave_devices[data.device_name].root_node.get_parameters()
            self.oscquery_slave_messageqs[data.device_name] = ossia.GlobalMessageQueue(self.oscquery_slave_devices[data.device_name])
            # self.gmessageqs.append(ossia.GlobalMessageQueue(self.oscquery_slave_devices[data.device_name]))

            for param in param_vec:
                # self.oscquery_slave_messageqs[data.device_name].register(param)
                self.oscquery_slave_registered_nodes[f'/{data.device_name}{str(param.node)}'] = [param, None]

                ############ Register also the node on the local oscquery device tree
                temp_node = self._oscquery_local_device.add_node(data.device_name + str(param.node))
                temp_node.critical = True
                parameter = temp_node.create_parameter(param.value_type)
                parameter.access_mode = param.access_mode
                parameter.repetition_filter = param.repetition_filter
                # self._oscquery_local_messageq.register(parameter)
                
                self._oscquery_registered_nodes[f'/{data.device_name}{str(param.node)}'] = [parameter, None]

    def add_local_nodes(self, data):
        if isinstance(data, MasterOSCQueryConfData):
            for route, conf in data.items():
                temp_node = self._oscquery_local_device.add_node(f'{route}')
                temp_node.critical = True
                parameter = temp_node.create_parameter(conf[0])
                parameter.access_mode = ossia.AccessMode.Bi
                parameter.repetition_filter = ossia.ossia_python.RepetitionFilter.On
                # self._oscquery_local_messageq.register(parameter)
                
                self._oscquery_registered_nodes[f'{route}'] = [parameter, conf[1]]

            # logger.info(f'OSCQuery Nodes registered: {data}')

    def remove_nodes(self, data):
        if isinstance(data, OSCConfData):
            for route in data.keys():
                try:
                    self.osc_player_registered_nodes.pop(data.device_name + route)
                except Exception as e:
                    logger.exception(e)

                try:
                    self._oscquery_registered_nodes.pop(data.device_name + route)
                except Exception as e:
                    logger.exception(e)

            try:
                self.osc_player_devices.pop(data.device_name)
            except KeyError:
                try:
                    self.oscquery_slave_devices.pop(data.device_name)
                except Exception as e:
                    logger.exception(e)
            except Exception as e:
                logger.exception(e)
            

class OSCConfData(dict):
    def __init__(self, device_name, dictionary = {}):
        self.device_name = device_name
        super().__init__(dictionary)

class MasterOSCQueryConfData(OSCConfData):
    pass
class PlayerOSCConfData(OSCConfData):
    def __init__(self, device_name, host = '', in_port = 0, out_port = 0, dictionary = {}):
        self.device_name = device_name
        self.host = host
        self.in_port = in_port
        self.out_port = out_port
        super().__init__(device_name, dictionary)

class SlaveOSCQueryConfData(OSCConfData):
    def __init__(self, device_name, host = '', ws_port = 0, osc_port = 0, dictionary = {}):
        self.device_name = device_name
        self.host = host
        self.ws_port = ws_port
        self.osc_port = osc_port
        super().__init__(device_name, dictionary)