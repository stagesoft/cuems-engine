import asyncio
from functools import partial

from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine, NODE_ENGINE_PORT, CONTROLLER_HOST
from .tools.communicate import ControllerCommunications
from .osc import ENGINE_CMD_ENDPOINTS
from .osc.helpers import add_callbacks_from_dict, add_callback_to_all, add_prefix_to_all
from .tools.mtcmaster import libmtcmaster
from .tools.PortHandler import PORT_HANDLER


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
        
        # Get OSC hub host from ConfigManager or use default
        if hasattr(self, 'cm') and self.cm:
            osc_hub_host = self.cm.controller_url
        else:
            osc_hub_host = CONTROLLER_HOST
        
        # Get dynamic port from PORT_HANDLER
        osc_hub_port = PORT_HANDLER.new_random_port()
        osc_hub_address = f"tcp://{osc_hub_host}:{osc_hub_port}"
        
        Logger.info(f'OSC Hub address: {osc_hub_address}')
        
        self.communications_thread = ControllerCommunications(
            osc_hub_address=osc_hub_address,
            editor_callback=self.editor_command_callback,
            osc_player_callback=self.osc_player_received_callback
        )
        self.communications_thread.start()

    def osc_player_received_callback(self, sender: str, player_id: str, node_data: dict, action):
        """
        Callback invoked when players are received from nodes.
        
        Parameters:
        - sender: ID of the node sending the player
        - player_id: Unique identifier for the player
        - node_data: Dictionary containing OSC node structure (None for REMOVE)
        - action: ActionType (ADD, UPDATE, or REMOVE)
        """
        Logger.info(f'Received player operation from {sender}: {action.value} {player_id}')
        # TODO: Implement player management logic
        # For now, just log the received player information
        if node_data:
            Logger.debug(f'Player {player_id} data: {node_data}')

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

    def editor_command_callback(self, item: dict, context):
        Logger.debug(f'Received editor command: {item}, with context: {context}')
        _item_keys = item.keys()
        if 'value' not in _item_keys:
            item['value'] = ''
        if 'action_uuid' not in _item_keys:
            self.error_to_editor(context, "No action uuid submitted")
        self.set_editor_request(item['action_uuid'])

        if 'type' in _item_keys:
            if item['type'] not in ['error', 'initial_settings']:
                
                self.set_editor_request('')
            self.error_to_editor(context, "Response not recognized")

        try:
            self.handle_editor_command(
                action = item['action'],
                value = item['value'], 
                context = context
            ) 
        except Exception as e:
            Logger.error(f'{type(e)} handling editor command: {e}')
            
            self.set_editor_request('')
            self.error_to_editor(context, value=f"Command {type(e)}: {e}")

    def handle_editor_command(self, action, value, context=None):
        command_dict = {
            'project_deploy': partial(self.load_project, deploy_only=True),
            'project_ready': self.load_project,
            'hw_discovery': self.hwdiscovery,
            'nodeconf': self.nodeconf,
            'go_script': self.go_script
        }
        if action in command_dict.keys():
            success  = command_dict[action](value, context)
            if success:
                self.confirm_to_editor(
                    context, type=action, value='OK'
                )
            
        else:
            raise ValueError(f'Command {action} not recognized')
        
    def confirm_to_editor(self, context, type=None, value=None):
        return_message={
            'type': type,
            'value': value,
            'action_uuid': self.get_editor_request()
        }
        Logger.debug(f'Sending confirm to editor: {return_message}')

        try:
            self.communications_thread.reply_to_editor(return_message, context)
        except Exception as e:
            Logger.error(f'{type(e)} confirming to editor: {e}')

    def error_to_editor(self, context, value=None, request_uuid = None, action = None):
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
        try:
            self.communications_thread.reply_to_editor(return_message, context)
        except Exception as e:
            Logger.error(f'{type(e)} sending error to editor: {e}')
        
    
    def set_editor_request(self, value):
        self._editor_request_uuid = value

    def get_editor_request(self):
        return self._editor_request_uuid


    #########################
    # External services
    #########################

    def hwdiscovery(self, message: dict, context=None) -> bool:
        Logger.debug(f'sending HW discovery request: {message}')
        try:
            reply = self.communications_thread.request_to_hwdiscovery(message)
            Logger.debug(f'Received HW discovery reply: {reply}')
            if 'OK' in reply.values():
                return True
            else:
                return False            
        except Exception as e:
            Logger.error(f'{type(e)} sending HW discovery request: {e}')
            return False

    def nodeconf(self, message: dict, context=None) -> bool:
        Logger.debug(f'sending nodeconf request: {message}')
        try:
            reply = self.communications_thread.request_to_nodeconf(message)
            Logger.debug(f'Received nodeconf reply: {reply}')
            if 'OK' in reply.values():
                return True
            else:
                return False            
        except Exception as e:
            Logger.error(f'{type(e)} sending nodeconf request: {e}')
            return False


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
            # '/engine/command/gocue': "yes"
            # '/engine/command/go': value
        })


        # CUE LOGIC BETWEEN CONTROLLER AND NODES
        # Send the go command to the nodes
        self.communications_thread.send_go_command(value)

        # Wait for the nodes to confirm the end of the script
        self.communications_thread.wait_for_nodes_to_finish()
        # Stop the timecode
        self.stop_timecode()
        # Set the oscquery values
        self.set_oscquery_values({
            '/engine/status/running': "no",
            # '/engine/command/gocue': "no"
        })

        # Confirm the script is stopped
        return True

    def start_timecode(self):
        libmtcmaster.MTCSender_play(self.mtcmaster)
        print("MTC master started playing.")

    def stop_timecode(self):
        libmtcmaster.MTCSender_stop(self.mtcmaster)
        print("MTC master stopped playing.")
