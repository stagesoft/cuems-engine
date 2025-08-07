from multiprocessing import Queue as MPQueue
from threading import Thread
from time import sleep

from cuemsutils.log import Logger, logged
from cuemsutils.helpers import new_uuid
from cuemsutils.tools.CommunicatorServices import Communicator
# from cuemsutils.AddressHandler import AddressHandler

from .core.BaseEngine import BaseEngine
from .tools.communicate import EditorWsServer
from .osc import OssiaServer, ServerDevices, ENGINE_CMD_ENDPOINTS
from .osc.helpers import include_function_endpoints

CONTROLLER_HOST = "localhost" #"controller.local"

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
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.engine_queue = MPQueue()
        self.editor_queue = MPQueue()
        self.ws_server = None
        
        # self.set_ws_server()
        self.set_comms()
        self.set_editor_request('')

        self.run()

    @logged
    def set_comms(self):
        # self.set_ws_server()
        self.set_oscquery()
        self.set_communicators()

    def set_ws_server(self):
        """Set the websocket server for the front-end"""
        Logger.info(f'ControllerEngine@{self.node_name} starting Websocket Server')
        settings_dict = {
            'session_uuid': str(new_uuid()),
            'library_path': self.cm.library_path,
            'tmp_path': self.cm.tmp_path,
            'database_name': self.cm.database_name,
            'load_timeout': self.cm.node_conf['load_timeout'],
            'discovery_timeout': self.cm.node_conf['discovery_timeout'],
            'websocket_port': self.cm.node_conf['websocket_port']
        }
        self.ws_server = EditorWsServer(
            self.engine_queue,
            self.editor_queue,
            settings_dict,
            self.cm.network_mappings
        )
        self._editor_request_uuid = ''
        
        try:
            self.ws_server.start()
        except KeyError:
            self.stop()
            Logger.error('Config error, websocket_port key not found in settings. Exiting.')
            exit(-1)
        except Exception as e:
            self.stop()
            Logger.error('Exception when starting websocket server. Exiting.')
            Logger.error(e)
            exit(-1)
        # Threaded own queue consumer loop
        # self.engine_queue_loop = Thread(
        #     target=self.engine_queue_consumer,
        #     name='engineq_consumer'
        # )
        # self.engine_queue_loop.start()

    def set_communicators(self):
        pass
        # self.backend = Communicator(address = AddressHandler.get("backend"))
        # self.hw_discovery = Communicator(address = AddressHandler.get("hw_discovery"))
        # self.mtc = Communicator(address = AddressHandler.get("mtc"))
        # self.node_conf = Communicator(address = AddressHandler.get("node_conf"))

    def stop(self):
        self.stop_queues()
        self.stop_comms()
        super().stop()

    @logged
    def stop_queues(self):
        while not self.engine_queue.empty():
            self.engine_queue.get()
        # if self.engine_queue_loop:
        #     self.engine_queue_loop.join()
        self.engine_queue.close()

        while not self.editor_queue.empty():
            self.editor_queue.get()
        self.editor_queue.close()
        Logger.debug('IPC queues clean and closed')

    @logged
    def stop_comms(self):
        if self.with_mtc:
            self.stop_mtc()
        if self.ws_server:
            self.stop_ws_server()
        if self.oscquery_server:
            self.oscquery_server.remove_device()

    @logged
    def stop_ws_server(self):
        self.ws_server.stop()
        if hasattr(self.ws_server, 'close'):
            self.ws_server.close()
        Logger.info('Websocket server stopped')

    @logged
    def stop_mtc(self):
        stop = self.mtc.send_request({'cmd':'stop'})
        release = self.mtc.send_request({'cmd':'release'})
        if stop['resp'] != 'ok' or release['resp'] != 'ok':
            Logger.error('MTC master could not be stopped')
            Logger.error(f"Stop: {stop['resp']}")
            Logger.error(f"Release: {release['resp']}")
        else:
            Logger.info('MTC master stopped')

    def on_timecode_change(self, value: str) -> None:
        Logger.debug(f'Timecode changed to {value}')
        if self.go_offset:
            self.set_oscquery_values({
                '/engine/status/timecode': value
            })

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
            'project_ready': self.load_project,
            'hw_discovery': self.hw_discovery_callback
        }
        if action in command_dict.keys():
            command_dict[action](value)
        else:
            raise ValueError(f'Command {action} not recognized')

    def set_oscquery(self):
        Logger.info("Starting oscquery for Controller")
        self.set_oscquery_server(self.get_status_endpoints())
        self.apply_oscquery_commands()

    def set_oscquery_server(self, endpoints: dict = None):
        self.oscquery_server = OssiaServer(
            # host = CONTROLLER_HOST,
            remote_port = self.cm.node_conf['oscquery_ws_port'],
            server = ServerDevices.OSCQUERY,
            endpoints = endpoints
        )

    def apply_oscquery_commands(self):
        cmd_dict = {
            'load': self.load_project,
            'loadcue': None, # self.load_cue,
            'go': None, # self.go_callback,
            'gocue': None, # self.go_cue_callback,
            'pause': None, # self.pause_callback,
            'stop': None, # self.stop_callback,
            'resetall': None, # self.reset_all_callback,
            'preload': None, # self.load_cue_callback,
            'unload': None, # self.unload_cue_callback,
            'hwdiscovery': None, # self.hw_discovery_callback,
            'deploy': None, # self.deploy_callback,
            'test': None # self.test_callback
        }
        endpoints = include_function_endpoints(
            ENGINE_CMD_ENDPOINTS,
            cmd_dict
        )
        self.oscquery_server.create_endpoints(endpoints)

    def set_oscquery_values(self, values: dict):
        for key, value in values.items():
            self.oscquery_server.set_value(key, value)

    def register_node_engines(self) -> None:
        """Register the NodeEngines in the OSCQuery server"""
        for host in self.find_hosts():
            endpoints = self.build_status_endpoints(host)
            self.oscquery_server.create_endpoints(endpoints)

    def set_editor_request(self, value):
        self._editor_request_uuid = value

    def get_editor_request(self):
        return self._editor_request_uuid

    def put_to_editor(self, type, action, action_uuid, value):
        self.editor_queue.put({
            'type': type,
            'action': action,
            'action_uuid': action_uuid,
            'value': value
        })

    def error_to_editor(self, value, action_uuid = None, action = None):
        if not action_uuid:
            action_uuid = self.get_editor_request()
        if not action:
            action = 'error'
        self.put_to_editor(
            'error', action, action_uuid, value
        )

    def load_project(self, project_name):
        if self.get_status('load') == project_name:
            Logger.info(f'Project {project_name} already loaded')
            return

        Logger.info(f'Loading project {project_name}')
        self.reset_script()
        
        try:
            self.cm.load_project_config(project_name)
        except Exception as e:
            Logger.error(f'Error loading project config: {e}')
            self.error_to_editor(
                f"Project config error: {e}",
                'project_ready'
            )
            self.set_editor_request('')
            return

        try:
            self.read_script(project_name)
        except Exception as e:
            Logger.error(f'Error loading project script: {e}')
            self.error_to_editor(
                f"Project script error: {e}",
                'project_ready'
            )
            self.set_editor_request('')
            return
        
        Logger.info(f'Script from {project_name} loaded')
        self.script.unix_name = project_name
        self.set_status('load', project_name)

        self.set_oscquery_values({
            '/engine/command/load': project_name
        })

        # Confirm the project is loaded
        self.set_show_lock_file()
        self.set_editor_request('')
        Logger.info(f'Project {project_name} loaded')
