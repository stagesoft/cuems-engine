from functools import partial
from os import path
from cuemsutils.CTimecode import CTimecode
from cuemsutils.log import Logger, logged
from cuemsutils.xml import XmlReaderWriter

from ..tools.MtcListener import MtcListener
from ..tools.ConfigManager import ConfigManager
from ..osc import ValueType
from .SignalEngine import SignalEngine

MTC_PORT = "Midi Through Port-0"

class BaseEngine(SignalEngine):
    def __init__(self, with_cm: bool = True, with_mtc: bool = True):
        """
        Initialize the BaseEngine.

        Args:
            with_cm (bool): Whether to initialize the ConfigManager. Default is True.
            with_mtc (bool): Whether to initialize the MTC listener. Default is True.
        """
        super().__init__()
        self.node_name = None
        self.mtc_port = MTC_PORT
        self._timecode = None

        if with_cm:
            self.set_config_manager()
        if with_mtc:
            self.set_mtc_listener()
    
        # Engine parameters
        self.go_offset = 0
        self.node_host = f"http://{self.node_name}.local"
        self.script = None
        self.stop_requested = False

        ## dev: CUE "POINTERS":
        # here we use the "standard" point of view that there is an
        # ongoing cue already running (one or many, at least the last to be gone)
        # and a pointer indicating which is the next to be gone when go is pressed
        
        self.ongoing_cue = None
        self.next_cue_pointer = None

        Logger.info(f"{self.__class__.__name__}@{self.node_name} initialized, waiting start signal")

    @property
    def timecode(self) -> str:
        return self._timecode
    
    @timecode.setter
    def timecode(self, value: str) -> None:
        self._timecode = value
        if hasattr(self, 'on_timecode_change'):
            self.on_timecode_change(value)

    def stop_all(self) -> None:
        self.stop_mtc_listener()
        self.cm.join()

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
            self.mtc_listener.run()
        else:
            Logger.error('MTC port not set, cannot create MtcListener')
            self.stop()
            exit(-1)

    def stop_mtc_listener(self) -> None:
        if self.mtc_listener is not None:
            self.mtc_listener.stop()
            self.mtc_listener.join()
            self.mtc_listener = None

    def mtc_callback(self, mtc: CTimecode) -> None:
        if self.go_offset:
            self.timecode = mtc.milliseconds - self.go_offset

    ### CONFIG MANAGER ###
    def set_config_manager(self) -> None:
        """Set the ConfigManager"""
        try:
            self.cm = ConfigManager()
        except FileNotFoundError:
            Logger.error('Node config file could not be found. Exiting !!!!!')
            exit(-1)
        except Exception as e:
            Logger.error(f'Exception while loading config: {e}')
            exit(-1)
        
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

    ### DEPLOY ###
    def deploy_requests_reset(self, project_name='', tag_name=''): # DEV: static with tmp_path parameter
        path_to_reset = path.join(self.cm.tmp_path, f'rsync_request_{project_name}_{tag_name}.log')
        with open(path_to_reset, 'w') as f:
            Logger.info(f'Rsync requests log file {path_to_reset} emptied!!')
            

    def log_deploy_request(self, project_name='', tag_name='project', file_names=[]): # DEV: static with tmp_path parameter
        if project_name:
            if tag_name == 'project':
               file_names = [
                   '/projects/' + project_name + '/script.xml\n',
                    '/projects/' + project_name + '/mappings.xml\n', 
                    '/projects/' + project_name + '/settings.xml\n'
                ]
            try:
                with open(path.join(self.cm.tmp_path, f'rsync_request_{project_name}_{tag_name}.log'), 'w') as f:
                    f.writelines(file_names)
            except Exception as e:
                Logger.error(f'Exception raised when writing rsync request log file: {e}')
                return False
            else:
                return True

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

    @logged
    def read_script(self, project_name: str) -> None:
        xml_file = path.join(self.cm.library_path, 'projects', project_name, 'script.xml')
        if not path.isfile(xml_file):
            raise FileNotFoundError(f'Script file {xml_file} not found')
        reader = XmlReaderWriter(xml_file = xml_file)
        self.script = reader.read_to_objects()
