from culsans import Queue
from threading import Thread
from time import sleep
import asyncio

from cuemsutils.log import Logger, logged
from cuemsutils.helpers import new_uuid
from .tools.communicate import ComsThread, TIMEOUT

from .core.BaseEngine import BaseEngine
from .tools.communicate import ComsThread
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
        self._msg_queue = Queue()
        self.sync_msg_queue = self._msg_queue.sync_q
        self.async_msg_queue = self._msg_queue.async_q
        self.ws_server = None
        
        


    def start(self):
        # self.set_ws_server()
        self.set_comms()
        self.set_editor_request('')
        super().start()
    
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
        Logger.info('Setting up Communicators')
        #self.hw_discovery = call_hwdiscovery()
        # self.mtc = Communicator(address = AddressHandler.get("mtc"))
        #self.node_conf = Communicator(address = AddressHandler.get("node_conf"))
        listener_addresses = {'editor': 'ipc://tmp/editor.ipc'}
        dialer_adresses = {'hw_discovery': 'ipc://tmp/hw_discovery.ipc'}
        self.communications_thread = ComsThread(self.async_msg_queue, self.editor_command_callback)
        self.communications_thread.start()



    def stop(self):
        self.stop_queues()
        self.stop_comms()
        super().stop()

    @logged
    def stop_queues(self):


        while not self.sync_msg_queue.empty():
            self.sync_msg_queue.get()
        self.sync_msg_queue.close()
        Logger.debug('IPC queues clean and closed')

    @logged
    def stop_comms(self):
        if self.with_mtc:
            self.stop_mtc()
        if self.ws_server:
            self.stop_ws_server()
        if self.oscquery_server:
            self.oscquery_server.remove_device()
        self._loop.call_soon_threadsafe(self._loop.stop)

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


    def editor_command_callback(self, item, context):
        Logger.debug(f'Received editor command: {item}, with context: {context}')
        _item_keys = item.keys()
        if 'action_uuid' not in _item_keys:
            self.error_to_editor(self._editor_request_uuid, "No action uuid submitted")
        self._editor_request_uuid = item['action_uuid']

        if 'type' in _item_keys:
            if item['type'] not in ['error', 'initial_settings']:
                
                self._editor_request_uuid = ''
            self.error_to_editor(self._editor_request_uuid, "Response not recognized")

        try:
            self.handle_editor_command(
                action = item['action'],
                value = item['value'], 
                context = context
            ) 
        except Exception as e:
            Logger.error(
                f'Error handling editor command: {e}'
            )
            
            self._editor_request_uuid = ''
            self.error_to_editor(self._editor_request_uuid, f"Command error: {e}")

    def handle_editor_command(self, action, value, context=None):
        command_dict = {
        #    'project_deploy': self.deploy_callback,
            'project_ready': self.load_project,
            'hw_discovery': self.hwdiscovery
        }
        if action in command_dict.keys():
            _editor_request_uuid = self._editor_request_uuid
            success  = command_dict[action](value, context)
            if success:
                self.confirm_to_editor(type=action, value='OK', request_uuid=_editor_request_uuid, context=context)
            
        else:
            raise ValueError(f'Command {action} not recognized')
        
    def confirm_to_editor(self, type=None, action=None, request_uuid=None, value=None, context=None):
        
        return_message={
            'type': type,
            'value': value,
            'action_uuid': request_uuid
        }
        self.reply_to_editor(return_message, context)

    def error_to_editor(self, value, request_uuid = None, action = None, context=None):
        if not action_uuid:
            action_uuid = self.get_editor_request()
        if not action:
            action = 'error'
        return_message={
            'type': type,
            'value': value,
            'action_uuid': request_uuid
        }
        self.reply_to_editor(return_message, context)
        
    def reply_to_editor(self, message, context=None):
        send_task = asyncio.run_coroutine_threadsafe(self.communications_thread.editor.responder_post_reply(message, context), self.communications_thread.event_loop)
        try:
            result = send_task.result(timeout=TIMEOUT)
        except TimeoutError:
            Logger.debug('The coroutine took too long, cancelling the task...')
            send_task.cancel()
        except Exception as exc:
            Logger.debug(f'The coroutine raised an exception: {exc!r}')
        else:
            Logger.debug(f'The coroutine returned: {result!r}')

    def hwdiscovery(self, message: dict, context=None) -> None:
        Logger.debug(f'sending HW discovery request: {message}')
        reply = self.request_to_hwdiscovery(message)
        Logger.debug(f'Received HW discovery reply: {reply}')
        if 'OK' in reply.values():
            return True
        else:
            return False            

    def request_to_hwdiscovery(self, message: dict) -> dict:
        send_task = asyncio.run_coroutine_threadsafe(self.communications_thread.hw_discovery.send_request(message), self.communications_thread.event_loop)
        try:
            result = send_task.result(timeout=TIMEOUT)
            
        except TimeoutError:
            Logger.debug('The coroutine took too long, cancelling the task...')
            send_task.cancel()
        except Exception as exc:
            Logger.debug(f'The coroutine raised an exception: {exc!r}')
        else:
            Logger.debug(f'The coroutine returned: {result!r}')
            return result
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
            #'load': self.load_project,
            # disabled because it trigers a doble load when called from editor
            'loadcue': None, # self.load_cue,
            'go': self.go_script,
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

    def load_project(self, project_name, context=None):
        if self.get_status('load') == project_name:
            Logger.info(f'Project {project_name} already loaded')
            return True

        Logger.info(f'Loading project {project_name}')
        self.reset_script()
        
        try:
            self.cm.load_project_config(project_name)
        except Exception as e:
            Logger.error(f'Error loading project config: {e}')
            
            self.set_editor_request('')
            self.error_to_editor(
                f"Project config error: {e}",
                'project_ready'
            )

        try:
            self.read_script(project_name)
        except Exception as e:
            Logger.error(f'Error loading project script: {e}')
            
            self.set_editor_request('')
            self.error_to_editor(
                f"Project script error: {e}",
                'project_ready'
            )
        
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
        return True

    def go_script(self, value):
        if self.get_status('go') == value:
            return

        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return
        
        self.set_status('go', value)
        
        self.set_oscquery_values({
            '/engine/status/running': 1,
            '/engine/command/go': value
        })
