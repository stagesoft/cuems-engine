import asyncio
import math
import threading
import time
from functools import partial

from cuemsutils.log import Logger, logged
from cuemsutils.xml.Settings import NetworkMap

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
        self._last_timecode_second: int = -1  # last whole-second value broadcast to UI
        # Per-cue status dict: maps cue uuid → int status value.
        # Values: 0=unplayed, 1-99=playing (1 until percentage enabled), 100=played, -1=error
        self.cue_status: dict[str, int] = {}
        # Per-cue enabled status: maps cue uuid → bool.
        # Initialised from XML on load_project, updated by show-time toggles.
        # Resets to XML values on reload; persists across stop/go.
        self.cue_enabled_status: dict[str, bool] = {}
        # Per-cue last-broadcast timestamps for WS throttle (Tier 2).
        self._cue_broadcast_timestamps: dict[str, float] = {}
        # Per-mixer-channel volume state: maps "{node_uuid}/{output_index}/{channel}"
        # to float 0.0-1.0. Channel is "master" or a stringified index. Persists
        # across project loads; resets only on engine restart. All access is on
        # the asyncio event loop (WS receive handler + _on_ws_client_connect),
        # so no lock is needed — keep it that way.
        self.mixer_status: dict[str, float] = {}

        # Cluster-state tracking. Populated at load time by _resolve_cluster_state
        # (chunk 3); used to gate the armed=yes flip on all required nodes having
        # reported armed_ready. _pong_responses is populated by the comms thread
        # via status_operation_callback as pong replies arrive. All set mutations
        # and the read in _probe_cluster_liveness happen under _cluster_lock.
        self._adopted_nodes: set[str] = set()
        self._required_nodes: set[str] = set()
        self._armed_nodes: set[str] = set()
        self._finished_nodes: set[str] = set()
        self._pong_responses: set[str] = set()
        self._pong_expected: set[str] = set()
        self._pong_event = threading.Event()
        self._cluster_lock = threading.Lock()
        # One-shot watchdog: fires N seconds after _resolve_cluster_state if
        # _armed_nodes still doesn't cover _required_nodes (e.g. a node ponged
        # alive but then died mid-rsync). Logs an error listing the pending
        # nodes. Does NOT force armed=yes — operator decides.
        self._arm_watchdog: threading.Timer | None = None

        super().__init__(**kwargs)
        self.set_editor_request('')
        self.set_node_operation_callback()

    def start(self):
        self.create_timecode()
        self.set_comms()
        # Always re-detect after create_timecode(): the MtcMaster sender port
        # ("MtcMaster:MTCPort") only appears in the ALSA port list AFTER the
        # sender is created.  Connecting the listener directly to that port is
        # the most reliable loopback path; any earlier detection would have
        # picked a wrong/fallback port (e.g. rtpmidid:Announcements).
        Logger.info('Re-detecting MIDI port after MTC sender creation...')
        self.mtc_listener._MtcListener__open_port(None)
        self.mtc_listener.start()
        super().start()

    def set_status(self, property: str, value: str, strict: bool = False) -> None:
        """Set status and push to UI via WebSocket when running, armed, or load."""
        super().set_status(property, value, strict)
        if property in ('running', 'armed', 'load', 'nextcue'):
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
        
        # LISTENER binds to all interfaces (0.0.0.0) so it does not depend on the
        # avahi link-local address (169.254.x.x) being assigned before startup.
        # NodeEngine (DIALER) still targets the specific controller_url IP.
        nng_hub_address = f"tcp://0.0.0.0:{nng_hub_port}"
        
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
        self.communications_thread.set_on_client_connect(self._on_ws_client_connect)

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
        self.communications_thread.register_command_handler(
            '/engine/command/setnextcue', self._setnextcue_handler, forward_to_nodes=False
        )
        self.communications_thread.register_command_handler(
            '/engine/command/cue_enabled', self._cue_enabled_handler, forward_to_nodes=False
        )

        # Register wildcard handler for player messages (engine format)
        self.communications_thread.register_osc_handler(
            '/engine/players/*', self._handle_player_osc_message
        )
        
        # Register direct player handler for every adopted node in the network map.
        # UI sends /{node_uuid}/<type>/... for both controller and worker nodes;
        # without per-node registration the WS dispatcher silently drops the
        # message and the NNG forward never happens.
        # The set deduplicates so the controller's own UUID isn't registered
        # twice (it appears in both node_conf and network_map['node_list']).
        node_uuids: set[str] = set()
        own_uuid = self.cm.node_conf.get('uuid', '') if hasattr(self, 'cm') and self.cm else ''
        if own_uuid:
            node_uuids.add(own_uuid)
        try:
            if self.cm and self.cm.network_map:
                adopted, _new = NetworkMap.get_nodes_by_adoption(self.cm.network_map)
                for entry in adopted:
                    nuuid = (entry.get('node') or {}).get('uuid')
                    if nuuid:
                        node_uuids.add(nuuid)
        except Exception as e:
            Logger.warning(f"Could not enumerate node UUIDs from network_map: {e}")

        for nuuid in node_uuids:
            self.communications_thread.register_osc_handler(
                f'/{nuuid}/*', self._handle_direct_player_osc_message
            )
            Logger.info(f"Registered direct player OSC handler for /{nuuid}/*")

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

        # Shadow audio mixer volume so /realtime clients can recover state on
        # reconnect or page reload. Address shape:
        #   /{node_uuid}/audio/mixer/{output_index}/{channel}/volume
        # NaN/Inf are dropped to avoid polluting the dict.
        if (len(parts) >= 6
                and parts[1] == 'audio' and parts[2] == 'mixer'
                and parts[-1] == 'volume'
                and value is not None):
            try:
                vol = float(value)
            except (TypeError, ValueError):
                vol = None
            if vol is not None and math.isfinite(vol):
                node_uuid_part, output_index, channel = parts[0], parts[3], parts[4]
                key = f'{node_uuid_part}/{output_index}/{channel}'
                self.mixer_status[key] = vol
                self._broadcast_status(
                    f'audio/mixer/{node_uuid_part}/{output_index}/{channel}/volume',
                    vol,
                )

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

        # Drop operations for cues not belonging to the current project.
        # This prevents stale REMOVE/ADD notifications from the NodeEngine
        # (sent when it disarms the previous project) from being broadcast
        # to the UI as unknown UUIDs.
        if cue_id and cue_id not in self.cue_status:
            Logger.debug(f'Ignoring cue operation for unknown/stale cue_id {cue_id} (action={operation.action})')
            return

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
            # Only transition to 100 if the cue was actually playing (status == 1).
            # REMOVEs that arrive while status is 0 (e.g. NodeEngine disarming the
            # previous project after a reload) are stale and must be silently dropped.
            if cue_id:
                if self.cue_status.get(cue_id) == 1:
                    self.cue_status[cue_id] = 100
                    self._broadcast_cue_status(cue_id, 100, force=True)
                else:
                    Logger.debug(f'Ignoring stale REMOVE for cue {cue_id} (status={self.cue_status.get(cue_id)}, expected 1)')
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

        Handles script_finished, armed_ready, nextcue, cue_enabled, and pong
        notifications.
        """
        Logger.info(f'Status operation received: {operation}')
        if operation.target == 'pong':
            # Cluster liveness probe reply. Runs on the AsyncCommsThread event
            # loop; _probe_cluster_liveness on the main thread waits on the event.
            with self._cluster_lock:
                self._pong_responses.add(operation.sender)
                if self._pong_responses >= self._pong_expected:
                    self._pong_event.set()
            Logger.debug(f'Pong from {operation.sender}')
            return
        if operation.target == 'script_finished':
            if operation.data and operation.data.get('running') == 'no':
                # Aggregate per-node: only flip running=no when all required
                # nodes have reported. Filter foreign senders to keep the
                # tracker bounded.
                sender = operation.sender
                if sender not in self._adopted_nodes:
                    Logger.debug(
                        f'Ignoring script_finished from non-adopted node {sender}'
                    )
                    return
                with self._cluster_lock:
                    self._finished_nodes.add(sender)
                    finished_now = set(self._finished_nodes)
                    required = set(self._required_nodes)
                Logger.info(
                    f'Node {sender} script_finished '
                    f'({len(finished_now)}/{len(required)})'
                )
                if finished_now >= required and self.get_status('running') == 'yes':
                    Logger.info('All required nodes finished — updating running status')
                    self.set_status('running', 'no')
        elif operation.target == 'armed_ready':
            if operation.data and operation.data.get('armed') == 'yes':
                # Aggregate per-node: only flip armed=yes when all required
                # nodes have reported. Filter foreign senders to keep the
                # tracker bounded.
                sender = operation.sender
                if sender not in self._adopted_nodes:
                    Logger.debug(
                        f'Ignoring armed_ready from non-adopted node {sender}'
                    )
                    return
                with self._cluster_lock:
                    self._armed_nodes.add(sender)
                    armed_now = set(self._armed_nodes)
                    required = set(self._required_nodes)
                Logger.info(
                    f'Node {sender} armed ({len(armed_now)}/{len(required)})'
                )
                if armed_now >= required and self.get_status('armed') != 'yes':
                    if self.go_offset is None:
                        Logger.info(
                            'Re-arm after stop complete — restarting timecode and enabling GO'
                        )
                        self.start_timecode()
                        self.go_offset = 0
                    else:
                        Logger.info('All required nodes armed — enabling GO')
                    self.set_status('armed', 'yes')
                    self._cancel_arm_watchdog()
        elif operation.target == 'nextcue':
            nextcue_id = operation.data.get('nextcue', '') if operation.data else ''
            self.set_status('nextcue', nextcue_id)
            Logger.info(f'Next cue updated: {nextcue_id or "(none)"}')
        elif operation.target == 'cue_enabled':
            cue_id = operation.data.get('cue_id') if operation.data else None
            enabled = operation.data.get('enabled', True) if operation.data else True
            if cue_id and cue_id in self.cue_enabled_status:
                self.cue_enabled_status[cue_id] = enabled
                self._broadcast_cue_enabled(cue_id, enabled)
                Logger.info(f'Cue {cue_id} enabled status updated from node: {enabled}')
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
            'go_script': self.go_script,
            'project_status': self.get_project_status,
            'project_unload': self.unload_project,
        }
        if action in command_dict.keys():
            result = command_dict[action](value, context)
            if result:
                reply_value = result if isinstance(result, dict) else 'OK'
                self.confirm_to_editor(
                    context, type=action, value=reply_value
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

    def _collect_project_nodes(self, cuelist) -> set[str]:
        """Walk a cuelist and return the set of node UUIDs referenced by any
        cue's output_name.

        output_name format depends on cue type:
          - video / audio: "<36-char UUID>_<index>" (e.g. "07131798-...-...d18f_0")
          - DMX:           "<UUID>" (no suffix)
        In both cases, output_name[:36] is the node UUID. We validate with a
        cheap UUID-shape check (hyphens at positions 8/13/18/23) so garbage
        output names don't leak non-UUID strings into the set.
        """
        from cuemsutils.cues import CueList
        nodes: set[str] = set()
        if not (hasattr(cuelist, 'contents') and cuelist.contents):
            return nodes
        for item in cuelist.contents:
            if item is None:
                continue
            outputs = getattr(item, 'outputs', None) or []
            for out in outputs:
                if not isinstance(out, dict):
                    continue
                name = out.get('output_name') or ''
                if len(name) >= 36:
                    head = name[:36]
                    if (
                        head[8] == '-' and head[13] == '-'
                        and head[18] == '-' and head[23] == '-'
                    ):
                        nodes.add(head)
            if isinstance(item, CueList):
                nodes.update(self._collect_project_nodes(item))
        return nodes

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

    def _collect_cue_enabled(self, cuelist) -> dict[str, bool]:
        """Recursively collect cue enabled states from a cuelist."""
        from cuemsutils.cues import CueList
        result = {}
        if hasattr(cuelist, 'contents') and cuelist.contents:
            for item in cuelist.contents:
                if item is None:
                    continue
                result[item.id] = item.enabled
                if isinstance(item, CueList):
                    result.update(self._collect_cue_enabled(item))
        return result

    def _broadcast_cue_enabled(self, cue_id: str, enabled: bool) -> None:
        """Broadcast per-cue enabled status to UI at /engine/status/cue_enabled/{uuid}."""
        if hasattr(self, 'communications_thread') and self.communications_thread \
                and hasattr(self.communications_thread, 'broadcast_osc'):
            self.communications_thread.broadcast_osc(
                f'/engine/status/cue_enabled/{cue_id}', 1 if enabled else 0)

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

    async def _on_ws_client_connect(self, websocket) -> None:
        """Send full state dump to a newly connected WebSocket client."""
        from .osc.WebSocketOscHandler import build_osc_message

        # Engine status
        for key in ('running', 'armed', 'load', 'nextcue'):
            val = self.get_status(key)
            if val is not None:
                data = build_osc_message(f'/engine/status/{key}', val)
                if data:
                    await websocket.send(data)

        # Per-cue playback status
        for cid, status in self.cue_status.items():
            data = build_osc_message(f'/engine/status/cue/{cid}', status)
            if data:
                await websocket.send(data)

        # Per-cue enabled status
        for cid, enabled in self.cue_enabled_status.items():
            data = build_osc_message(
                f'/engine/status/cue_enabled/{cid}', 1 if enabled else 0)
            if data:
                await websocket.send(data)

        # Per-mixer-channel volume status.
        # Scale note: each entry is one ~80-byte WS message. Acceptable up to
        # ~500 entries (~40 KB / ~500 ms over LAN). If a deployment ever
        # exceeds that (e.g. 8 nodes × 64 channels), switch to a single OSC
        # bundle via build_osc_bundle() instead of per-message sends.
        for key, vol in self.mixer_status.items():
            data = build_osc_message(f'/engine/status/audio/mixer/{key}/volume', vol)
            if data:
                await websocket.send(data)

        Logger.info(f'Late-join state dump sent to new WebSocket client')

    def on_timecode_change(self, value) -> None:
        """Broadcast timecode to UI as integer ms (whole seconds only), once per second."""
        try:
            ms = int(value) if value is not None else 0
        except (TypeError, ValueError):
            return
        current_second = ms // 1000
        if current_second != self._last_timecode_second:
            self._last_timecode_second = current_second
            self._broadcast_status('timecode', current_second * 1000)
            Logger.debug(f'Timecode broadcast {current_second}s')

    def _clear_playback_state(self):
        """Clear runtime playback tracking: timestamps, timecode, armed, nextcue.

        Also clears the per-node armed/finished accumulators. The
        _required_nodes / _adopted_nodes snapshots stay — they belong to
        the loaded project, not playback state, and get recomputed on the
        next load_project. unload_project clears them explicitly.
        """
        self._cue_broadcast_timestamps.clear()
        self._last_timecode_second = -1
        self._broadcast_status('timecode', 0)
        self.set_status('armed', 'no')
        self.set_status('nextcue', '')
        self.stop_timecode()
        with self._cluster_lock:
            self._armed_nodes.clear()
            self._finished_nodes.clear()
        self._cancel_arm_watchdog()

    #########################
    # Project management
    #########################

    def load_project(self, project_name, context=None, deploy_only=False):
        # Don't allow loading while script is running
        if self.get_status('running') == "yes":
            Logger.warning(f'Cannot load project {project_name} while script is running. Stop first.')
            return False

        Logger.info(f'Loading project {project_name}')
        self._clear_playback_state()
        self.reset_script()
        
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
        for cid in self.cue_status:
            self._broadcast_cue_status(cid, 0, force=True)
        Logger.info(f'Cue status initialised for {len(self.cue_status)} cues')

        # Initialise per-cue enabled status from XML (resets show-time overrides).
        self.cue_enabled_status = self._collect_cue_enabled(self.script.cuelist)
        for cid, enabled in self.cue_enabled_status.items():
            self._broadcast_cue_enabled(cid, enabled)
        Logger.info(f'Cue enabled status initialised for {len(self.cue_enabled_status)} cues')

        # Update internal status
        # TODO: send project UUID instead of name for robustness (would break UI contract)
        self.set_status('load', project_name)

        # Probe cluster, derive _required_nodes for GO gating, refresh <online>
        # in network_map. Done BEFORE _forward_load_to_nodes so the gating set
        # is in place by the time nodes start sending armed_ready.
        self._resolve_cluster_state()

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

    def _setnextcue_handler(self, value):
        """Handle setnextcue from UI — forward to NodeEngine which owns the pointer."""
        self._forward_command_to_nodes('/engine/command/setnextcue', value)

    def _cue_enabled_handler(self, value):
        """Handle cue_enabled toggle from UI.

        Value format: "<cue_id> <0|1>" (space-separated UUID and enabled flag).
        """
        if not value or not isinstance(value, str):
            Logger.warning(f'Invalid cue_enabled value: {repr(value)}')
            return

        parts = value.split(' ', 1)
        if len(parts) != 2 or parts[1] not in ('0', '1'):
            Logger.warning(f'Invalid cue_enabled format (expected "uuid 0|1"): {repr(value)}')
            return

        cue_id, enabled_str = parts
        enabled = enabled_str == '1'

        if cue_id not in self.cue_enabled_status:
            Logger.warning(f'cue_enabled: unknown cue_id {cue_id}')
            return

        self.cue_enabled_status[cue_id] = enabled
        self._broadcast_cue_enabled(cue_id, enabled)
        self._forward_command_to_nodes('/engine/command/cue_enabled', value)
        Logger.info(f'Cue {cue_id} {"enabled" if enabled else "disabled"}')

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

    def _controller_uuid(self) -> str:
        if hasattr(self, 'cm') and self.cm:
            return self.cm.node_conf.get('uuid', 'controller')
        return 'controller'

    def _adopted_uuids_from_network_map(self) -> set[str]:
        """Read adopted node UUIDs from the in-memory network_map.

        We avoid NetworkMap.get_nodes_by_adoption() because it mutates the dict
        via strtobool — only works on the first pass; subsequent calls raise
        because `adopted`/`online` are no longer string-typed.
        """
        out: set[str] = set()
        try:
            node_list = (self.cm.network_map or {}).get('node_list', [])
            for entry in node_list:
                if not isinstance(entry, dict):
                    continue
                node = entry.get('node') or {}
                uuid = node.get('uuid')
                adopted = node.get('adopted', False)
                if isinstance(adopted, str):
                    adopted = adopted.strip().lower() in ('true', '1', 'yes')
                if adopted and uuid:
                    out.add(uuid)
        except Exception as e:
            Logger.warning(f'Could not read network_map: {e}')
        return out

    def _probe_cluster_liveness(self, timeout: float = 1.5) -> set[str]:
        """Broadcast a ping to all nodes and collect pong replies.

        The set of senders that respond within `timeout` is the authoritative
        "alive right now" view of the cluster. The controller's own UUID is
        always included (it never needs to ping itself).

        Returns the set of UUIDs that are alive.
        """
        controller_uuid = self._controller_uuid()
        adopted_uuids = self._adopted_uuids_from_network_map()

        expected = adopted_uuids - {controller_uuid}

        with self._cluster_lock:
            self._pong_responses.clear()
            self._pong_expected = set(expected)
        self._pong_event.clear()

        if not expected:
            Logger.debug('Cluster probe: no remote nodes to ping')
            return {controller_uuid}

        if not hasattr(self, 'communications_thread') or not self.communications_thread:
            Logger.warning('Cluster probe skipped: communications thread not available')
            return {controller_uuid}

        ping_op = NodeOperation(
            type=OperationType.COMMAND,
            action=ActionType.UPDATE,
            sender=controller_uuid,
            target='ping',
            data={'value': None, 'address': '/engine/cluster/ping'},
        )
        try:
            asyncio.run_coroutine_threadsafe(
                self.communications_thread.nng_hub.send_operation(ping_op),
                self.communications_thread.event_loop,
            )
        except Exception as e:
            Logger.warning(f'Could not broadcast cluster ping: {e}')
            return {controller_uuid}

        # Early-exit wait. The comms thread sets the event when all expected
        # pongs have arrived; otherwise we wake on timeout with whatever did.
        self._pong_event.wait(timeout=timeout)

        with self._cluster_lock:
            alive = set(self._pong_responses)
        alive.add(controller_uuid)
        Logger.debug(
            f'Cluster probe: expected={sorted(expected)} '
            f'alive_remote={sorted(alive - {controller_uuid})}'
        )
        return alive

    def _resolve_cluster_state(self) -> None:
        """Probe the cluster and decide which nodes the GO gate must wait for.

        Snapshots three sets at load time:
          - adopted: UUIDs from network_map.xml
          - alive:   UUIDs that ponged within the probe window
          - project: UUIDs referenced by any cue's output_name in self.script

        Computes self._required_nodes = adopted & alive & project, then
        always adds the controller's own UUID (its node-engine always
        processes the load and sends armed_ready, so this is reachable —
        and prevents the degenerate set() >= set() = True case from
        flipping armed=yes before any node has loaded).

        Categorizes each adopted node and logs info / warning / error.
        Resets _armed_nodes / _finished_nodes for the new project.
        """
        controller_uuid = self._controller_uuid()
        adopted = self._adopted_uuids_from_network_map()
        try:
            project = self._collect_project_nodes(self.script.cuelist)
        except Exception as e:
            Logger.warning(f'Could not collect project nodes: {e}')
            project = set()
        alive = self._probe_cluster_liveness()

        # Categorize for operator visibility.
        for uuid in sorted(adopted):
            in_alive = uuid in alive
            in_project = uuid in project
            if in_alive and in_project:
                continue  # the silent happy path — tracked via armed_ready
            if in_alive and not in_project:
                Logger.info(f'node {uuid} online but unused by this project')
            elif not in_alive and in_project:
                Logger.error(
                    f'node {uuid} required by this project but did not '
                    f'respond to ping; cues for it will not play. GO blocked.'
                )
            else:
                Logger.warning(
                    f'node {uuid} is adopted but did not respond to ping; '
                    f'not required by this project — investigate why it is offline'
                )

        # Project nodes that are NOT adopted at all — script is broken for
        # this cluster.
        for uuid in sorted(project - adopted):
            Logger.warning(
                f'project references node {uuid} which is not in the cluster; '
                f'cues for it will not fire'
            )

        required = (adopted & alive & project) | {controller_uuid}

        with self._cluster_lock:
            self._adopted_nodes = set(adopted)
            self._required_nodes = required
            self._armed_nodes.clear()
            self._finished_nodes.clear()

        Logger.info(
            f'Cluster state resolved: required={sorted(required)} '
            f'alive={sorted(alive)} adopted={sorted(adopted)} '
            f'project={sorted(project)}'
        )

        # The probe's `alive` set is a runtime liveness snapshot (sub-second,
        # used here for GO gating). The <online> field in network_map.xml is
        # a different concept: nodeconf's startup-discovery flag, persisted
        # so that adopted-but-currently-absent nodes keep their identity
        # records instead of being dropped from the map. The engine must NOT
        # overwrite that with its runtime view. See CLAUDE.md "Node identity"
        # / "<online> field ownership" for the full rationale.

        self._arm_arm_watchdog()

    _ARM_WATCHDOG_S = 120.0

    def _arm_arm_watchdog(self) -> None:
        """(Re)start the watchdog timer that surfaces a stalled load.

        Fires _ARM_WATCHDOG_S seconds after a load if not all required nodes
        have reported armed_ready by then. Logs an error naming the
        still-pending UUIDs so operator sees what's wedged.
        """
        self._cancel_arm_watchdog()
        timer = threading.Timer(self._ARM_WATCHDOG_S, self._on_arm_watchdog_fire)
        timer.daemon = True
        self._arm_watchdog = timer
        timer.start()

    def _cancel_arm_watchdog(self) -> None:
        timer = self._arm_watchdog
        if timer is not None:
            timer.cancel()
            self._arm_watchdog = None

    def _on_arm_watchdog_fire(self) -> None:
        with self._cluster_lock:
            armed = set(self._armed_nodes)
            required = set(self._required_nodes)
        pending = required - armed
        if not pending:
            return
        Logger.error(
            f'Load stalled: nodes still pending armed_ready after '
            f'{self._ARM_WATCHDOG_S:.0f}s: {sorted(pending)}'
        )

    def stop_script(self, value):
        """Handle STOP command - stop timecode, update status and forward to nodes."""
        if self.get_status('running') != "yes":
            Logger.info('Script not running, nothing to stop.')
            return

        self.go_offset = None
        self.set_status('running', "no")
        self._clear_playback_state()

        # Reset all cue statuses to unplayed (0) and broadcast to UI.
        for cid in self.cue_status:
            self.cue_status[cid] = 0
            self._broadcast_cue_status(cid, 0, force=True)

        self._forward_command_to_nodes('/engine/command/stop', value)

        Logger.info('STOP command processed - timecode stopped; nodes will re-arm')
        return True

    def get_project_status(self, value, context=None):
        """Return current project playback status."""
        running = self.get_status('running') == "yes"
        return {
            "status": "running" if running else "none",
            "project_uuid": str(self.script.id) if running and self.script else ""
        }

    def unload_project(self, value, context=None):
        """Unload the current project. Rejects if playback is running."""
        if self.get_status('running') == "yes":
            raise RuntimeError("Cannot unload while running. Stop playback first.")
        self._clear_playback_state()
        self.reset_script()
        self.cue_status = {}
        self.cue_enabled_status = {}
        self.set_status('load', '')
        # No project loaded → no required/adopted snapshot. Without this, a
        # late armed_ready from a slow node could flip armed=yes on an
        # unloaded project.
        with self._cluster_lock:
            self._required_nodes.clear()
            self._adopted_nodes.clear()
        self._forward_command_to_nodes('/engine/command/stop', value)
        Logger.info('Project unloaded')
        return True
