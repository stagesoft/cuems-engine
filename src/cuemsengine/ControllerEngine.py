from threading import Thread
from time import sleep
import asyncio
from functools import partial

from cuemsutils.log import Logger, logged
from cuemsutils.helpers import new_uuid

from .core.BaseEngine import BaseEngine, NODE_ENGINE_PORT
from .tools.communicate import AsyncCommsThread, TIMEOUT
from .osc import ENGINE_CMD_ENDPOINTS
from .osc.helpers import add_callbacks_from_dict, add_callback_to_all, add_prefix_to_all
from .tools.mtcmaster import libmtcmaster


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
        self.set_editor_request('')
        

    def start(self):
        self.mtcmaster = libmtcmaster.MTCSender_create()
        self.set_comms()
        super().start()
    
    @logged
    def set_comms(self):
        self.set_oscquery()
        self.set_communicators()

    def set_communicators(self):
        Logger.info('Setting up Communicators')
        self.communications_thread = AsyncCommsThread(self.editor_command_callback)
        self.communications_thread.start()

    def stop(self):
        self.stop_comms()
        super().stop()

    @logged
    def stop_comms(self):
        if self.with_mtc:
            self.stop_mtc()
        if self.oscquery_server:
            self.oscquery_server.remove_device()
        if hasattr(self, '_loop'):
            self._loop.call_soon_threadsafe(self._loop.stop)

    @logged
    def stop_mtc(self):
        libmtcmaster.MTCSender_stop(self.mtcmaster)
        # stop = self.mtc.send_request({'cmd':'stop'})
        # release = self.mtc.send_request({'cmd':'release'})
        # if stop['resp'] != 'ok' or release['resp'] != 'ok':
        #     Logger.error('MTC master could not be stopped')
        #     Logger.error(f"Stop: {stop['resp']}")
        #     Logger.error(f"Release: {release['resp']}")
        # else:
        #     Logger.info('MTC master stopped')

    def on_timecode_change(self, value: str) -> None:
        Logger.debug(f'Timecode changed to {value}')
        if self.go_offset:
            self.set_oscquery_values({
                '/engine/status/timecode': value
            })


    #########################
    # Editor commands
    #########################

    def editor_command_callback(self, item, context):
        Logger.debug(f'Received editor command: {item}, with context: {context}')
        _item_keys = item.keys()
        if 'value' not in _item_keys:
            item['value'] = ''
        if 'action_uuid' not in _item_keys:
            self.error_to_editor(context, "No action uuid submitted")
        self._editor_request_uuid = item['action_uuid']

        if 'type' in _item_keys:
            if item['type'] not in ['error', 'initial_settings']:
                
                self._editor_request_uuid = ''
            self.error_to_editor(context, "Response not recognized")

        try:
            
            self.handle_editor_command(
                action = item['action'],
                value = item['value'], 
                context = context
            ) 
        except Exception as e:
            Logger.error(
                f'Error handling editor command: {e} {type(e)}'
            )
            
            self._editor_request_uuid = ''
            error_string = f"Command error: {e} {type(e)}"
            self.error_to_editor(context,  error_string)

    def handle_editor_command(self, action, value, context=None):
        command_dict = {
            'project_deploy': partial(self.load_project, deploy_only=True),
            'project_ready': self.load_project,
            'hw_discovery': self.hwdiscovery,
            'nodeconf': self.nodeconf,
            'go_script': self.go_script
        }
        if action in command_dict.keys():
            _editor_request_uuid = self._editor_request_uuid
            success  = command_dict[action](value, context)
            if success:
                self.confirm_to_editor(context, type=action, value='OK', request_uuid=_editor_request_uuid)
            
        else:
            raise ValueError(f'Command {action} not recognized')
        
    def confirm_to_editor(self, context, type=None, action=None, request_uuid=None, value=None, ):
        
        return_message={
            'type': type,
            'value': value,
            'action_uuid': request_uuid
        }
        self.reply_to_editor(return_message, context)

    def error_to_editor(self, context, value=None, request_uuid = None, action = None):
        Logger.debug(f'Sending error to editor: {value}, request: {request_uuid}, action:{action}  ')
        if not request_uuid:
            request_uuid = self.get_editor_request()
        if not action:
            action = 'error'
        return_message={
            'type': action,
            'value': value,
            'action_uuid': request_uuid
        }
        Logger.debug(f'Sending error to editor: {return_message}')
        self.reply_to_editor(return_message, context)
        
    def reply_to_editor(self, message, context):
        send_task = asyncio.run_coroutine_threadsafe(self.communications_thread.editor.responder_post_reply(message, context), self.communications_thread.event_loop)
        try:
            _ = send_task.result(timeout=TIMEOUT)
        except TimeoutError:
            Logger.debug('The coroutine took too long, cancelling the task...')
            self.error_to_editor(context, value="Timeout error")
            send_task.cancel()
        except Exception as exc:
            Logger.debug(f'The coroutine raised an exception: {exc!r}')

    def set_editor_request(self, value):
        self._editor_request_uuid = value

    def get_editor_request(self):
        return self._editor_request_uuid


    #########################
    # External services
    #########################

    def hwdiscovery(self, message: dict, context=None) -> None:
        Logger.debug(f'sending HW discovery request: {message}')
        reply = self.request_to_hwdiscovery(message, context)
        Logger.debug(f'Received HW discovery reply: {reply}')
        if 'OK' in reply.values():
            return True
        else:
            return False            

    def request_to_hwdiscovery(self, message: dict, context) -> dict:
        send_task = asyncio.run_coroutine_threadsafe(self.communications_thread.hw_discovery.send_request(message), self.communications_thread.event_loop)
        try:
            result = send_task.result(timeout=TIMEOUT)
            Logger.debug(f'Hwdiscovery request returned: {result!r}')
            return result
        except TimeoutError:
            Logger.debug('Hwdiscovery request took too long, cancelling the task...')
            self.error_to_editor(context, value="Timeout error")
            send_task.cancel()
        except Exception as exc:
            Logger.debug(f'Hwdiscovery request raised an exception: {exc!r}')
            send_task.cancel()

    def nodeconf(self, message: dict, context=None) -> None:
        Logger.debug(f'sending nodeconf request: {message}')
        reply = self.request_to_nodeconf(message, context)
        Logger.debug(f'Received nodeconf reply: {reply}')
        if 'OK' in reply.values():
            return True
        else:
            return False            

    def request_to_nodeconf(self, message: dict, context) -> dict:
        send_task = asyncio.run_coroutine_threadsafe(self.communications_thread.nodeconf.send_request(message), self.communications_thread.event_loop)
        try:
            result = send_task.result(timeout=TIMEOUT)
            Logger.debug(f'Nodeconf request returned: {result!r}')
            return result
        except TimeoutError:
            Logger.debug('Nodeconf request took too long, cancelling the task...')
            self.error_to_editor(context, value="Timeout error")
            send_task.cancel()
        except Exception as exc:
            Logger.debug(f'Nodeconf request raised an exception: {exc!r}')
            send_task.cancel()


    #########################
    # OSCQuery
    #########################

    def set_oscquery(self):
        Logger.info("Starting oscquery for Controller")
        self.set_oscquery_server(self.get_status_endpoints())
        self.apply_oscquery_commands()
        self.set_oscquery_bridge()

    def apply_oscquery_commands(self):
        cmd_dict = {
            'deploy': None, # self.deploy_callback,
            # disabled because it trigers a doble load when called from editor
            'load': self.deploy_project,
            'loadcue': None, # self.load_cue,
            'go': self.go_script,
            'gocue': None, # self.go_cue_callback,
            # 'hwdiscovery': None, # self.hw_discovery_callback,
            'pause': None, # self.pause_callback,
            'preload': None, # self.load_cue_callback,
            'resetall': None, # self.reset_all_callback,
            'stop': None, # self.stop_callback,
            'test': None, # self.test_callback
            'unload': None, # self.unload_cue_callback,
            'update': self.set_oscquery_bridge # Rebuilds client connections
        }
        endpoints = add_callbacks_from_dict(
            ENGINE_CMD_ENDPOINTS,
            cmd_dict
        )
        self.oscquery_server.create_endpoints(endpoints)

    def set_oscquery_values(self, values: dict):
        for key, value in values.items():
            self.oscquery_server.set_value(key, value)

    def set_oscquery_bridge(self, host = None):
        Logger.info(
            "Oscquery bridge for Controller starting"
        )
        # Start a client to each NodeEngine
        if not host:
            hosts = self.find_hosts()
        if not isinstance(host, list):
            hosts = [str(host)]
        else:
            hosts = [str(host) for host in host]
        for host in hosts:
            client = self.set_oscquery_client(
                port = NODE_ENGINE_PORT,
                host = host
            )
            # Register the NodeEngines in the OSCQuery server
            self.mirror_nodes_on_controller(client)
            client.add_node_creation_callback(self.node_creation_callback)

    def node_creation_callback(self, node):
        Logger.debug(f'Node creation callback received with {str(node)}')
        node_dict = {str(node): node}
        self.oscquery_server.add_endpoints(add_prefix_to_all(node_dict, '/node'))

        



    def mirror_nodes_on_controller(self, client):
        """Mirror the nodes from the NodeEngines to the Controller"""
        # Set the callbacks client for the nodes
        Logger.debug(f'Mirroring nodes from {client} to the Controller')
        endpoints = client.get_endpoints()
        self.oscquery_server.add_endpoints(add_prefix_to_all(endpoints, '/node'))
        Logger.debug(f'Altered endpoints: {client.get_endpoints()}')


    #########################
    # Project management
    #########################

    def load_project(self, project_name, context=None, deploy_only=False):
        if self.get_status('load') == project_name:
            Logger.info(f'Project {project_name} already loaded')
            return True

        Logger.info(f'Loading project {project_name}')
        self.reset_script()
        self.stop_timecode()
        
        if deploy_only:
            self.oscquery_server.set_value('/engine/command/deploy', project_name)
            return True
        
        try:
            self.cm.load_project_config(project_name)
        except Exception as e:
            Logger.error(f'Error loading project config: {e}')
            
            self.set_editor_request('')
            self.error_to_editor( context, 
                f"Project config error: {e}",
                action='project_ready'
            )

        try:
            self.read_script(project_name)
        except Exception as e:
            Logger.error(f'Error loading project script: {e}')
            
            self.set_editor_request('')
            self.error_to_editor(context, 
                f"Project script error: {e}",
                action='project_ready'
            )

        Logger.info(f'Script from {project_name} loaded')
        self.script.unix_name = project_name
        # self.set_status('load', project_name)

        self.set_oscquery_values({
            '/engine/status/load': project_name,
            '/engine/command/load': project_name
        })

        # Confirm the project is loaded
        self.set_show_lock_file()
        self.set_editor_request('')
        Logger.info(f'Project {project_name} loaded')
        return True

    def deploy_project(self, project_name):
        self.load_project(project_name)

    def go_script(self, value):
        if self.get_status('running') == "yes":
            Logger.info(f'Script {type(value)} already running.')
            return

        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return
        self.start_timecode()
        self.set_oscquery_values({
            # '/engine/status/go': value,
            '/engine/status/running': "yes",
            '/engine/command/gocue': "yes"
            # '/engine/command/go': value
        })

    def start_timecode(self):
        libmtcmaster.MTCSender_play(self.mtcmaster)
        print("MTC master started playing.")

    def stop_timecode(self):
        libmtcmaster.MTCSender_stop(self.mtcmaster)
        print("MTC master stopped playing.")
