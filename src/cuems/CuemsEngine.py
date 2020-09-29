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

# from .MtcListener import MtcListener
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
        # logger.info('Starting MTC listener')
        # self.mtclistener = MtcListener(step_callback=self.mtc_step_callback)

        # MTC master object creation through bound library and open port
        self.mtcmaster = libmtcmaster.MTCSender_create()

        self.ossia_server = None

        self.main_queue = RunningQueue(main_flag=True, name='Main', mtcmaster=self.mtcmaster)
        self.preview_queue = RunningQueue(main_flag=False, name='Preview')

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
        # self.osc = threading.Thread(target = self.osc_server, name = 'osc')
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
        # self.osc.start()
        # self.sm.start()

    ########################################################3
    # Thread stopping functions
    def stop_all_threads(self):
        self.stop_requested = True

        self.cm.join()
        # self.pm.join()

        self.ws.join()
        logger.info(f'Ws-server thread finished')

        self.om.join()
        logger.info(f'Ossia server thread finished')

        # self.osc.join()
        # self.sm.join()

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
        '''

        # logger.info(f'MTC: {self.mtclistener.timecode()}')

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
            while self.node_conf == {}:
                self.conf_loaded_condition.wait()

        ws_server = CuemsWsServer.CuemsWsServer()
        ws_server.start(self.node_conf['websocket_port'])

        self.ws_id = threading.get_ident()
        logger.info(f'Websocket Server started. Thread ID: {self.ws_id} Process PID: {ws_server.process.pid} PORT : {self.node_conf["websocket_port"]}')

        while not self.stop_requested:
            time.sleep(0.01)

        ws_server.stop()
        logger.info(f'Websocket Server process terminated (PID: {ws_server.process.pid})')
        logger.info(f'Websocket server stopped')

    def ossia_manager(self):
        with self.conf_loaded_condition:
            while self.node_conf == {}:
                self.conf_loaded_condition.wait()

        osc_bridge_conf = {   '/engine' : [ossia.ValueType.Impulse, self.main_queue],
                        '/engine/go' : [ossia.ValueType.String, self.main_queue.go],
                        '/engine/pause' : [ossia.ValueType.Impulse, self.main_queue.pause],
                        '/engine/stop' : [ossia.ValueType.Impulse, self.main_queue.stop],
                        '/engine/resetall' : [ossia.ValueType.Impulse, self.main_queue.reset_all],
                        '/engine/preload' : [ossia.ValueType.String, self.main_queue.preload],
                        '/engine/timecode' : [ossia.ValueType.Int, self.main_queue.timecode]
                    }

        with self.ossia_created_condition:
            self.ossia_server = OssiaServer(self.node_conf, osc_bridge_conf)
            self.ossia_created_condition.notify_all()
            
        self.ossia_server.start()
        
        self.om_id = threading.get_ident()
        logger.info(f'Ossia Server started. Thread ID: {self.om_id}')

        while not self.stop_requested:
            time.sleep(0.01)

        self.ossia_server.stop()
        logger.info(f'Ossia server stopped')

    '''
    def osc_server(self):
        with self.conf_loaded_condition:
            while self.node_conf == {}:
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

    def mtc_step_callback(self, mtc):
        logger.info(f'MTC step callback {mtc}')
        with self.ossia_created_condition:
            while self.ossia_server == None:
                self.ossia_created_condition.wait()
        self.ossia_server.engine_oscquery_nodes['/engine/timecode'].parameter.value = mtc.milliseconds
    '''

    ########################################################
    # OSC handler functions
    '''
    def osc_go_handler(self, unused_address, args, message):
        self.main_queue.go(message)

    def osc_pause_handler(self, unused_address, args):
        self.main_queue.pause()

    def osc_stop_handler(self, unused_address, args):
        self.main_queue.stop()

    def osc_resetall_handler(self, unused_address, args):
        self.main_queue.reset_all()

    def osc_preload_handler(self, unused_address, args, message):
        self.main_queue.preload(message)
    '''
    ########################################################

    ########################################################
    # System signals handlers
    def sigTermHandler(self, sigNum, frame):
        string = 'SIGTERM received! Finishing.'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        self.stop_all_threads()
        logger.info(f'Exiting with result code: {sigNum}')
        exit(sigNum)

    def sigIntHandler(self, sigNum, frame):
        string = 'SIGINT received! Finishing.'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        self.stop_all_threads()
        logger.info(f'Exiting with result code: {sigNum}')
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
    def __init__(self, main_flag=False, name='', mtcmaster=None):
        self.main_flag = main_flag
        self.queue_name = name
        self.running = False
        self.queue = CuePriorityQueue()
        self.processor = CueQueueProcessor(self.queue)

        self.mtcmaster = mtcmaster

        self.previous_cue_uuid = None
        self.current_cue_uuid = None
        self.next_cue_uuid = None

    def go(self, **kwargs):
        logger.info(f'{self.queue_name} queue GO! -> CUE : {kwargs["value"]}')
        try:
            libmtcmaster.MTCSender_play(self.mtcmaster)
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def preload(self, **kwargs):
        logger.info(f'{self.queue_name} queue PRELOAD! -> CUE : {kwargs["value"]}')

    def pause(self, **kwargs):
        logger.info(f'{self.queue_name} queue PAUSE!')
        try:
            libmtcmaster.MTCSender_pause(self.mtcmaster)
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop(self, **kwargs):
        logger.info(f'{self.queue_name} queue STOP!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all(self, **kwargs):
        logger.info(f'{self.queue_name} queue RESETALL!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def timecode(self, **kwargs):
        logger.info(f'{self.queue_name} queue TIMECODE!')
        # libmtcmaster.MTCSender_stop(self.mtcmaster)

