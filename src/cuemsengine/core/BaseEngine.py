from functools import partial
from typing import Any
from os import path, remove

from cuemsutils.log import Logger, logged
from cuemsutils.xml import XmlReaderWriter
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.ConfigManager import ConfigManager
from cuemsutils.tools.SignalEngine import SignalEngine

from .EngineStatus import EngineStatus
from ..tools.MtcListener import MtcListener
from ..osc import ValueType

MTC_PORT = "Midi Through Port-0"
SHOW_LOCK_PATH = '/tmp/cuems.show.lock'

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
        self.script = None
        self.stop_requested = False
        self.node_name = None
        self.node_host = None
        self.mtc_port = MTC_PORT
        self.timecode = None
        self.status = EngineStatus()

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
            Logger.debug(f'Setting {property} to {value}')
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
        return {f"/engine/status/{k[1:]}": [ValueType.String, self.status_callback, v] for k,v in vars(self.status).items()}

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
            self.mtc_listener.start()
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
    
    def find_hosts(self) -> list:
        """Hardcoded for now, should be replaced by a discovery system"""
        return [
            'node1',
            'node2',
            'node3'
        ]

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
            
    def build_status_endpoints(self, host: str) -> dict:
        """Build the endpoints for a NodeEngine"""
        keys = self.status.__dict__.keys()
        endpoints = {}
        for key in keys:
            endpoints[f"/{host}/status/{key[1:]}"] = [
                ValueType.String,
                self.status_callback
            ]
        return endpoints

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
