import asyncio
from functools import partial
import threading
import time

from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine, NODE_ENGINE_PORT, CONTROLLER_HOST
from .core.libmtc import libmtcmaster
from .comms.ControllerCommunications import ControllerCommunications
from .comms.NodesHub import NodeOperation, ActionType, OperationType
from .osc import ENGINE_CMD_ENDPOINTS, PLAYERS_ENDPOINTS_DICT
from .osc.helpers import add_callbacks_from_dict, add_callback_to_all, add_prefix_to_all
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
        self.set_node_operation_callback()

        # Command polling: checks OSCQuery endpoints for value changes
        # Note: Direct callbacks disabled due to pyossia GIL threading issues
        self._command_poll_thread = None
        self._command_poll_stop = threading.Event()
        self._last_command_values = {}

    def start(self):
        self.create_timecode()
        self.set_comms()
        self.start_command_polling()
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
        nng_hub_address = f"tcp://{osc_hub_host}:{osc_hub_port}"
        
        Logger.info(f'NNG Hub address: {nng_hub_address}')
        
        self.communications_thread = ControllerCommunications(
            nng_hub_address=nng_hub_address,
            editor_callback=self.editor_command_callback,
            node_operation_callback=self.node_operation_callback
        )
        self.communications_thread.start()

    def stop(self):
        self.stop_command_polling()
        self.stop_comms()
        super().stop()

    @logged
    def stop_comms(self):
        if self.with_mtc:
            self.stop_timecode()
        if hasattr(self, 'communications_thread'):
            self.communications_thread.stop()
        if hasattr(self, 'oscquery_server'):
            self.oscquery_server.remove_device()

    def start_command_polling(self):
        """Start the command polling thread"""
        if not self._command_poll_thread or not self._command_poll_thread.is_alive():
            Logger.info("Starting command polling thread")
            self._command_poll_stop.clear()
            self._command_poll_thread = threading.Thread(
                target=self._command_poll_loop,
                name="CommandPollThread",
                daemon=True
            )
            self._command_poll_thread.start()

    def stop_command_polling(self):
        """Stop the command polling thread"""
        if self._command_poll_thread and self._command_poll_thread.is_alive():
            Logger.info("Stopping command polling thread")
            self._command_poll_stop.set()
            timeout = 0.5  # 500ms timeout
            self._command_poll_thread.join(timeout=timeout)
            if self._command_poll_thread.is_alive():
                Logger.warning("Command polling thread did not terminate gracefully")

    def _command_poll_loop(self):
        """Poll OSCQuery command endpoints for value changes"""
        # Map command paths to handler methods
        command_handlers = {
            '/engine/command/go': self.go_script,
            '/engine/command/load': self.deploy_project,
        }

        poll_interval = 0.1  # 100ms polling interval
        Logger.info("Command polling loop started")

        while not self._command_poll_stop.wait(poll_interval):
            try:
                if not hasattr(self, 'oscquery_server') or not self.oscquery_server:
                    continue

                for cmd_path, handler in command_handlers.items():
                    try:
                        # Check if node exists
                        if cmd_path not in self.oscquery_server.nodes:
                            continue

                        # Get current value
                        node = self.oscquery_server.nodes[cmd_path]
                        current_value = node.parameter.value
                        last_value = self._last_command_values.get(cmd_path)

                        # Trigger on value change AND non-empty value
                        if current_value != last_value and current_value:
                            Logger.info(f"Command detected: {cmd_path} = {repr(current_value)}")
                            self._last_command_values[cmd_path] = current_value

                            # Execute handler
                            try:
                                handler(current_value)
                            except Exception as e:
                                Logger.error(f"Error executing {cmd_path}: {e}", exc_info=True)

                            # Reset value to allow re-triggering
                            try:
                                node.parameter.push_value("")
                                self._last_command_values[cmd_path] = ""
                            except Exception as e:
                                Logger.warning(f"Could not reset {cmd_path}: {e}")

                    except Exception as e:
                        Logger.error(f"Error polling {cmd_path}: {e}")

            except Exception as e:
                Logger.error(f"Error in command poll loop: {e}", exc_info=True)
                time.sleep(1.0)  # Back off on error

    #########################
    # Timecode
    #########################
    def create_timecode(self):
        if self.with_mtc:
            self.mtcmaster = libmtcmaster.MTCSender_create()
        else:
            Logger.info("Midi TimeCode requires with_mtc to be True.")

    def start_timecode(self):
        if self.with_mtc:
            libmtcmaster.MTCSender_play(self.mtcmaster)
            Logger.info("Midi TimeCode started.")
        else:
            Logger.info("Midi TimeCode requires with_mtc to be True.")

    def stop_timecode(self):
        if self.with_mtc:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            Logger.info("Midi TimeCode stopped.")
        else:
            Logger.info("Midi TimeCode requires with_mtc to be True.")


    #########################
    # Operation callbacks
    #########################
    def set_node_operation_callback(self):
        self.node_operation_callback = {
            OperationType.PLAYER: self.player_operation_callback,
            OperationType.CUE: self.cue_operation_callback
        }

    def player_operation_callback(self, operation: NodeOperation):
        """
        Callback invoked when players are received from nodes.
        
        Parameters:
        - sender: ID of the node sending the player
        - player_id: Unique identifier for the player
        - node_data: Dictionary containing OSC node structure (None for REMOVE)
        - action: ActionType (ADD, UPDATE, or REMOVE)
        """
        Logger.info(f'Received {operation}')
        
        if operation.action == ActionType.ADD:
            self.add_player_oscquery_nodes(operation)
        elif operation.action == ActionType.REMOVE:
            self.remove_player_oscquery_nodes(operation)
        else:
            Logger.warning(f'Unknown player action: {operation.action}')

    def add_player_oscquery_nodes(self, operation: NodeOperation):
        """Add the player nodes to the local OSCQuery server"""
        common_path = self.build_player_oscquery_path(operation)
        if not common_path:
            Logger.warning(f'Player path returned None, skipping addition')
            return
        node_data = self.endpoints_from_player_path(common_path)
        if not node_data:
            Logger.warning(f'Player endpoints returned None, skipping addition')
            return
        if hasattr(self, 'oscquery_server') and self.oscquery_server:
            self.oscquery_server.add_endpoints(node_data)
        else:
            Logger.warning("OSCQuery server not initialized, cannot add player endpoints")

    def remove_player_oscquery_nodes(self, operation: NodeOperation):
        """Remove the player nodes from the local OSCQuery server"""
        common_path = self.build_player_oscquery_path(operation)
        if not common_path:
            Logger.warning(f'Player path returned None, skipping removal')
            return
        # Filter for cue-specific players
        if '/cue/' not in common_path:
            Logger.warning(f'Player {operation.target} is not a cue-specific player, skipping removal')
            return
        if hasattr(self, 'oscquery_server') and self.oscquery_server:
            self.oscquery_server.remove_node(common_path)
        else:
            Logger.warning("OSCQuery server not initialized, cannot remove player nodes")

    def build_player_oscquery_path(self, operation: NodeOperation) -> str | None:
        """Build the player OSCQuery path"""
        ptype, id = operation.target.split('_')
        common_path = f'/engine/players/{operation.sender}/'
        if ptype == 'audioplayer':
            common_path += f'audio/cue/{id}/'
        elif ptype == 'audiomixer':
            common_path += f'audio/mixer/{id}/'
        elif ptype == 'videoplayer':
            common_path += f'video/mixer/{id}/'
        elif ptype == 'dmxplayer':
            common_path += f'dmx/mixer/{id}/'
        else:
            Logger.warning(f'Unknown player type: {ptype}')
            return None
        return common_path

    def endpoints_from_player_path(self, path: str) -> dict:
        """Build the player OSCQuery endpoints"""
        endpoints = {}
        for key, value in PLAYERS_ENDPOINTS_DICT.items():
            if key in path:
                endpoints.update(value)
        add_prefix_to_all(endpoints, path)
        return endpoints

    def cue_operation_callback(self, operation: NodeOperation):
        """Callback invoked when cues are received from nodes."""
        Logger.info(f'Received {operation}')
        if operation.action == ActionType.ADD:
            self.add_cue_oscquery_nodes(operation)
        elif operation.action == ActionType.REMOVE:
            self.remove_cue_oscquery_nodes(operation)
        else:
            Logger.warning(f'Unknown cue action: {operation.action}')

    def add_cue_oscquery_nodes(self, operation: NodeOperation):
        """Add the running cues information to the local OSCQuery server one by one.

        Publishes the updated currentcue information to the local OSCQuery server after each addition.

        Args:
            operation: NodeOperation object containing the cue information inside the data dictionary
                - id: ID of the cue
                - offset: Offset of the cue

        Returns:
            None

        Raises:
            Exception: If an error occurs while adding the cue to the current cue
        """
        try:
            self.status.currentcue = [operation.data['id'], operation.data['offset']]
        except Exception as e:
            Logger.error(f'Error adding to currentcue {operation.data["id"]}: {e}')
            return
        self.set_oscquery_values({
            '/engine/status/currentcue': self.status.currentcue
        })

    def remove_cue_oscquery_nodes(self, operation: NodeOperation):
        """Remove the cue from running cues information from the local OSCQuery server"""
        self.status.remove_currentcue(operation.data['id'])
        self.set_oscquery_values({
            '/engine/status/currentcue': self.status.currentcue
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
            
            request_uuid = self.get_editor_request()
            self.set_editor_request('')
            self.error_to_editor(context, value=f"Command {type(e)}: {e}", request_uuid=request_uuid)

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
                # Clear the editor request after successful confirmation
                self.set_editor_request('')
            
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
        return_message={
            'type': 'error',
            'value': value,
            'action_uuid': request_uuid
        }
        if action:
            return_message['action'] = action
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
        status_endpoints = self.get_status_endpoints()
        Logger.debug(f"Creating OSCQuery server with {len(status_endpoints)} status endpoints: {list(status_endpoints.keys())}")
        self.set_oscquery_server(status_endpoints)
        Logger.debug(f"OSCQuery server created with nodes: {list(self.oscquery_server.nodes.keys())}")
        self.apply_oscquery_commands()
        Logger.debug(f"After applying commands, OSCQuery server has nodes: {list(self.oscquery_server.nodes.keys())}")

    def apply_oscquery_commands(self):
        """
        Register OSCQuery command endpoints.

        Note: All callbacks are set to None due to pyossia threading issues.
        The library invokes callbacks from C++ threads without acquiring Python's GIL,
        causing crashes. Commands are instead handled via polling (_command_poll_loop).
        """
        cmd_dict = {
            'deploy': None,    # Handled via Editor NNG ReqRep
            'load': None,      # Polled by _command_poll_loop
            'loadcue': None,
            'go': None,        # Polled by _command_poll_loop
            'gocue': None,
            # 'hwdiscovery': None,
            'pause': None,
            'preload': None,
            'resetall': None,
            'stop': None,
            'test': None,
            'unload': None,
            'update': None,    # Handled via NNG Hub
        }
        endpoints = add_callbacks_from_dict(
            ENGINE_CMD_ENDPOINTS,
            cmd_dict
        )
        if hasattr(self, 'oscquery_server') and self.oscquery_server:
            self.oscquery_server.create_endpoints(endpoints)
        else:
            Logger.error("OSCQuery server not initialized in apply_oscquery_commands")

    def set_oscquery_values(self, values: dict):
        if not hasattr(self, 'oscquery_server') or not self.oscquery_server:
            Logger.warning("OSCQuery server not initialized, cannot set values")
            return
        for key, value in values.items():
            try:
                self.oscquery_server.set_value(key, value)
            except ValueError as e:
                Logger.warning(f"Could not set OSCQuery value {key}={value}: {e}")
                Logger.debug(f"Available OSCQuery nodes: {list(self.oscquery_server.nodes.keys())}")

    def on_timecode_change(self, value: str) -> None:
        Logger.debug(f'Timecode changed to {value}')
        if self.go_offset:
            self.set_oscquery_values({
                '/engine/status/timecode': value
            })

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
            if hasattr(self, 'oscquery_server') and self.oscquery_server:
                try:
                    self.oscquery_server.set_value('/engine/command/deploy', project_name)
                except ValueError as e:
                    Logger.warning(f"Could not set deploy command in OSCQuery: {e}")
            return True
        
        try:
            self.cm.load_project_config(project_name)
        except Exception as e:
            Logger.error(f'Error loading project config: {e}')
            
            request_uuid = self.get_editor_request()
            self.set_editor_request('')
            self.error_to_editor(context, 
                f"Project config error: {e}",
                request_uuid=request_uuid,
                action='project_ready'
            )
            return False

        try:
            self.read_script(project_name)
        except Exception as e:
            Logger.error(f'Error loading project script: {e}')
            
            request_uuid = self.get_editor_request()
            self.set_editor_request('')
            self.error_to_editor(context, 
                f"Project script error: {e}",
                request_uuid=request_uuid,
                action='project_ready'
            )
            return False

        Logger.info(f'Script from {project_name} loaded')
        self.script.unix_name = project_name
        # self.set_status('load', project_name)

        self.set_oscquery_values({
            '/engine/status/load': project_name,
            '/engine/command/load': project_name
        })

        # Confirm the project is loaded
        self.set_show_lock_file()
        Logger.info(f'Project {project_name} loaded')
        # Note: Don't clear editor_request here - handle_editor_command will clear it after confirmation
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
        
        # Update status only - do not set command node to avoid callback loop
        # External clients set /engine/command/go which triggers this callback
        # This callback should only update status nodes, not command nodes
        self.set_oscquery_values({
            '/engine/status/running': "yes"
        })
        
        Logger.info(f'GO command sent via OSCQuery: {value}')
        
        # Note: In a full implementation, we would wait for nodes to signal completion
        # For now, this is a fire-and-forget command
        
        return True
