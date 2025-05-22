import signal
from functools import partial
from os import path, getpid, remove
from time import sleep
from cuemsutils.CTimecode import CTimecode
from cuemsutils.log import Logger, logged
from cuemsutils.xml import XmlReaderWriter
from .tools.MtcListener import MtcListener
from .tools.ConfigManager import ConfigManager
from .osc import ValueType
CUEMS_CONF_PATH = '/etc/cuems/'
SHOW_LOCK_PATH = '/tmp/cuems.show.lock'
MTC_PORT = 10000

class BaseEngine:
    def __init__(self, with_cm: bool = True, with_mtc: bool = True):
        self.node_name = None
        self.mtc_port = MTC_PORT
        self._timecode = None
        self.status = EngineStatus()
        self.pid = getpid()
        Logger.info(f"Starting {self.__class__.__name__} with PID {self.pid}")

        if with_cm:
            self.set_config_manager()
        if with_mtc:
            self.set_mtc_listener()
    
        # Engine parameters
        self.go_offset = 0
        self.node_host = f"http://{self.node_name}.local"
        self.running = False
        self.script = None
        self.show_locked = False
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

    @logged
    def start(self) -> None:
        self.register_signals()
        self.running = True
        Logger.info(f"BaseEngine {self.node_name} started")
        self.run()

    def restart(self) -> None:
        pass

    def reload(self) -> None:
        pass

    @logged
    def run(self, tick: float = 3, max_tick: float = None) -> None:
        while self.running:
            sleep(tick)
            if max_tick is not None:
                if tick < max_tick:
                    tick += 0.01
                else:
                    self.stop()

    @logged
    def stop(self) -> None:
        self.stop_requested = True
        try:
            self.stop_all_threads()
        except:
            Logger.warning('Exception when closing all threads')
        self.running = False

    def stop_all_threads(self) -> None:
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
                reset_callback = mtc_reset,
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

    def mtc_callback(self, mtc: CTimecode) -> None:
        if self.go_offset:
            self.timecode = mtc.milliseconds - self.go_offset

    ### CONFIG MANAGER ###
    def set_config_manager(self) -> None:
        """Set the ConfigManager"""
        try:
            self.cm = ConfigManager(path = CUEMS_CONF_PATH)
        except FileNotFoundError:
            Logger.error('Node config file could not be found. Exiting !!!!!')
            exit(-1)
        except Exception as e:
            Logger.error(f'Exception while loading config: {e}')
            exit(-1)
        
        # Get node name from config as a check step
        try:
            self.node_name = str(self.cm.node_conf['name'])
        except KeyError:
            Logger.error('Node name not found in config. Exiting !!!!!')
            exit(-1)

        # Get tmp path from config as a check step
        try:
            self.tmp_path = str(self.cm.node_conf['tmp_path'])
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

    ### SIGNALS HANDLERS ###
    def register_signals(self) -> None:
        signal.signal(signal.SIGINT, self.handle_interrupt)
        signal.signal(signal.SIGTERM, self.handle_terminate)
        signal.signal(signal.SIGUSR1, self.handle_print_running)
        signal.signal(signal.SIGUSR2, self.handle_print_all)
        signal.signal(signal.SIGCHLD, self.handle_child_signal)

    def handle_interrupt(self, sigNum, frame) -> None:
        string = f'SIGINT received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        Logger.info(string)

        self.stop()
        sleep(0.1)
        exit()
    
    def handle_terminate(self, sigNum, frame) -> None:
        string = f'SIGTERM received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        Logger.info(string)

        self.stop()
        sleep(0.1)
        exit()

    def handle_print_all(self, sigNum, frame) -> None:
        Logger.info(f"STATUS REQUEST BY SIGUSR2 SIGNAL {sigNum}")
        self.print_all_status()

    def handle_print_running(self, sigNum, frame) -> None:
        run_str = "" if self.running else " NOT"
        string = f"SIGNAL {sigNum} recieved: {self.__class__.__name__} is{run_str} running"
        Logger.info(string)
        print(string)

    def handle_child_signal(self, sigNum, frame):
        pass
        # Logger.info('Child process signal received, maybe from ws-server')
        # wait_return = os.waitid(os.P_PID, self.ws_pid, os.WEXITED)
        # Logger.info(wait_return)
        #if wait_return.si_code

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
                Logger.warning("/tmp/cuems.show.lock file written...")
                self.show_locked = True
            except:
                Logger.warning("Could not write show lock file")

    def remove_show_lock_file(self): # DEV: static
        if path.isfile(SHOW_LOCK_PATH):
            try:
                remove(SHOW_LOCK_PATH)
                Logger.warning("/tmp/cuems.show.lock file removed...")
                self.show_locked = False
            except OSError:
                Logger.warning("Could not delete master lock file")

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
        parameter = endpoint.split('/')[-1]
        self.set_status(parameter, value)

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

