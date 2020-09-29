#!/usr/bin/env python3

# %%
import threading
import multiprocessing
import signal
import time
import os
import pyossia as ossia

from .CTimecode import CTimecode

from .cuems_editor import CuemsWsServer

from .MtcListener import MtcListener
from .mtcmaster import libmtcmaster

from .log import logger
from .OssiaServer import OssiaServer
from .OscServer import OscServer
from .Settings import Settings
from .CueProcessor import CuePriorityQueue, CueQueueProcessor

# %%
class CuemsEngine():
    def __init__(self):
        # Main thread ids
        self.main_thread_pid = os.getpid()
        self.main_thread_id = threading.get_ident()
        logger.info('CUEMS ENGINE INITIALIZATION')
        logger.info(f'Main thread PID: {self.main_thread_pid} ID: {self.main_thread_id}')

        # Flags
        self.stop_requested = False
        self.conf_loaded_condition = threading.Condition()
        self.ossia_created_condition = threading.Condition()

        # Conf
        self.node_conf = {}
        self.master_flag = False
        # self.engine_settings = None

        # Our MTC objects
        logger.info('Starting MTC listener')
        self.mtclistener = MtcListener(step_callback=self.mtc_step_callback)

        # MTC master object creation through bound library and open port
        self.mtcmaster = libmtcmaster.MTCSender_create()

        self.ossia_server = None

        self.main_queue = RunningQueue()
        self.preview_queue = RunningQueue()

        ########################################################3
        # System signals handlers
        signal.signal(signal.SIGINT, self.sigIntHandler)
        signal.signal(signal.SIGTERM, self.sigTermHandler)
        signal.signal(signal.SIGUSR1, self.sigUsr1Handler)
        signal.signal(signal.SIGUSR2, self.sigUsr2Handler)
        signal.signal(signal.SIGCHLD, self.sigChldHandler)

        ########################################################3
        # Threaded managers objects
        self.cm = threading.Thread(target = self.config_manager, name = 'confman')
        # self.pm = threading.Thread(target = self.project_manager, name = 'projman')
        self.ws = threading.Thread(target = self.websocket_server, name = 'wsserver')
        self.om = threading.Thread(target = self.ossia_manager, name = 'ossia')
        self.osc = threading.Thread(target = self.osc_server, name = 'osc')
        # self.sm = threading.Thread(target = self.script_manager, name = 'scriptman')
        # self.mq = threading.Thread(target = self.main_queue, name = 'mainq')
        # self.pq = threading.Thread(target = self.preview_queue, name = 'previewq')
        
        self.start_threads()

        while not self.stop_requested:
            time.sleep(0.01)

        self.stop_all_threads()

    ########################################################3
    # Init check functions
    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        pass

    def check_dmx_devs(self):
        pass

    ########################################################3
    # Thread starting functions
    def start_threads(self):
        self.stop_requested = False

        self.cm.start()
        # self.pm.start()
        self.ws.start()
        self.om.start()
        self.osc.start()
        # self.sm.start()
        # self.mq.start()
        # self.pq.start()

    ########################################################3
    # Thread stopping functions
    def stop_all_threads(self):
        self.stop_requested = True

        self.cm.join()
        # self.pm.join()
        self.ws.join()
        self.om.join()
        self.osc.join()
        # self.sm.join()
        # self.mq.join()
        # self.pq.join()

    ########################################################3
    # Status check functions
    def print_all_status(self):
        logger.info('STATUS REQUEST BY SIGUSR2 SIGNAL')
        if self.cm.is_alive():
            logger.info(self.cm.getName() + ' is alive)')
        else:
            logger.info(self.cm.getName() + ' is not alive, trying to restore it')
            self.cm.start()

        '''
        if self.pm.is_alive():
            logger.info(self.pm.getName() + ' is alive')
        else:
            logger.info(self.pm.getName() + ' is not alive, trying to restore it')
            self.pm.start()
        '''

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

        '''
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
        '''

        logger.info(f'MTC: {self.mtclistener.timecode()}')

    ########################################################3
    # Managers threaded functions
    def config_manager(self):
        self.cm_id = threading.get_ident()
        self.cm_pid = os.getpid()

        with self.conf_loaded_condition:
            engine_settings = Settings('./cuems/settings.xsd', './cuems/settings.xml')
            if not engine_settings.loaded:
                engine_settings.read()
                self.node_conf = engine_settings['node'][0]

                self.conf_loaded_condition.notify_all()

        if self.node_conf['id'] == 0:
            self.master_flag = True
        else:
            self.master_flag = False

        logger.info(f'Cuems node conf loaded : {self.node_conf}')

    def project_manager(self):
        self.pm_id = threading.get_ident()
        logger.info(f'Starting Project Manager. Thread ID: {self.pm_id}')
        while not self.stop_requested:
            time.sleep(0.01)

        logger.info(f'Stopping project manager thread')

    def websocket_server(self):
        with self.conf_loaded_condition:
            while not self.node_conf == {}:
                self.conf_loaded_condition.wait()

        # This server is to be reviewed to run it as a thread
        # or as an independent process
        # Do we need pipe communication??
        self.ws_id = threading.get_ident()
        logger.info(f'Starting Websocket Server. Thread ID: {self.ws_id}')
        
        ws_server = CuemsWsServer.CuemsWsServer()
        ws_server.start(self.node_conf['websocket_port'])

        logger.info(f'Websocket Server process own PID: {ws_server.process.pid}')
        logger.info(f'\tlistening on port: {self.node_conf["websocket_port"]}')

        while not self.stop_requested:
            time.sleep(0.01)

        logger.info(f'Stopping Websocket Server')
        ws_server.stop()
        time.sleep(0.1)

        logger.info(f'Websocket Server process terminated (PID: {ws_server.process.pid})')
        logger.info(f'Stopping ws-server thread')

    def ossia_manager(self):
        with self.conf_loaded_condition:
            while not self.node_conf == {}:
                self.conf_loaded_condition.wait()

        self.om_id = threading.get_ident()
        logger.info(f'Starting Ossia Manager. Thread ID: {self.om_id}')

        with self.ossia_created_condition:
            self.ossia_server = OssiaServer(self.node_conf)
            self.ossia_created_condition.notify_all()
            
        self.ossia_server.start()
        
        while not self.stop_requested:
            time.sleep(0.01)

        self.ossia_server.stop()

        logger.info(f'Stopping ossia manager thread')

    def osc_server(self):
        with self.conf_loaded_condition:
            while not self.node_conf == {}:
                self.conf_loaded_condition.wait()

        engine_osc_mappings = { '/engine/go':self.osc_go_handler,
                                '/engine/pause':self.osc_pause_handler,
                                '/engine/stop':self.osc_stop_handler,
                                '/engine/resetall':self.osc_resetall_handler,
                                '/engine/preload':self.osc_preload_handler
                                }

        server = OscServer( host=self.node_conf['osc_dest_host'],
                            port=self.node_conf['engine_osc_in_port'],
                            mappings=engine_osc_mappings )

        server.start()

        while not self.stop_requested:
            time.sleep(0.01)

        server.stop()

        logger.info(f'Stopping OSC server thread')

    def script_manager(self):
        self.sm_id = threading.get_ident()
        logger.info(f'Starting Script Manager. Thread ID: {self.sm_id}')
        while not self.stop_requested:
            time.sleep(0.01)

    '''
    def main_queue_(self):
        self.mq_id = threading.get_ident()
        logger.info(f'Starting main queue manager. Tthread ID: {self.mq_id}')
        
        self.previous_cue_uuid = None
        self.current_cue_uuid = None
        self.next_cue_uuid = None

        while not self.stop_requested:
            time.sleep(0.01)

    def preview_queue(self):
        self.pq_id = threading.get_ident()
        logger.info(f'Starting preview queue manager. Thread ID: {self.pq_id}')
        while not self.stop_requested:
            time.sleep(0.01)
    '''

    def mtc_step_callback(self, mtc):
        logger.info(f'MTC step callback {mtc}')
        with self.ossia_created_condition:
            while self.ossia_server == None:
                self.ossia_created_condition.wait()
        self.ossia_server.engine_oscquery_nodes['/engine/timecode'].parameter.value = mtc.milliseconds

    ########################################################
    # OSC handler functions
    def osc_go_handler(self, unused_address, args, message):
        logger.info(f'OSC /engine/go received {unused_address} {args} {message}')
        libmtcmaster.MTCSender_play(self.mtcmaster)

    def osc_pause_handler(self, unused_address, args):
        logger.info(f'OSC /engine/pause received {unused_address} {args}')
        libmtcmaster.MTCSender_pause(self.mtcmaster)

    def osc_stop_handler(self, unused_address, args):
        logger.info(f'OSC /engine/stop received {unused_address} {args}')
        libmtcmaster.MTCSender_stop(self.mtcmaster)

    def osc_resetall_handler(self, unused_address, args):
        logger.info(f'OSC /engine/resetall received {unused_address} {args}')

    def osc_preload_handler(self, unused_address, args, message):
        logger.info(f'OSC /engine/preload received {unused_address} {args} {message}')
    ########################################################

    ########################################################
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
    ########################################################


# %%

########################################################
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

class RunningQueue():
    def __init__(self, main_flag=False):
        self.mainqueue = main_flag
        self.running = False
        self.queue = CuePriorityQueue()
        self.processor = CueQueueProcessor(self.queue)