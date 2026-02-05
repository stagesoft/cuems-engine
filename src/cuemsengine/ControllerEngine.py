import asyncio
from functools import partial

from cuemsutils.log import Logger, logged

from .core.BaseEngine import BaseEngine, NODE_ENGINE_PORT, CONTROLLER_HOST
from .core.libmtc import libmtcmaster
from .comms.ControllerCommunications import ControllerCommunications
from .comms.NodesHub import NodeOperation, ActionType, OperationType


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

    def start(self):
        self.create_timecode()
        self.set_comms()
        super().start()
    
    @logged
    def set_comms(self):
        # Start communicators with WebSocket handler on port 9190
        self.set_communicators()

    def set_communicators(self):
        Logger.info('Setting up Communicators')
        
        # Get OSC hub host from ConfigManager or use default
        if hasattr(self, 'cm') and self.cm:
            osc_hub_host = self.cm.controller_url
        else:
            osc_hub_host = CONTROLLER_HOST
        
        # Get NNG hub port from config (must match NodeEngine)
        if hasattr(self, 'cm') and self.cm and hasattr(self.cm, 'node_conf'):
            nng_hub_port = self.cm.node_conf.get('nng_hub_port', 9093)
            # Use port 9190 for WebSocket OSC - we start BEFORE pyossia to claim this port
            # This allows UI to send commands via Apache's /realtime proxy to ws://127.0.0.1:9190
            websocket_osc_port = self.cm.node_conf.get('oscquery_ws_port', 9190)
            node_id = self.cm.node_conf.get('uuid', 'controller')
        else:
            nng_hub_port = 9093
            websocket_osc_port = 9190  # Take port 9190 for WebSocket OSC
            node_id = 'controller'
        
        nng_hub_address = f"tcp://{osc_hub_host}:{nng_hub_port}"
        
        Logger.info(f'NNG Hub address: {nng_hub_address}')
        
        # WebSocket OSC configuration for receiving commands from UI
        # Uses port 9190 (same as Apache /realtime proxy target) to receive
        # OSC commands directly. Started BEFORE pyossia to claim the port.
        websocket_osc_config = {
            'host': '0.0.0.0',
            'port': websocket_osc_port,
            'node_id': node_id
        }
        Logger.info(f'WebSocket OSC port: {websocket_osc_port}')
        
        self.communications_thread = ControllerCommunications(
            nng_hub_address=nng_hub_address,
            editor_callback=self.editor_command_callback,
            node_operation_callback=self.node_operation_callback,
            websocket_osc_config=websocket_osc_config
        )
        
        # Register command handlers for WebSocket OSC
        self._register_osc_command_handlers()
        
        self.communications_thread.start()
        
        # Wait for NNG thread to initialize (prevents race condition in nni_random)
        from time import sleep
        max_wait = 5.0  # seconds
        wait_interval = 0.1
        waited = 0.0
        while waited < max_wait:
            if (self.communications_thread.is_alive() and 
                self.communications_thread.event_loop is not None):
                Logger.info(f"NNG communications thread ready after {waited:.1f}s")
                break
            sleep(wait_interval)
            waited += wait_interval
        else:
            Logger.warning(f"NNG communications thread not ready after {max_wait}s")
    
    def _register_osc_command_handlers(self):
        """Register OSC command handlers for WebSocket OSC receiving.
        
        These handlers are called when commands are received from the UI via
        WebSocket OSC. Commands are also forwarded to NodeEngine via NNG.
        """
        # Command handlers - same as used in _command_poll_loop
        self.communications_thread.register_command_handler(
            '/engine/command/go', self.go_script, forward_to_nodes=True
        )
        self.communications_thread.register_command_handler(
            '/engine/command/load', self.deploy_project, forward_to_nodes=True
        )
        self.communications_thread.register_command_handler(
            '/engine/command/stop', self.stop_script, forward_to_nodes=True
        )
        
        # Register wildcard handler for player messages
        self.communications_thread.register_osc_handler(
            '/engine/players/*', self._handle_player_osc_message
        )
        
        Logger.info("OSC command handlers registered for WebSocket receiving")
    
    def _handle_player_osc_message(self, address: str, args: list):
        """Handle player-related OSC messages from UI.
        
        These are forwarded to NodeEngine via NNG for player control
        (video, audio mixer, DMX, etc.)
        """
        # Forward to NodeEngine via NNG
        value = args[0] if args else None
        
        # Create a COMMAND operation for player control
        operation = NodeOperation(
            type=OperationType.COMMAND,
            action=ActionType.UPDATE,
            sender=self.cm.node_conf.get('uuid', 'controller') if hasattr(self, 'cm') and self.cm else 'controller',
            target='player_control',
            data={'address': address, 'value': value}
        )
        
        try:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self.communications_thread.nng_hub.send_operation(operation),
                self.communications_thread.event_loop
            )
            Logger.debug(f"Forwarded player OSC to nodes: {address} = {repr(value)}")
        except Exception as e:
            Logger.error(f"Error forwarding player OSC to nodes: {e}")

    def stop(self):
        self.stop_comms()
        super().stop()

    @logged
    def stop_comms(self):
        if self.with_mtc:
            self.stop_timecode()
        if hasattr(self, 'communications_thread'):
            self.communications_thread.stop()

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
        - operation: NodeOperation with sender, target (player_id), and action
        """
        Logger.info(f'Player operation received: {operation}')

    def cue_operation_callback(self, operation: NodeOperation):
        """Callback invoked when cues are received from nodes.
        
        Updates internal status tracking for running cues.
        """
        Logger.info(f'Cue operation received: {operation}')
        if operation.action == ActionType.ADD:
            try:
                self.status.currentcue = [operation.data['id'], operation.data['offset']]
                Logger.debug(f"Current cue updated: {self.status.currentcue}")
            except Exception as e:
                Logger.error(f'Error updating currentcue: {e}')
        elif operation.action == ActionType.REMOVE:
            self.status.remove_currentcue(operation.data['id'])
            Logger.debug(f"Cue removed from currentcue: {operation.data['id']}")
        else:
            Logger.warning(f'Unknown cue action: {operation.action}')

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
    # Status Updates (stub - OSCQuery removed)
    #########################

    def set_oscquery_values(self, values: dict):
        """Stub for OSCQuery value setting - OSCQuery server has been removed.
        
        Status updates are now handled via internal state tracking.
        TODO: Implement WebSocket status push if UI needs real-time status.
        """
        for key, value in values.items():
            Logger.debug(f"Status update (no-op): {key} = {repr(value)}")

    def on_timecode_change(self, value: str) -> None:
        """Handle timecode changes - logs for now."""
        Logger.debug(f'Timecode changed to {value}')

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
            Logger.info(f"Deploy only requested for {project_name}")
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
        
        # Update internal status
        self.set_status('load', project_name)

        # Confirm the project is loaded
        self.set_show_lock_file()
        Logger.info(f'Project {project_name} loaded')
        # Note: Don't clear editor_request here - handle_editor_command will clear it after confirmation
        return True

    def deploy_project(self, project_name):
        self.load_project(project_name)

    def go_script(self, value):
        if self.get_status('running') == "yes":
            Logger.info(f'Script already running.')
            return

        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return
        
        self.start_timecode()
        
        # Update internal status
        self.set_status('running', "yes")
        
        Logger.info(f'GO command processed')
        return True

    def stop_script(self, value):
        """Handle STOP command - stop timecode and update status"""
        if self.get_status('running') != "yes":
            Logger.info('Script not running, nothing to stop.')
            return

        self.stop_timecode()
        
        # Update internal status
        self.set_status('running', "no")
        
        Logger.info('STOP command processed - ready for next GO')
        return True