class EngineStatus:
    def __init__(self):
        # Set all properties to None
        self.load = None
        self.loadcue = None
        self.go = None
        self.gocue = None
        self.pause = None
        self.stop = None
        self.resetall = None
        self.preload = None
        self.unload = None
        self.hwdiscovery = None
        self.deploy = None
        self.test = None
        self.timecode = None
        self.currentcue = None
        self.nextcue = None
        self.running = None
    
    @property
    def load(self) -> str:
        return self._load

    @load.setter 
    def load(self, value: str) -> None:
        self._load = value

    @property
    def loadcue(self) -> str:
        return self._loadcue

    @loadcue.setter
    def loadcue(self, value: str) -> None:
        self._loadcue = value

    @property
    def go(self) -> str:
        return self._go

    @go.setter
    def go(self, value: str) -> None:
        self._go = value

    @property
    def gocue(self) -> str:
        return self._gocue

    @gocue.setter
    def gocue(self, value: str) -> None:
        self._gocue = value

    @property
    def pause(self) -> str:
        return self._pause

    @pause.setter
    def pause(self, value: str) -> None:
        self._pause = value

    @property
    def stop(self) -> str:
        return self._stop

    @stop.setter
    def stop(self, value: str) -> None:
        self._stop = value

    @property
    def resetall(self) -> str:
        return self._resetall

    @resetall.setter
    def resetall(self, value: str) -> None:
        self._resetall = value

    @property
    def preload(self) -> str:
        return self._preload

    @preload.setter
    def preload(self, value: str) -> None:
        self._preload = value

    @property
    def unload(self) -> str:
        return self._unload

    @unload.setter
    def unload(self, value: str) -> None:
        self._unload = value

    @property
    def hwdiscovery(self) -> str:
        return self._hwdiscovery

    @hwdiscovery.setter
    def hwdiscovery(self, value: str) -> None:
        self._hwdiscovery = value

    @property
    def deploy(self) -> str:
        return self._deploy

    @deploy.setter
    def deploy(self, value: str) -> None:
        self._deploy = value

    @property
    def test(self) -> str:
        return self._test

    @test.setter
    def test(self, value: str) -> None:
        self._test = value
        self.test_recieved = value

    @property
    def test_recieved(self) -> int:
        return self._recieved

    @test_recieved.setter
    def test_recieved(self, value: int) -> None:
        pass

    @property
    def timecode(self) -> int:
        return self._timecode

    @timecode.setter
    def timecode(self, value: int) -> None:
        self._timecode = value

    @property
    def currentcue(self) -> str:
        return self._currentcue

    @currentcue.setter
    def currentcue(self, value: str) -> None:
        self._currentcue = value

    @property
    def nextcue(self) -> str:
        return self._nextcue

    @nextcue.setter
    def nextcue(self, value: str) -> None:
        self._nextcue = value

    @property
    def running(self) -> int:
        return self._running

    @running.setter
    def running(self, value: int) -> None:
        self._running = value