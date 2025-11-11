from dis import hasconst
from functools import partial
from typing import Any, Callable
from os import path, remove

from cuemsutils.log import Logger, logged
from cuemsutils.xml import XmlReaderWriter
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.ConfigManager import ConfigManager
from cuemsutils.tools.SignalEngine import SignalEngine
from cuemsutils.cues import ActionCue, CueList, CuemsScript

from .EngineStatus import EngineStatus
from ..tools.MtcListener import MtcListener
from ..osc import ValueType, OssiaServer, OssiaClient, ServerDevices, ClientDevices
from ..osc.OssiaClient import PlayerClient
from ..osc.helpers import add_callback_to_all, add_prefix_to_all
from ..cues.CueHandler import CUE_HANDLER
from ..tools.PortHandler import PORT_HANDLER

MTC_PORT = "Midi Through Port-0"
SHOW_LOCK_PATH = '/tmp/cuems.show.lock'
CONTROLLER_HOST = "localhost" #"controller.local"
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
        self.go_offset = 0
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
            self.stop_mtc_listener()
        self.remove_show_lock_file()

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
            self.status.__setattr__(property, str(value))
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
        return {f"/engine/status/{k[1:]}": [ValueType.String, self.status_callback, v] for k,v in vars(self.status).items()}
    
    def build_status_endpoints(self, host: str, func: Callable = None) -> dict:
        """Build the endpoints for a NodeEngine"""
        if func is None:
            func = self.status_callback
        keys = self.status.__dict__.keys()
        endpoints = {}
        for key in keys:
            endpoints[f"/{host}/status/{key[1:]}"] = [
                ValueType.String,
                func
            ]
        return endpoints

    ### OSCQUERY ###
    def set_oscquery_server(self, endpoints: dict = None, host: str = None, port: int = None):
        if port is None:
            port = self.cm.node_conf['oscquery_ws_port']
        if host is None:
            host = self.controller_ip
        self.oscquery_server = OssiaServer(
            host = host,
            local_port = PORT_HANDLER.new_random_port(),
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

    def server_to_client_values(
        self, client: OssiaClient, node: str, value: Any, strip: str = ""
    ) -> None:
        node = str(node).strip(strip)
        Logger.debug(f"Setting node {node} to {value} in {client}")
        try:
            client.set_value(node, value)
        except Exception as e:
            Logger.error(f"Error setting {node} to {value} in {client}: {e}")

    def client_to_server_values(self, node: str, value: Any) -> None:
        node = str(node)
        Logger.debug(f"Setting node {node} to {value} in server")
        self.oscquery_server.set_value(node, value)

    def add_player_nodes_to_local(self, client: PlayerClient, prefix: str = "") -> None:
        Logger.debug(f"Procesing nodes from client: {client}")
        if not isinstance(client, PlayerClient):
            Logger.error(f"Client {client} is not a PlayerClient")
            return
        def set_client_values(node: str, value: Any) -> None:
            self.server_to_client_values(client, node, value, strip = prefix
        )
        endpoints = client.get_endpoints()
        endpoints = add_callback_to_all(endpoints, set_client_values)
        endpoints = add_prefix_to_all(endpoints, prefix)
        Logger.debug(f"Endpoints: {endpoints}")
        self.oscquery_server.add_endpoints(endpoints)

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
        if self.mtc_listener is not None:
            self.mtc_listener.stop()
            self.mtc_listener.join()
            self.mtc_listener = None

    def reset_script(self) -> None:
        if self.script:
            self.script = None
            self.ongoing_cue = None
            self.next_cue_pointer = None
            self.go_offset = 0
            self.oscquery_server.set_value('/engine/status/running', "no")
            self.oscquery_server.set_value('/engine/status/gocue', "no")

    def mtc_callback(self, mtc: CTimecode) -> None:
        if self.go_offset:
            self.timecode = mtc.milliseconds - self.go_offset

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
        """Set the controller IP address"""
        if not hasattr(self, 'cm') or not self.cm.network_map:
            raise AttributeError('No network map found')
        nodes = self.cm.network_map.get('CuemsNodeDict', [])
        if not nodes:
            raise ValueError('No nodes found in network map')
        for node in nodes:
            if node.get('node_type') == 'NodeType.master':
                return node.get('ip')
        raise ValueError('No master node found in network map')

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
        nodes, _ = self.cm.network_map.get_nodes_by_adoption()
        if not nodes:
            raise ValueError('No nodes found in network map')
        hosts = [
            {'ip': node.get('ip'), 'uuid': node.get('uuid'), 'controller': node.get('node_type') == 'NodeType.master'}
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

    def remove_show_lock_file(self): # DEV: static
        if path.isfile(SHOW_LOCK_PATH):
            try:
                remove(SHOW_LOCK_PATH)
                Logger.info("/tmp/cuems.show.lock file removed...")
                self.show_locked = False
            except OSError:
                Logger.warning("Could not delete master lock file")

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
            if not cuelist.contents or len(cuelist.contents) == 0:
                Logger.warning('Script cuelist is empty, nothing to process')
                return
            # Skip the script cuelist and process the first cuelist
            #cuelist = cuelist.contents[0]
        Logger.debug(f'Processing cuelist: {type(cuelist)} {cuelist.id} #########################')
        if not hasattr(cuelist, 'contents') or not cuelist.contents or len(cuelist.contents) == 0:
            Logger.warning('Cuelist contents is empty, nothing to process')
            return
        
        if cuelist.check_mappings(self.cm):
            CUE_HANDLER.arm(cuelist, True)

        try:
            for index, item in enumerate(cuelist.contents):
                ## TODO: remove this hardcoded local flag
                Logger.info(f'Processing item: {type(item)} {item.id}')
                item._local = True
                item.loaded = False
                item.enabled = True
                # if item.check_mappings(self.cm):
                #     ## DEV: Hardcoded for now, should be replaced by the discovery system
                #     item._local = True

                #     Logger.info(f'{type(item)} {item.id} is mapped and {"not " if not item._local else ""}local')
                # else:
                #     raise Exception(f"Cue outputs badly assigned in cue : {item.id}")

                if isinstance(item, CueList):
                    self.initial_cuelist_process(item)

                # if item.autoload and item._local and not item.loaded:
                
                if item.target is None or item.target == "":
                    if (index + 1) == len(cuelist.contents):
                        '''
                        If the item is the last in the cuelist we leave the
                        target fields as None
                        '''
                        item.target = None
                        item._target_object = None
                    else:
                        item.target = cuelist.contents[index + 1].id
                        item._target_object = cuelist.contents[index + 1]
                else:
                    item._target_object = self.script.find(item.target)

                if item._local and not item.loaded:
                    Logger.info(f'Arming item: {type(item)} {item.id}')
                    CUE_HANDLER.arm(item, True)

                Logger.debug(f'Target object for {type(item)} {item.id} is {item._target_object}')
                if isinstance(item, ActionCue):
                    item._action_target_object = self.script.find(item.action_target)

        except Exception as e:
            Logger.error(f'Error arming cuelist : {cuelist.id} : {e}')
            raise
