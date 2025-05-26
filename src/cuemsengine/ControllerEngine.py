from multiprocessing import Queue as MPQueue
from threading import Thread
from time import sleep

from cuemsutils.log import Logger, logged
from cuemsutils.helpers import new_uuid
from cuemsutils.CommunicatorServices import Communicator
# from cuemsutils.AddressHandler import AddressHandler

from .core.BaseEngine import BaseEngine
from .tools.communicate import EditorWsServer
from .osc import OssiaServer, ServerDevices

CONTROLLER_HOST = "main.local"

class ControllerEngine(BaseEngine):
    '''
    The main engine class for the CUEMS system.
    
    An object of this class runs all the inner logical part of communications with:
      - The WebSocket system
      - The Ossia System
      - The MTC System
      - The NodeEngine local and remote instances
      - The NNG communication system

    It is responsible for:
      - Monitoring the NodeEngine local and remote instances
      - Restarting the NodeEngine local and remote instances
      - Updating the NodeEngine local and remote instances
      - Handling the NodeEngine local and remote instances failures
      - Handling the NNG communication system
      - Handling the WebSocket system
      - Handling the Ossia System
      - Handling the MTC master system
      - Handling the NodeConf system
    '''
    def __init__(self):
        super().__init__()
        self.engine_queue = MPQueue()
        self.editor_queue = MPQueue()
        
        self.set_comms()

        self.run()

    @logged
    def set_comms(self):
        self.set_ws_server()
        self.set_oscquery_server()

    def set_ws_server(self):
        """Set the websocket server for the front-end"""
        Logger.info(f'ControllerEngine@{self.node_name} starting Websocket Server')
        settings_dict = {
            'session_uuid': str(new_uuid()),
            'library_path': self.cm.library_path,
            'tmp_path': self.cm.tmp_path,
            'database_name': self.cm.database_name,
            'load_timeout': self.cm.node_conf['load_timeout'],
            'discovery_timeout': self.cm.node_conf['discovery_timeout']
        }
        self.ws_server = EditorWsServer(
            self.engine_queue,
            self.editor_queue,
            settings_dict,
            self.cm.network_mappings
        )
        self._editor_request_uuid = ''
        
        try:
            self.ws_server.start(self.cm.node_conf['websocket_port'])
        except KeyError:
            self.stop()
            Logger.error('Config error, websocket_port key not found in settings. Exiting.')
            exit(-1)
        except Exception as e:
            self.stop()
            Logger.error('Exception when starting websocket server. Exiting.')
            Logger.error(e)
            exit(-1)
        else:
            # Threaded own queue consumer loop
            self.engine_queue_loop = Thread(
                target=self.engine_queue_consumer,
                name='engineq_consumer'
            )
            self.engine_queue_loop.start()

    def stop(self):
        self.stop_queues()
        self.stop_comms()
        super().stop()

    @logged
    def stop_queues(self):
        while not self.engine_queue.empty():
            self.engine_queue.get()
        self.engine_queue_loop.join()
        self.engine_queue.close()

        while not self.editor_queue.empty():
            self.editor_queue.get()
        self.editor_queue.close()
        Logger.debug('IPC queues clean and closed')

    @logged
    def stop_comms(self):
        self.ws_server.stop()
        if hasattr(self.ws_server, 'close'):
            self.ws_server.close()
        Logger.info('Websocket server stopped')

    def on_timecode_change(self, value: str) -> None:
        Logger.debug(f'Timecode changed to {value}')
        if self.go_offset:
            self.send_oscquery_value(f'/engine/status/timecode', value)

    def engine_queue_consumer(self):
        while not self.stop_requested:
            if not self.engine_queue.empty():
                item = self.engine_queue.get()
                Logger.debug(f'Received queue message from WS server: {item}')
                self.editor_command_callback(item)
            sleep(0.004)

    def editor_command_callback(self, item):
        _item_keys = item.keys()
        if 'action_uuid' not in _item_keys:
            self.error_to_editor(self._editor_request_uuid, "No action uuid submitted")
            return
        self._editor_request_uuid = item['action_uuid']

        if 'type' in _item_keys:
            if item['type'] not in ['error', 'initial_settings']:
                self.error_to_editor(self._editor_request_uuid, "Response not recognized")
                self._editor_request_uuid = ''
            return

        try:
            self.handle_editor_command(
                action = item['action'],
                value = item['value']
            )
        except Exception as e:
            Logger.error(
                f'Error handling editor command: {e}'
            )
            self.error_to_editor(self._editor_request_uuid, f"Command error: {e}")
            self._editor_request_uuid = ''
            return
        

    def handle_editor_command(self, action, value):
        command_dict = {
            'project_deploy': self.deploy_callback,
            'project_ready': self.load_project_callback,
            'hw_discovery': self.hw_discovery_callback
        }
        if action in command_dict.keys():
            command_dict[action](value)
        else:
            raise ValueError(f'Command {action} not recognized')

    def set_oscquery_server(self):
        self.oscquery_server = OssiaServer(
            host = CONTROLLER_HOST,
            server = ServerDevices.OSCQUERY
        )

    def register_node_engines(self) -> None:
        """Register the NodeEngines in the OSCQuery server"""
        for host in self.find_hosts():
            endpoints = self.build_status_endpoints(host)
            self.oscquery_server.create_endpoints(endpoints)

    def put_to_editor(self, type, action, action_uuid, value):
        self.editor_queue.put({
            'type': type,
            'action': action,
            'action_uuid': action_uuid,
            'value': value
        })

    def error_to_editor(self, action_uuid, value):
        self.put_to_editor(
            'error', None, action_uuid, value
        )
