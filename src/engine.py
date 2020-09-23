#!/usr/bin/env python3

# %%
import threading
import multiprocessing
import signal
import time
import os
from cuems_editor import CuemsWsServer

from MtcListener import MtcListener

from log import logger
from OssiaServer import OssiaServer
from Settings import Settings

# %%
class cuems_engine():
    # Flags
    stop_requested = False
    ws_exited = False

    # Main thread ids
    main_thread_pid = os.getpid()
    main_thread_id = threading.get_ident()

    # Conf
    node_conf = {}
    master = False
    engine_settings = None

    def __init__(self):
        # Our MTC listener object
        logger.info('CUEMS ENGINE INITIALIZATION')
        logger.info(f'Main thread PID: {self.main_thread_pid} ID: {self.main_thread_id}')
        logger.info('Starting MTC listener')
        self.mtclistener = MtcListener()

        ########################################################3
        # Threaded managers objects
        self.cm = threading.Thread(target = self.config_manager, name = 'cm')
        self.pm = threading.Thread(target = self.project_manager, name = 'pm')
        self.ws = threading.Thread(target = self.websocket_server, name = 'ws')
        self.om = threading.Thread(target = self.ossia_manager, name = 'ossia')
        self.sm = threading.Thread(target = self.script_manager, name = 'sm')
        self.mq = threading.Thread(target = self.main_queue, name = 'mq')
        self.pq = threading.Thread(target = self.preview_queue, name = 'pq')
        self.start_threads()

        signal.signal(signal.SIGINT, self.sigIntHandler)
        signal.signal(signal.SIGTERM, self.sigTermHandler)
        signal.signal(signal.SIGUSR1, self.sigUsr1Handler)
        signal.signal(signal.SIGUSR2, self.sigUsr2Handler)
        signal.signal(signal.SIGCHLD, self.sigChldHandler)

        while not self.stop_requested:
            time.sleep(0.1)

        self.stop_all_threads()

    ########################################################3
    # Init check functions
    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        pass

    ########################################################3
    # Thread starting functions
    def start_threads(self):
        self.cm.start()
        self.pm.start()
        self.ws.start()
        self.om.start()
        self.sm.start()
        self.mq.start()
        self.pq.start()

        logger.info('Threads started!!!')

    ########################################################3
    # Thread stopping functions
    def stop_all_threads(self):
        logger.info('Stopping threads!!!')
        self.stop_requested = True
        self.cm.join()
        self.pm.join()
        self.ws.join()
        self.om.join()
        self.sm.join()
        self.mq.join()
        self.pq.join()

    ########################################################3
    # Status check functions
    def print_all_status(self):
        logger.info('STATUS REQUEST BY SIGUSR2 SIGNAL')
        if self.cm.is_alive():
            logger.info(self.cm.getName() + ' is alive)')
        else:
            logger.info(self.cm.getName() + ' is not alive, trying to restore it')
            self.cm.start()

        if self.pm.is_alive():
            logger.info(self.pm.getName() + ' is alive')
        else:
            logger.info(self.pm.getName() + ' is not alive, trying to restore it')
            self.pm.start()

        if self.ws.is_alive():
            logger.info(self.ws.getName() + ' is alive')
            '''
            try:
                # os.kill(self.ws_pid, 0)
            except OSError:
                logger.info('\tws child process is NOT running')
            else:
                logger.info('\tws child process is running')
            '''

        else:
            logger.info(self.ws.getName() + ' is not alive, trying to restore it')
            self.ws.start()

        if self.sm.is_alive():
            logger.info(self.sm.getName() + ' is alive')
        else:
            logger.info(self.sm.getName() + ' is not alive, trying to restore it')
            self.sm.start()

        if self.mq.is_alive():
            logger.info(self.mq.getName() + ' is alive')
        else:
            logger.info(self.mq.getName() + ' is not alive, trying to restore it')
            self.mq.start()

        if self.pq.is_alive():
            logger.info(self.pq.getName() + ' is alive')
        else:
            logger.info(self.pq.getName() + ' is not alive, trying to restore it')
            self.pq.start()

        logger.info(f'MTC: {self.mtclistener.timecode()}')

    ########################################################3
    # Managers threaded functions
    def config_manager(self):
        self.cm_id = threading.get_ident()
        self.cm_pid = os.getpid()
        logger.info(f'Starting Config Manager. PID: {self.cm_pid} Thread ID: {self.cm_id}')

        self.engine_settings = Settings('settings.xsd', 'settings.xml')
        if not self.engine_settings.loaded:
            self.engine_settings.read()
            logger.info('Configuration loaded:')
            self.node_conf = self.engine_settings['node'][0]

        logger.info('node :\n' + print_dict(self.node_conf, 1))

        while not self.stop_requested:
            time.sleep(0.1)

    def project_manager(self):
        self.pm_id = threading.get_ident()
        logger.info(f'Starting Project Manager. Thread ID: {self.pm_id}')
        while not self.stop_requested:
            time.sleep(0.1)
    
    def websocket_server(self):
        # This server is to be reviewed to run it as a thread
        # or as an independent process
        # Do we need pipe communication??
        self.ws_id = threading.get_ident()
        logger.info(f'Starting Websocket Server. Thread ID: {self.ws_id}')
        ws_server = CuemsWsServer.CuemsWsServer()
        ws_process = multiprocessing.Process(name='cuems_ws_server', target=ws_server.start(9092))
        # self.ws_pid = os.spawnl(os.P_NOWAIT, '/usr/bin/python3', '/usr/bin/python3','/home/calamar/MEGA/StageLab/osc_control/ws-server/ws-test.py')
        logger.info(f'Websocket Server process own PID: {ws_process}')
        logger.info('\tlistening on port: 9092')
        ws_process.start()
        while not self.stop_requested:
            time.sleep(0.1)

        logger.info(f'Stopping Websocket Server')
        ws_server.stop()

        logger.info(f'Terminate Websocket Server process (PID: {ws_process})')
        ws_process.terminate()

    def ossia_manager(self):
        while not self.engine_settings.loaded:
            time.sleep(0.1)

        self.om_id = threading.get_ident()
        logger.info(f'Starting Ossia Manager. Thread ID: {self.sm_id}')

        logger.info('\tCreating Ossia server...')
        ossia_server = OssiaServer(self.node_conf)
        logger.info('\tStarting Ossia server...')
        ossia_server.start()
        
        while not self.stop_requested:
            time.sleep(0.1)

        ossia_server.stop()

    def script_manager(self):
        self.sm_id = threading.get_ident()
        logger.info(f'Starting Script Manager. Thread ID: {self.sm_id}')
        while not self.stop_requested:
            time.sleep(0.1)

    def main_queue(self):
        self.mq_id = threading.get_ident()
        logger.info(f'Starting main queue manager. Tthread ID: {self.mq_id}')
        while not self.stop_requested:
            time.sleep(0.1)

    def preview_queue(self):
        self.pq_id = threading.get_ident()
        logger.info(f'Starting preview queue manager. Thread ID: {self.pq_id}')
        while not self.stop_requested:
            time.sleep(0.1)

    ########################################################3
    # System signals handlers
    def sigTermHandler(self, sigNum, frame):
        string = 'SIGTERM received! Finishing.'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        self.stop_all_threads()
        logger.info('Exiting with result code: {}'.format(sigNum))
        exit(sigNum)

    def sigIntHandler(self, sigNum, frame):
        string = 'SIGINT received! Finishing.'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        self.stop_all_threads()
        logger.info('Exiting with result code: {}'.format(sigNum))
        exit(sigNum)

    def sigChldHandler(self, sigNum, frame):
        pass
        # logger.info('Child process signal received, maybe from ws-server')
        # wait_return = os.waitid(os.P_PID, self.ws_pid, os.WEXITED)
        # logger.info(wait_return)
        #if wait_return.si_code

    def sigUsr1Handler(self, sigNum, frame):
        string = 'RUNNING!'
        print('[' + string + '] [OK]')
        logger.info(string)

    def sigUsr2Handler(self, sigNum, frame):
        self.print_all_status()


# %%

# Utilities
def print_dict(d, depth = 0):
    outstring = ''
    formattabs = '\t' * depth
    for k, v in d.items():
        if isinstance(v, dict):
            outstring += formattabs + f'{k} :\n'
            outstring += print_dict(v, depth + 1)
        elif isinstance(v, list):
            outstring += formattabs + f'{k} :\n'
            for elem in v:
                if isinstance(elem, dict):
                    outstring += print_dict(elem, depth + 1)
                else:
                    outstring += formattabs + v
        else:
            outstring += formattabs + f'{k} : {v}\n'

    return outstring
# %%
