# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from dis import hasconst
from functools import partial
from typing import Any, Callable
from os import path, remove
import ipaddress
import socket

from cuemsutils.log import Logger, logged
from cuemsutils.xml import XmlReaderWriter
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.ConfigManager import ConfigManager
from cuemsutils.tools.SignalEngine import SignalEngine
from cuemsutils.cues import ActionCue, CueList, CuemsScript

from .EngineStatus import EngineStatus
from ..tools.MtcListener import MtcListener
from ..osc import VALUE_TYPES_DICT, OssiaServer, OssiaClient, ServerDevices, ClientDevices
from ..osc.OssiaClient import PlayerClient
from ..osc.helpers import add_callback_to_all, add_prefix_to_all
from ..cues.CueHandler import CUE_HANDLER
from ..tools.PortHandler import PORT_HANDLER

MTC_PORT = "Midi Through Port-0"
CONTROLLER_NETWORK_FLAG = "NodeType.master"
SHOW_LOCK_PATH = '/tmp/cuems.show.lock'
CONTROLLER_HOST = "controller.local"
NODE_ENGINE_PORT = 10000

class BaseEngine(SignalEngine):
    def __init__(self, with_cm: bool = True, with_mtc: bool = True, with_signals: bool = True):
        """
        Initialize the BaseEngine.

        Args:
            with_cm (bool): Whether to initialize the ConfigManager. Default is True.
            with_mtc (bool): Whether to initialize the MTC listener. Default is True.
            with_signals (bool): Whether to initialize the SignalEngine. Default is True.
        """
        # Engine parameters
        self.with_cm = with_cm
        self.with_mtc = with_mtc
        self.with_signals = with_signals
        self.go_offset = None  # None = not computing timecode; 0 = raw MTC
        self.script: CuemsScript = None
        self.stop_requested = False
        self.node_name = None
        self.node_host = None
        self.mtc_port = MTC_PORT
        self.timecode = None
        self.status = EngineStatus()
        self.oscquery_client_list: list[OssiaClient] = []

        super().__init__(with_signals=with_signals)
    
        if self.with_cm:
            self.set_config_manager()
        if self.with_mtc:
            self.set_mtc_listener()

        ## dev: CUE "POINTERS":
        # here we use the "standard" point of view that there is an
        # ongoing cue already running (one or many, at least the last to be gone)
        # and a pointer indicating which is the next to be gone when go is pressed
        
        self.ongoing_cue = None
        self.next_cue_pointer = None
        self.show_locked = False

        Logger.info(f"{self.__class__.__name__}@{self.node_name} initialized, waiting start signal")

    @property
    def timecode(self) -> str | None:
        return self._timecode
    
    @timecode.setter
    def timecode(self, value: str | None) -> None:
        self._timecode = value
        if hasattr(self, 'on_timecode_change'):
            self.on_timecode_change(value) # type: ignore[attr-defined]

    def stop_all(self) -> None:
        if self.with_mtc:
            try:
                self.stop_mtc_listener()
            except Exception as e:
                Logger.error(f'Error stopping MTC listener: {e}')
                raise e
        try:
            self.remove_show_lock_file()
        except Exception as e:
            Logger.error(f'Error removing show lock file: {e}')
            raise e

    ### STATUS ###
    def set_status(self, property: str, value: str, strict: bool = False) -> None:
        """Set the status of the engine
        
        Args:
            property (str): The property to set
            value (str): The value to set
            strict (bool): If True, raise an AttributeError if the property is not found
        """
        if f"_{property}" in self.status.__dict__.keys():
            Logger.debug(f'Setting property {property} to {value}')
            self.status.__setattr__(property, value)
        else:
            Logger.error(f'Property {property} not found in EngineStatus')
            if strict:
                raise AttributeError(f'Property {property} not found in EngineStatus')
    
    def get_status(self, property: str, strict: bool = False) -> str:
        """Get the status of the engine
        
        Args:
            property (str): The property to get
            strict (bool): If True, raise an AttributeError if the property is not found
        """
        value = getattr(self.status, property, "NotFound")
        if value == "NotFound":
            Logger.error(f'Property {property} not found in EngineStatus')
            if strict:
                raise AttributeError(f'Property {property} not found in EngineStatus')
        return value
    
    def status_callback(self, endpoint: str, value: str) -> None:
        """Callback for the status endpoint"""
        Logger.debug(f'Status callback received: {endpoint} = {value}')
        parameter = str(endpoint).split('/')[-1]
        self.set_status(parameter, value)

    def get_all_status_names(self) -> list[str]:
        return [i[1:] for i in vars(self.status).keys()]
    
    def get_status_endpoints(self) -> dict[str, list[Any]]:
        endpoints = self.build_endpoints_from_status()
        Logger.debug(f"Status endpoints: {endpoints}")
        # remove unwanted callbacks from status nodes that are set programmatically
        # to avoid callback loops and threading issues when push_value() is called
        for i in ["currentcue", "running", "load", "timecode", "armed"]:
            if f"/engine/status/{i}" in endpoints:
                endpoints[f"/engine/status/{i}"][1] = None
        return endpoints

    def build_endpoints_from_status(self) -> dict[str, list[Any, Callable | None, Any]]:
        endpoints = {}
        Logger.debug(f"Building endpoints from status, vars: {list(vars(self.status).keys())}")
        for k, v in vars(self.status).items():
            if v is None:
                Logger.debug(f"Skipping {k} (value is None)")
                continue
            type_name = type(v).__name__
            # Map Python type names to pyossia type names
            if type_name == 'str':
                type_name = 'string'
            if type_name not in VALUE_TYPES_DICT:
                Logger.warning(f"Unknown value type {type_name} for status property {k}, skipping")
                continue
            endpoint_path = f"/engine/status/{k[1:]}"
            endpoints[endpoint_path] = [VALUE_TYPES_DICT[type_name], self.status_callback, v]
            Logger.debug(f"Added endpoint: {endpoint_path} with type {type_name} and value {v}")
        return endpoints   

    ### OSCQUERY ###
    def set_oscquery_server(self, endpoints: dict = None, host: str = None, port: int = None):
        if port is None:
            # Try to get port from config, fallback to default
            if hasattr(self, 'cm') and self.cm and hasattr(self.cm, 'node_conf') and self.cm.node_conf:
                port = self.cm.node_conf.get('oscquery_ws_port', 9001)
            else:
                port = 9001  # Default OSCQuery port
        if host is None:
            # For ControllerEngine, controller_ip might be None, use CONTROLLER_HOST as fallback
            host = getattr(self, 'controller_ip', None) or CONTROLLER_HOST
        local_port = PORT_HANDLER.new_random_port()
        if local_port is None:
            raise RuntimeError("Failed to get random port for OSCQuery server")
        self.oscquery_server = OssiaServer(
            host = host,
            local_port = local_port,
            remote_port = port,
            server = ServerDevices.OSCQUERY,
            endpoints = endpoints
        )

    def set_oscquery_client(self, host: str = None, port: int = None) -> OssiaClient:
        if port is None:
            port = self.cm.node_conf['oscquery_ws_port']
        if host is None:
            host = self.controller_ip
        oscquery_client = OssiaClient(
            host = host,
            local_port = PORT_HANDLER.new_random_port(),
            remote_port = port,
            remote_type = ClientDevices.OSCQUERY
        )
        Logger.debug(f"OscQueryClient created: {oscquery_client}")
        self.oscquery_client_list.append(oscquery_client)
        return oscquery_client

    ### MTC LISTENER ###
    def set_mtc_listener(self) -> None:
        """Set the MTC listener"""
        mtc_step = partial(BaseEngine.mtc_callback, self)
        mtc_reset = partial(BaseEngine.mtc_callback, self, CTimecode('00:00:00:00'))
        
        if not self.mtc_port:
            self.mtc_port = self.cm.node_conf['mtc_port']

        if self.mtc_port is not None:
            self.mtc_listener = MtcListener(
                port=self.mtc_port,
                step_callback = mtc_step,
                reset_callback = mtc_reset
            )
        else:
            Logger.error('MTC port not set, cannot create MtcListener')
            self.stop()
            exit(-1)

    def stop_mtc_listener(self) -> None:
        if self.mtc_listener is not None and self.mtc_listener.is_alive():
            try:
                self.mtc_listener.stop()
                self.mtc_listener.join()
                self.mtc_listener = None
            except Exception as e:
                Logger.error(f'Error stopping MTC listener: {e}')
                raise e

    def reset_script(self) -> None:
        if self.script:
            self.script = None
            self.ongoing_cue = None
            self.next_cue_pointer = None
            self.go_offset = None
            # Only set OSCQuery values if server exists and has the nodes
            if hasattr(self, 'oscquery_server') and self.oscquery_server:
                try:
                    self.oscquery_server.set_value('/engine/status/running', "no")
                    self.oscquery_server.set_value('/engine/status/gocue', "no")
                except ValueError as e:
                    Logger.warning(f"Could not reset OSCQuery status nodes: {e}. Server may not be fully initialized.")

    def mtc_callback(self, mtc: CTimecode) -> None:
        if self.go_offset is not None:
            # Drift = current MTC - GO-time MTC. Both _exact for sub-ms
            # precision at NTSC framerates (29.97/23.976).
            self.timecode = mtc.milliseconds_exact - self.go_offset

    ### CONFIG MANAGER ###
    def set_config_manager(self) -> None:
        """Set the ConfigManager"""
        from cuemsutils.xml import ProjectMappings
        try:
            self.cm = ConfigManager(load_all=True)
            self.node_host = f"http://{self.cm.node_conf['uuid'][-12:]}.local"
        except FileNotFoundError:
            Logger.error('Node config file could not be found. Exiting !!!!!')
            exit(-1)
        except Exception as e:
            Logger.error(f'Exception while loading config: {e}')
            exit(-1)
        Logger.info(f'Node conf: {self.cm.node_conf}')
        # Get node name from config as a check step
        try:
            self.node_name = str(self.cm.node_conf['uuid'])
        except KeyError:
            Logger.error('Node name not found in config. Exiting !!!!!')
            exit(-1)

        # Get tmp path from config as a check step
        try:
            self.tmp_path = str(self.cm.tmp_path)
        except KeyError:
            Logger.error('Tmp path not found in config. Exiting !!!!!')
            exit(-1)

        # Get controller IP from network map
        try:
            self.controller_ip = self.get_controller_ip()
            Logger.info(f'Controller IP: {self.controller_ip}')
        except Exception as e:
            Logger.error(f'{type(e)} while getting controller IP: {e}')
            exit(-1)

    def get_controller_ip(self) -> str:
        """Resolve the controller's NNG-hub IP.

        Resolution order (Phase 2 — late-binding to controller.local):
          1. mDNS: resolve CONTROLLER_HOST (controller.local). cuems-nodeconf
             publishes the controller's cluster-interface address under this
             name, so a node always discovers the *live* IP — no correct
             <ip> needed in network_map.xml, and IPv4LL renegotiation
             self-heals on the next engine start.
          2. Fallback: the network_map.xml <ip> of the NodeType.master node
             (operator/nodeconf-maintained), used when mDNS is unusable.

        A loopback result from (1) is rejected on purpose: it means "this host
        IS the controller" (avahi short-circuits the own-hostname query to
        127.0.0.1), in which case the map <ip> is the deterministic local
        path (the controller's hub binds 0.0.0.0, reachable either way).
        """
        resolved = self._resolve_controller_host()
        if resolved:
            Logger.info(f'Controller IP resolved via mDNS ({CONTROLLER_HOST}): {resolved}')
            return resolved
        mapped = self._controller_ip_from_map()
        Logger.info(f'Controller IP resolved via network_map: {mapped}')
        return mapped

    def _resolve_controller_host(self) -> str | None:
        """Resolve CONTROLLER_HOST to a usable remote unicast IPv4, or None.

        Returns None (→ caller falls back to the map) on any of:
          - resolution failure (NXDOMAIN/timeout — the normal fast path when
            mDNS can't answer, e.g. avahi down),
          - a loopback / unspecified address (means this host is the
            controller; see get_controller_ip).
        Never raises — a resolution problem must degrade to the map, not
        crash engine startup.
        """
        try:
            ip = socket.gethostbyname(CONTROLLER_HOST)
        except (socket.gaierror, OSError) as e:
            Logger.debug(f'mDNS resolution of {CONTROLLER_HOST} failed: {e}')
            return None
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            Logger.warning(f'{CONTROLLER_HOST} resolved to non-IP {ip!r}; ignoring')
            return None
        if addr.is_loopback or addr.is_unspecified:
            Logger.debug(
                f'{CONTROLLER_HOST} resolved to {ip} (loopback/self); '
                f'using network_map instead'
            )
            return None
        return ip

    def _controller_ip_from_map(self) -> str:
        """Return the <ip> of the NodeType.master node in network_map.xml."""
        if not hasattr(self, 'cm') or not self.cm.network_map:
            raise AttributeError('No network map found')
        nodes = self.cm.network_map['node_list']
        if not nodes:
            raise ValueError('No nodes found in network map')
        for node_item in nodes:
            node = node_item.get('node', {}) if isinstance(node_item, dict) else {}
            if node.get('node_type') == CONTROLLER_NETWORK_FLAG:
                ip = node.get('ip')
                if not ip:
                    raise ValueError('Controller node in network map has no <ip>')
                return ip
        raise ValueError('No controller node found in network map')

    def find_hosts(self) -> list[dict[str, str | bool]]:
        """
        Extract the list of adopted online hosts in the network map

        Returns:
        - list[dict[str, str | bool]]: List of hosts with their IP, uuid and controller flag

        Exceptions:
        - ValueError: No nodes found in network map
        - AttributeError: No controller found in network map
        """
        Logger.info(f'Looking for hosts in network map')
        network_dict = self.cm.network_map
        if not network_dict:
            raise ValueError('No network map not found')
        nodes, _ = self.cm.network_map.get_nodes_by_adoption(network_dict)
        if not nodes:
            raise ValueError('No adopted nodes found in network map')
        hosts = [
            {'ip': node.get('ip'), 'uuid': node.get('uuid'), 'controller': node.get('node_type') == CONTROLLER_NETWORK_FLAG}
            for node in nodes
            if node.get('online') == 'True'
        ]
        if not any(host.get('controller') for host in hosts):
            raise AttributeError('No controller found in network map')
        if len([host for host in hosts if host.get('controller')]) > 1:
            raise AttributeError('Multiple controllers found in network map')
        return hosts

    def print_all_status(self) -> None:
        Logger.info('STATUS REQUEST BY SIGUSR2 SIGNAL')
        if self.cm.is_alive():
            Logger.info(self.cm.getName() + ' is alive)')
        else:
            Logger.info(self.cm.getName() + ' is not alive, trying to restore it')
            self.cm.start()

        '''
        if self.ws_server.is_alive():
            Logger.info(self.ws_server.getName() + ' is alive')
            try:
                # os.kill(self.ws_pid, 0)
            except OSError:
                Logger.info('\tws child process is NOT running')
            else:
                Logger.info('\tws child process is running')
        else:
            Logger.info(self.ws_server.getName() + ' is not alive, trying to restore it')
            # self.ws_server.start()
        '''

        Logger.info(f'MTC: {self.mtc_listener.timecode()}')

    ### SHOW LOCK FILE ###
    def set_show_lock_file(self): # DEV: static
        if not path.isfile(SHOW_LOCK_PATH):
            try:
                with open(SHOW_LOCK_PATH, 'w') as file:
                    file.write(' ')
                Logger.info("/tmp/cuems.show.lock file written...")
                self.show_locked = True
            except:
                Logger.warning("Could not write show lock file")
        else:
            Logger.info(f'Show lock file {SHOW_LOCK_PATH} already exists')
            self.show_locked = True

    def remove_show_lock_file(self): # DEV: static
        if path.isfile(SHOW_LOCK_PATH):
            try:
                remove(SHOW_LOCK_PATH)
                Logger.info("/tmp/cuems.show.lock file removed...")
                self.show_locked = False
            except OSError:
                Logger.warning("Could not delete master lock file")
        else:
            Logger.info(f'Show lock file {SHOW_LOCK_PATH} does not exist')
            self.show_locked = False

    @logged
    def read_script(self, project_name: str) -> None:
        xml_file = path.join(self.cm.library_path, 'projects', project_name, 'script.xml')
        if not path.isfile(xml_file):
            raise FileNotFoundError(f'Script file {xml_file} not found')
        reader = XmlReaderWriter(
            schema_name = 'script',
            xmlfile = xml_file
        )
        self.script = reader.read_to_objects()

    @logged
    def initial_cuelist_process(self, cuelist: CueList = None):
        ''' 
        Review all the items recursively to update target uuids and objects
        and to load all the "loaded" flagged
        '''
        
        if not self.script:
            Logger.error('No script found, need to load a project first')
            raise ValueError('Script is not loaded')
        
        if cuelist is None:
            cuelist = self.script.cuelist
        Logger.info(f'Processing {type(cuelist).__name__}: {cuelist.id}')
        if not hasattr(cuelist, 'contents') or not cuelist.contents or len(cuelist.contents) == 0:
            Logger.warning('Cuelist contents is empty, nothing to process')
            return
        
        cuelist.localize_cue(self.cm.node_uuid)
        CUE_HANDLER.arm(cuelist, True)

        for index, item in enumerate(cuelist.contents):
            if item is None:
                Logger.warning(f'Skipping None item at index {index} in cuelist {cuelist.id}')
                continue

            try:
                if isinstance(item, CueList):
                    self.initial_cuelist_process(item)

                item.localize_cue(self.cm.node_uuid)
                
                if item.target is None or item.target == "":
                    if (index + 1) == len(cuelist.contents):
                        '''
                        If the item is the last in the cuelist we leave the
                        target fields as None
                        '''
                        item.target = None
                        item._target_object = None
                    else:
                        next_item = cuelist.contents[index + 1]
                        if next_item is not None:
                            item.target = next_item.id
                            item._target_object = next_item
                        else:
                            item.target = None
                            item._target_object = None
                else:
                    item._target_object = self.script.find(item.target)
                    if item._target_object is None:
                        Logger.warning(f'{type(item).__name__} {item.id} has target {item.target} that could not be found in the script (deleted?)')

                Logger.debug(f'Target object for {type(item)} {item.id} is {item._target_object}')
                if isinstance(item, ActionCue):
                    item._action_target_object = self.script.find(item.action_target)
                    if item._action_target_object is None and item.action_target:
                        Logger.warning(f'ActionCue {item.id} has action_target {item.action_target} that could not be found in the script (deleted?)')

            except Exception as e:
                Logger.error(f'Error processing item at index {index} in cuelist {cuelist.id}: {e}')
                continue

        # Arm first cue + duration-aware lookahead. The sliding window
        # (_arm_ahead in go/go_threaded) arms subsequent cues during
        # playback. For post_go='go' chains, arm() recursively arms the
        # entire chain. For go_at_end chains, only 2 cues with meaningful
        # duration are armed, saving resources for large projects.
        if cuelist.contents:
            first_cue = None
            for c in cuelist.contents:
                if c.enabled:
                    first_cue = c
                    break
            # If the cuelist's first cue isn't ours, walk the post_go='go' chain
            # to find our first local cue — same shape as NodeEngine.go_script.
            # Without this, slaves don't pre-arm anything at load time and the
            # /videocomposer/layer/load only fires when GO is hit, producing
            # staggered starts as the async loads complete in arrival order.
            first_local = first_cue
            walked = 0
            while first_local is not None and not getattr(first_local, '_local', False):
                if first_local.post_go != 'go':
                    first_local = None
                    break
                first_local = getattr(first_local, '_target_object', None)
                walked += 1
                if walked > 1024:
                    first_local = None
                    break
            if first_local is not None:
                if first_local is not first_cue:
                    Logger.info(
                        f'Pre-arm: skipped {walked} non-local cue(s); arming first '
                        f'local cue {first_local.id} + lookahead')
                else:
                    Logger.info(f'Arming first enabled cue + lookahead for {type(cuelist).__name__}: {cuelist.id}')
                CUE_HANDLER.arm(first_local, True)
                CUE_HANDLER._arm_ahead(first_local)
