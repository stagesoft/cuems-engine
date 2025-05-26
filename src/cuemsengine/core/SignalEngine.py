import signal
from time import sleep

from cuemsutils.log import Logger, logged
from cuemsengine.core.EngineStatus import EngineStatus
from os import getpid, path, remove

SHOW_LOCK_PATH = '/tmp/cuems.show.lock'

class SignalEngine:
    """
    A class that handles system signals and status tracking.
    """
    def __init__(self):
        self.status = EngineStatus()
        self.pid = getpid()
        Logger.info(f"Starting {self.__class__.__name__} with PID {self.pid}")
        self.running = False
        self.show_locked = False

        self.register_signals()

    ### RUNNING LOGIC ###
    @logged
    def start(self) -> None:
        self.register_signals()
        self.running = True
        Logger.info(f"{self.__class__.__name__} started")
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
            if hasattr(self, 'stop_all'):
                self.stop_all()
        except:
            Logger.warning('Exception when calling stop_all')
        self.remove_show_lock_file()
        self.running = False

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
