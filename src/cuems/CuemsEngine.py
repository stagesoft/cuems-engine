#!/usr/bin/env python3

# %%
import threading
import queue
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

        # Main thread flags
        self.stop_requested = False
        self.conf_loaded_condition = threading.Condition()

        # Our MTC objects
        # logger.info('Starting MTC listener')
        self.mtclistener = MtcListener(step_callback=self.mtc_step_callback)

        # MTC master object creation through bound library and open port
        self.mtcmaster = libmtcmaster.MTCSender_create()
        logger.info('MTC Master created')

        #########################################################
        # System signals handlers
        signal.signal(signal.SIGINT, self.sigIntHandler)
        signal.signal(signal.SIGTERM, self.sigTermHandler)
        signal.signal(signal.SIGUSR1, self.sigUsr1Handler)
        signal.signal(signal.SIGUSR2, self.sigUsr2Handler)
        signal.signal(signal.SIGCHLD, self.sigChldHandler)

        # Conf
        self.general_conf = {}
        self.node_conf = {}
        self.master_flag = False
        self.project_conf = {}

        self.cm = threading.Thread(target = self.config_manager, name = 'confman')
        self.cm.start()

        with self.conf_loaded_condition:
            while self.node_conf == None:
                self.conf_loaded_condition.wait()

        self.ws_server = CuemsWsServer.CuemsWsServer()
        self.ws_server.start(self.node_conf['websocket_port'])

        self.ossia_queue = queue.Queue()
        self.ossia_server = OssiaServer(self.node_conf, self.ossia_queue)
        self.ossia_server.start()

        # Execution Queues
        self.main_queue = RunningQueue(True, 'Main', self.ossia_server, self.mtcmaster)
        self.preview_queue = RunningQueue(False, 'Preview', self.ossia_server, self.mtcmaster)

        # Initial OSC nodes to tell ossia to configure
        self.osc_bridge_conf = {'/engine' : [ossia.ValueType.Impulse, None],
                                '/engine/command' : [ossia.ValueType.Impulse, None],
                                '/engine/command/load' : [ossia.ValueType.String, self.main_queue.load],
                                '/engine/command/go' : [ossia.ValueType.String, self.main_queue.go],
                                '/engine/command/pause' : [ossia.ValueType.Impulse, self.main_queue.pause],
                                '/engine/command/stop' : [ossia.ValueType.Impulse, self.main_queue.stop],
                                '/engine/command/resetall' : [ossia.ValueType.Impulse, self.main_queue.reset_all],
                                '/engine/command/preload' : [ossia.ValueType.String, self.main_queue.preload],
                                '/engine/status/timecode' : [ossia.ValueType.Int, self.main_queue.timecode], 
                                '/engine/status/currentcue' : [ossia.ValueType.String, self.main_queue.currentcue],
                                '/engine/status/nextcue' : [ossia.ValueType.String, self.main_queue.nextcue],
                                '/engine/status/running' : [ossia.ValueType.Bool, self.main_queue.running]
                                }
        self.ossia_queue.put(['add', self.osc_bridge_conf])

        while not self.stop_requested:
            time.sleep(0.01)

        self.stop_all_threads()

    #########################################################
    # Init check functions
    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        pass

    def check_dmx_devs(self):
        pass

    #########################################################
    # Ordered stopping
    def stop_all_threads(self):
        self.stop_requested = True

        try:
            libmtcmaster.MTCSender_release(self.mtcmaster)
            logger.info('MTC Master released')
        except:
            logger.info('MTC Master could not be released')

        # self.mtclistener.join()

        self.cm.join()

        self.ws_server.stop()
        logger.info(f'Ws-server thread finished')

        self.ossia_server.stop()
        logger.info(f'Ossia server thread finished')

        # self.sm.join()

    #########################################################
    # Status check functions
    def print_all_status(self):
        logger.info('STATUS REQUEST BY SIGUSR2 SIGNAL')
        if self.cm.is_alive():
            logger.info(self.cm.getName() + ' is alive)')
        else:
            logger.info(self.cm.getName() + ' is not alive, trying to restore it')
            self.cm.start()

        if self.ws_server.is_alive():
            logger.info(self.ws_server.getName() + ' is alive')
            '''
            try:
                # os.kill(self.ws_pid, 0)
            except OSError:
                logger.info('\tws child process is NOT running')
            else:
                logger.info('\tws child process is running')
            '''
        else:
            logger.info(self.ws_server.getName() + ' is not alive, trying to restore it')
            self.ws_server.start()

        logger.info(f'MTC: {self.mtclistener.timecode()}')

    #########################################################
    # Managers threaded functions and callbacks
    def config_manager(self):
        with self.conf_loaded_condition:
            engine_settings = Settings('./cuems/settings.xsd', './cuems/settings.xml')
            if not engine_settings.loaded:
                engine_settings.read()
            
            self.node_conf = engine_settings['node'][0]
            self.conf_loaded_condition.notify_all()

        if self.node_conf['master'] == 1:
            self.master_flag = True
        else:
            self.master_flag = False

        logger.info(f'Cuems {self.node_conf} config loaded')

    def mtc_step_callback(self, mtc):
        if self.main_queue.running:
            logger.info(f'MTC step callback {mtc}')
            self.ossia_server.engine_oscquery_nodes['/engine/status/timecode'].parameter.value = mtc.milliseconds

    ########################################################
    # System signals handlers
    def sigTermHandler(self, sigNum, frame):
        self.stop_all_threads()
        time.sleep(0.1)
        string = f'SIGTERM received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        if self.cm.is_alive():
            print('cm alive')
        if self.ossia_server.is_alive():
            print('ossia alive')
        if self.ws_server.process.is_alive():
            print('ws alive')
        exit()

    def sigIntHandler(self, sigNum, frame):
        self.stop_all_threads()
        time.sleep(0.1)
        string = f'SIGINT received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        if self.cm.is_alive():
            print('cm alive')
        if self.ossia_server.is_alive():
            print('ossia alive')
        if self.ws_server.process.is_alive():
            print('ws alive')
        exit()

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
    def __init__(self, main_flag, name, ossia_server, mtcmaster):
        self.main_flag = main_flag
        self.queue_name = name
        self.ossia_server = ossia_server
        self.mtcmaster = mtcmaster

        self.queue = CuePriorityQueue()
        self.processor = CueQueueProcessor(self.queue)

        self.running_flag = False

        self.previous_cue_uuid = None
        self.current_cue_uuid = None
        self.next_cue_uuid = None

    def load(self, **kwargs):
        logger.info(f'{self.queue_name} queue LOAD! -> PROJECT : {kwargs["value"]}')

    def go(self, **kwargs):
        logger.info(f'{self.queue_name} queue GO! -> CUE : {kwargs["value"]}')
        try:
            libmtcmaster.MTCSender_play(self.mtcmaster)
            self.running_flag = True
            self.ossia_server.engine_oscquery_nodes['/engine/status/running'][0].parameter.value = True
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def preload(self, **kwargs):
        logger.info(f'{self.queue_name} queue PRELOAD! -> CUE : {kwargs["value"]}')

    def pause(self, **kwargs):
        logger.info(f'{self.queue_name} queue PAUSE!')
        try:
            libmtcmaster.MTCSender_pause(self.mtcmaster)
            self.running_flag = False
            self.ossia_server.engine_oscquery_nodes['/engine/status/running'][0].parameter.value = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop(self, **kwargs):
        logger.info(f'{self.queue_name} queue STOP!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.running_flag = False
            self.ossia_server.engine_oscquery_nodes['/engine/status/running'][0].parameter.value = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all(self, **kwargs):
        logger.info(f'{self.queue_name} queue RESETALL!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.running_flag = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def timecode(self, **kwargs):
        logger.info(f'{self.queue_name} queue TIMECODE!')
        # libmtcmaster.MTCSender_stop(self.mtcmaster)

    def currentcue(self, **kwargs):
        logger.info(f'{self.queue_name} queue CURRENTCUE!')
        # libmtcmaster.MTCSender_stop(self.mtcmaster)

    def nextcue(self, **kwargs):
        logger.info(f'{self.queue_name} queue NEXTCUE!')
        # libmtcmaster.MTCSender_stop(self.mtcmaster)

    def running(self, **kwargs):
        logger.info(f'{self.queue_name} queue RUNNING!')
        # libmtcmaster.MTCSender_stop(self.mtcmaster)
