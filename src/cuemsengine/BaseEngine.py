import signal
from time import sleep

from cuemsutils.log import Logger, logged

class BaseEngine:
    def __init__(self):
        self.running = False

    @logged
    def start(self) -> None:
        self.register_signals()
        self.running = True
        self.run()

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
        try:
            self.stop_all_threads()
        except:
            Logger.warning('Exception when closing all threads')

        self.running = False

    def restart(self) -> None:
        pass

    def reload(self) -> None:
        pass

    def register_signals(self) -> None:
        signal.signal(signal.SIGINT, self.handle_interrupt)
        signal.signal(signal.SIGTERM, self.handle_terminate)
        signal.signal(signal.SIGUSR1, self.handle_print_running)
        signal.signal(signal.SIGUSR2, self.handle_print_all)
        signal.signal(signal.SIGCHLD, self.sigChildHandler)

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

    def sigChildHandler(self, sigNum, frame):
        pass
        # Logger.info('Child process signal received, maybe from ws-server')
        # wait_return = os.waitid(os.P_PID, self.ws_pid, os.WEXITED)
        # Logger.info(wait_return)
        #if wait_return.si_code