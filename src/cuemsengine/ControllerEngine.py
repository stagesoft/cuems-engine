import asyncio
import time
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
    # Controller→UI WebSocket throttle for cue percentage updates.
    # State transitions (0, 1, 100) always bypass this and broadcast immediately.
    # Only in-progress percentage values (2-99) are throttled.
    # Two-tier throttle: Tier 1 is node-side (CUE_STATUS_UPDATE_HZ in loop_cue.py);
    # Tier 2 is here, capping WS broadcasts even when multiple nodes send updates
    # in quick succession.
    CUE_BROADCAST_MIN_INTERVAL = 0.25  # seconds — max 4 Hz to UI per cue

    def __init__(self, **kwargs):
        # Must be set before super().__init__() because BaseEngine sets
        # self.timecode = None which triggers on_timecode_change() via the
        # property setter, and that method reads these attributes.
        self._last_timecode_broadcast = 0.0
        self._timecode_broadcast_interval = 0.5  # 2 Hz max for timecode , for 20mhz set it to 0.05
        # Per-cue status dict: maps cue uuid → int status value.
        # Values: 0=unplayed, 1-99=playing (1 until percentage enabled), 100=played, -1=error
        self.cue_status: dict[str, int] = {}
        # Per-cue last-broadcast timestamps for WS throttle (Tier 2).
        self._cue_broadcast_timestamps: dict[str, float] = {}
        super().__init__(**kwargs)
        self.set_editor_request('')
        self.set_node_operation_callback()

    def start(self):
        self.create_timecode()
        self.set_comms()
        # HEADLESS/CLOUD: on servers without hardware MIDI the port list is
        # empty at __init__ time.  create_timecode() above creates the virtual
        # ALSA sender port, so we retry detection here to pick it up.
        if self.mtc_listener.port_name is None:
            Logger.info('Re-detecting MIDI port after MTC sender creation...')
            self.mtc_listener._MtcListener__open_port(None)
        self.mtc_listener.start()
        super().start()

    def set_status(self, property: str, value: str, strict: bool = False) -> None:
        """Set status and push to UI via WebSocket when running, armed, or load."""
        super().set_status(property, value, strict)
        if property in ('running', 'armed', 'load'):
            self._broadcast_status(property, value)
    
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
            '/engine/command/go', self.go_script, forward_to_nodes=False
        )
        self.communications_thread.register_command_handler(
            '/engine/command/load', self.deploy_project, forward_to_nodes=False
        )
        self.communications_thread.register_command_handler(
            '/engine/command/stop', self.stop_script, forward_to_nodes=False
        )
        
        # Register wildcard handler for player messages (engine format)
        self.communications_thread.register_osc_handler(
            '/engine/players/*', self._handle_player_osc_message
        )
        
        # Register handler for direct node/player messages from UI
        # UI sends: /<node_uuid>/audiomixer/<channel> or /<node_uuid>/jadeo/<cmd>
        # We need to catch these and forward to NodeEngine
        node_uuid = self.cm.node_conf.get('uuid', '') if hasattr(self, 'cm') and self.cm else ''
        if node_uuid:
            self.communications_thread.register_osc_handler(
                f'/{node_uuid}/*', self._handle_direct_player_osc_message
            )
            Logger.info(f"Registered direct player OSC handler for /{node_uuid}/*")
        
        Logger.info("OSC command handlers registered for WebSocket receiving")
    
    def _handle_direct_player_osc_message(self, address: str, args: list):
        """Handle direct player OSC messages from UI (/<node_uuid>/<type>/...).
        
        These are forwarded directly to the local node's player handlers.
        """
        value = args[0] if args else None
        
        # Parse: /<node_uuid>/<type>/<...>
        parts = address.strip('/').split('/')
        if len(parts) < 2:
            Logger.warning(f"Invalid direct player OSC address: {address}")
            return
        
        # parts[0] is node_uuid, parts[1] is type (audiomixer, jadeo, etc.)
        player_type = parts[1]
        
        Logger.debug(f"Direct player OSC: {address} = {repr(value)}")
        
        # Forward to NodeEngine via NNG as player_control
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
            Logger.debug(f"Forwarded direct player OSC to nodes: {address} = {repr(value)}")
        except Exception as e:
            Logger.error(f"Error forwarding direct player OSC to nodes: {e}")
    
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

    def _forward_load_to_nodes(self, project_name: str) -> None:
        """Forward a load command to NodeEngine via NNG."""
        self._forward_command_to_nodes('/engine/command/load', project_name)

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
            OperationType.CUE: self.cue_operation_callback,
            OperationType.STATUS: self.status_operation_callback
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

        Handles three action types:
        - ADD:    cue started playing on a node → status 1, broadcast immediately
        - REMOVE: cue finished playing on a node → status 100, broadcast immediately
        - UPDATE: percentage progress from a node (future) → throttled broadcast
        """
        Logger.info(f'Cue operation received: {operation}')
        cue_id = operation.data.get('id') if operation.data else None

        if operation.action == ActionType.ADD:
            # Cue started playing: mark as playing (1) and broadcast immediately.
            if cue_id:
                self.cue_status[cue_id] = 1
                self._broadcast_cue_status(cue_id, 1, force=True)
            try:
                self.status.currentcue = [operation.data['id'], operation.data['offset']]
                Logger.debug(f"Current cue updated: {self.status.currentcue}")
            except Exception as e:
                Logger.error(f'Error updating currentcue: {e}')

        elif operation.action == ActionType.REMOVE:
            # Cue finished playing: mark as played (100) and broadcast immediately.
            if cue_id:
                self.cue_status[cue_id] = 100
                self._broadcast_cue_status(cue_id, 100, force=True)
            self.status.remove_currentcue(operation.data['id'])
            Logger.debug(f"Cue removed from currentcue: {operation.data['id']}")

        elif operation.action == ActionType.UPDATE:
            # Future: percentage progress updates from loop_cue() during playback.
            # Throttled by _broadcast_cue_status (Tier 2 / controller-side).
            # The node-side Tier 1 throttle (CUE_STATUS_UPDATE_HZ) limits NNG traffic.
            if cue_id:
                pct = operation.data.get('percentage', 1)
                self.cue_status[cue_id] = pct
                self._broadcast_cue_status(cue_id, pct)  # throttled
            Logger.debug(f"Cue percentage update: {cue_id} = {operation.data.get('percentage')}")

        else:
            Logger.warning(f'Unknown cue action: {operation.action}')

    def status_operation_callback(self, operation: NodeOperation):
        """Callback invoked when status updates are received from nodes.
        
        Handles script_finished and armed_ready notifications.
        """
        Logger.info(f'Status operation received: {operation}')
        if operation.target == 'script_finished':
            if operation.data and operation.data.get('running') == 'no':
                Logger.info('Script finished notification received from node - updating running status')
                self.set_status('running', 'no')
        elif operation.target == 'armed_ready':
            if operation.data and operation.data.get('armed') == 'yes':
                Logger.info('Re-arm complete from node - GO available')
                self.set_status('armed', 'yes')
        else:
            Logger.debug(f'Unknown status target: {operation.target}')

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

    def _collect_cue_ids(self, cuelist) -> list[str]:
        """Recursively collect all cue IDs from a cuelist (including nested CueLists)."""
        from cuemsutils.cues import CueList
        ids = []
        if hasattr(cuelist, 'contents') and cuelist.contents:
            for item in cuelist.contents:
                if item is None:
                    continue
                ids.append(item.id)
                if isinstance(item, CueList):
                    ids.extend(self._collect_cue_ids(item))
        return ids

    def _broadcast_cue_status(self, cue_id: str, value: int, force: bool = False) -> None:
        """Broadcast per-cue status to UI via WebSocket OSC at /engine/status/cue/{uuid}.

        Values: 0=unplayed, 1-99=playing (1 until percentage is enabled), 100=played, -1=error.

        State transitions (force=True: values 0, 1, 100) bypass throttle and broadcast
        immediately. In-progress percentage updates (2-99) are throttled per-cue to
        CUE_BROADCAST_MIN_INTERVAL to limit WS traffic even when multiple remote nodes
        send updates in quick succession (Tier 2 of the two-tier throttle strategy).
        """
        if not force:
            now = time.monotonic()
            last = self._cue_broadcast_timestamps.get(cue_id, 0)
            if now - last < self.CUE_BROADCAST_MIN_INTERVAL:
                return
            self._cue_broadcast_timestamps[cue_id] = now
        if hasattr(self, 'communications_thread') and self.communications_thread \
                and hasattr(self.communications_thread, 'broadcast_osc'):
            self.communications_thread.broadcast_osc(f'/engine/status/cue/{cue_id}', value)

    def _broadcast_status(self, key: str, value) -> None:
        """Push status to UI via WebSocket OSC (realtime)."""
        if hasattr(self, 'communications_thread') and self.communications_thread and hasattr(self.communications_thread, 'broadcast_osc'):
            self.communications_thread.broadcast_osc(f'/engine/status/{key}', value)

    def on_timecode_change(self, value: str) -> None:
        """Handle timecode changes - broadcast to UI (throttled to 20 Hz)."""
        now = time.monotonic()
        if now - self._last_timecode_broadcast >= self._timecode_broadcast_interval:
            self._last_timecode_broadcast = now
            try:
                tc_int = int(value) if value is not None else 0
                self._broadcast_status('timecode', tc_int)
                Logger.debug(f'Timecode broadcast {tc_int}')
            except (TypeError, ValueError):
                pass

    #########################
    # Project management
    #########################

    def load_project(self, project_name, context=None, deploy_only=False):
        # Don't allow loading while script is running
        if self.get_status('running') == "yes":
            Logger.warning(f'Cannot load project {project_name} while script is running. Stop first.')
            return False

        Logger.info(f'Loading project {project_name}')
        self.set_status('armed', 'no')
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

        # Initialise per-cue status: every cue starts as unplayed (0).
        # Broadcasts one WS message per cue so the UI can populate its cue list.
        self.cue_status = {cid: 0 for cid in self._collect_cue_ids(self.script.cuelist)}
        self._cue_broadcast_timestamps.clear()
        for cid in self.cue_status:
            self._broadcast_cue_status(cid, 0, force=True)
        Logger.info(f'Cue status initialised for {len(self.cue_status)} cues')

        # Update internal status
        self.set_status('load', project_name)

        # Forward load command to NodeEngine via NNG (nodes will arm cues)
        self._forward_load_to_nodes(project_name)

        # Timecode starts on load; runs until next load or engine shutdown
        self.start_timecode()
        self.go_offset = 0  # Enable mtc_callback → on_timecode_change → broadcast
        # armed=yes is NOT set here -- it's set when NodeEngine reports armed_ready
        # via status_operation_callback, ensuring cues are actually armed before
        # the UI shows GO as available

        # Confirm the project is loaded
        self.set_show_lock_file()
        Logger.info(f'Project {project_name} loaded')
        # Note: Don't clear editor_request here - handle_editor_command will clear it after confirmation
        return True

    def deploy_project(self, project_name):
        self.load_project(project_name)

    def go_script(self, value, context=None):
        if self.get_status('armed') != "yes":
            Logger.warning('Cues not armed. GO not available.')
            return

        if not self.script:
            Logger.warning('No script loaded, cannot process GO command.')
            return
        
        self.set_status('running', "yes")

        # Forward GO to NodeEngine via NNG (needed when called from editor;
        # when called from WebSocket the comms layer also forwards, but the
        # NodeEngine's run_command is idempotent so a double-call is harmless)
        self._forward_command_to_nodes('/engine/command/go', value)

        Logger.info(f'GO command processed')
        return True

    def _forward_command_to_nodes(self, address: str, value) -> None:
        """Forward a generic command to NodeEngine via NNG."""
        if not hasattr(self, 'communications_thread') or not self.communications_thread:
            Logger.warning("Cannot forward command to nodes: communications thread not available")
            return

        parts = address.strip('/').split('/')
        command_name = parts[-1] if parts else address

        operation = NodeOperation(
            type=OperationType.COMMAND,
            action=ActionType.UPDATE,
            sender=self.cm.node_conf.get('uuid', 'controller') if hasattr(self, 'cm') and self.cm else 'controller',
            target=command_name,
            data={'value': value, 'address': address}
        )

        try:
            asyncio.run_coroutine_threadsafe(
                self.communications_thread.nng_hub.send_operation(operation),
                self.communications_thread.event_loop
            )
            Logger.debug(f"Forwarded command to nodes: {command_name} = {repr(value)}")
        except Exception as e:
            Logger.error(f"Error forwarding command to nodes: {e}")

    def stop_script(self, value):
        """Handle STOP command - stop timecode, update status and forward to nodes."""
        if self.get_status('running') != "yes":
            Logger.info('Script not running, nothing to stop.')
            return

        self.go_offset = None
        self.stop_timecode()
        self._broadcast_status('timecode', 0)

        self.set_status('running', "no")
        self.set_status('armed', 'no')

        # Reset all cue statuses to unplayed (0) and broadcast to UI.
        for cid in self.cue_status:
            self.cue_status[cid] = 0
            self._broadcast_cue_status(cid, 0, force=True)
        self._cue_broadcast_timestamps.clear()

        self._forward_command_to_nodes('/engine/command/stop', value)

        Logger.info('STOP command processed - timecode stopped; nodes will re-arm')
        return True
