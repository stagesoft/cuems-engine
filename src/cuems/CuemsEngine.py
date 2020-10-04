#!/usr/bin/env python3

# %%
import threading
import queue
import multiprocessing
import signal
import time
import os
import pyossia as ossia
from functools import partial

from .CTimecode import CTimecode

from .cuems_editor import CuemsWsServer

from .MtcListener import MtcListener
from .mtcmaster import libmtcmaster

from .log import logger
from .OssiaServer import OssiaServer
from .OscServer import OscServer
from .Settings import Settings
from .CueProcessor import CuePriorityQueue, CueQueueProcessor
from .XmlReaderWriter import XmlReader

# %%
class CuemsEngine():
    def __init__(self):
        logger.info('CUEMS ENGINE INITIALIZATION')

        # Main thread ids
        self.main_thread_pid = os.getpid()
        os.name
        
        logger.info(f'Main thread PID: {self.main_thread_pid}')

        # Main thread conf and flags
        self.cuems_path=os.environ['HOME'] + '/cuems/'
        logger.info(f'Cuems path: {self.cuems_path}')
        self.stop_requested = False

        self.script = {}

        # MTC master object creation through bound library and open port
        self.mtcmaster = libmtcmaster.MTCSender_create()

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

        # Conf load manager
        self.config_manager = ConfigManager(path=self.cuems_path)
        try:
            self.node_conf = self.config_manager.load_node_settings()
        except FileNotFoundError:
            message = 'Node config file could not be found. Exiting.'
            print('\n\n' + message + '\n\n')
            logger.error(message)
            exit(-1)

        # Our MTC objects
        # logger.info('Starting MTC listener')
        try:
            self.mtclistener = MtcListener( port=self.node_conf['mtc_port'], 
                                            step_callback=partial(CuemsEngine.mtc_step_callback, self), 
                                            reset_callback=partial(CuemsEngine.mtc_step_callback, self, CTimecode('0:0:0:0')))
        except KeyError:
            logger.error('Node config could bot be properly loaded. Exiting.')
            exit(-1)

        # WebSocket server
        self.ws_server = CuemsWsServer.CuemsWsServer()
        try:
            self.ws_server.start(self.node_conf['websocket_port'])
        except KeyError:
            self.stop_all_threads()
            logger.error('Config error, websocket_port key not found. Exiting.')
            exit(-1)

        # OSSIA OSCQuery server
        self.ossia_queue = queue.Queue()
        self.ossia_server = OssiaServer(self.node_conf, self.ossia_queue)
        self.ossia_server.start()

        # Initial OSC nodes to tell ossia to configure
        self.osc_bridge_conf = {'/engine' : [ossia.ValueType.Impulse, None],
                                '/engine/command' : [ossia.ValueType.Impulse, None],
                                '/engine/command/load' : [ossia.ValueType.String, self.load],
                                '/engine/command/go' : [ossia.ValueType.String, self.go],
                                '/engine/command/pause' : [ossia.ValueType.Impulse, self.pause],
                                '/engine/command/stop' : [ossia.ValueType.Impulse, self.stop],
                                '/engine/command/resetall' : [ossia.ValueType.Impulse, self.reset_all],
                                '/engine/command/preload' : [ossia.ValueType.String, self.preload],
                                '/engine/status/timecode' : [ossia.ValueType.String, None], 
                                '/engine/status/currentcue' : [ossia.ValueType.String, None],
                                '/engine/status/nextcue' : [ossia.ValueType.String, None],
                                '/engine/status/running' : [ossia.ValueType.Bool, None]
                                }
        self.ossia_queue.put(['add', self.osc_bridge_conf])

        # Execution Queues
        self.main_queue = RunningQueue(True, 'Main', self.mtcmaster)
        self.preview_queue = RunningQueue(False, 'Preview', self.mtcmaster)

        while not self.stop_requested:
            time.sleep(0.005)

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

        self.mtclistener.stop()
        self.mtclistener.join()

        self.config_manager.join()

        try:
            self.ws_server.stop()
        except AttributeError:
            pass
        logger.info(f'Ws-server thread finished')

        try:
            self.ossia_server.stop()
        except AttributeError:
            pass
        logger.info(f'Ossia server thread finished')

        # self.sm.join()

    #########################################################
    # Status check functions
    def print_all_status(self):
        logger.info('STATUS REQUEST BY SIGUSR2 SIGNAL')
        if self.config_manager.is_alive():
            logger.info(self.config_manager.getName() + ' is alive)')
        else:
            logger.info(self.config_manager.getName() + ' is not alive, trying to restore it')
            self.config_manager.start()

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
            # self.ws_server.start()

        logger.info(f'MTC: {self.mtclistener.timecode()}')

    #########################################################
    # Usefull callbacks
    def mtc_step_callback(self, mtc):
        self.ossia_server.osc_registered_nodes['/engine/status/timecode'][0].parameter.value = str(mtc)

    ########################################################
    # System signals handlers
    def sigTermHandler(self, sigNum, frame):
        self.stop_all_threads()
        time.sleep(0.1)
        string = f'SIGTERM received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        if self.config_manager.is_alive():
            print('cm alive')
        if self.ossia_server.is_alive():
            print('ossia alive')
        if self.ws_server.process.is_alive():
            print('ws alive')
        if self.mtclistener.is_alive():
            print('mtcl alive')
        exit()

    def sigIntHandler(self, sigNum, frame):
        self.stop_all_threads()
        time.sleep(0.1)
        string = f'SIGINT received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        if self.config_manager.is_alive():
            print('cm alive')
        if self.ossia_server.is_alive():
            print('ossia alive')
        if self.ws_server.process.is_alive():
            print('ws alive')
        if self.mtclistener.is_alive():
            print('mtcl alive')
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

    ########################################################
    # OSC messages handlers
    def load(self, **kwargs):
        logger.info(f'OSC LOAD! -> PROJECT : {kwargs["value"]}')
        try:
            self.script = XmlReader(self.cuems_path + 'script.xsd', self.cuems_path + '/projects/' + kwargs['value'])
        except FileNotFoundError:
            logger.error('Project file not found')

    def go(self, **kwargs):
        logger.info(f'OSC GO! -> CUE : {kwargs["value"]}')
        try:
            libmtcmaster.MTCSender_play(self.mtcmaster)
            self.ossia_server.osc_registered_nodes['/engine/status/running'][0].parameter.value = True
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def preload(self, **kwargs):
        logger.info(f'OSC PRELOAD! -> CUE : {kwargs["value"]}')

    def pause(self, **kwargs):
        logger.info('OSC PAUSE!')
        try:
            libmtcmaster.MTCSender_pause(self.mtcmaster)
            self.ossia_server.osc_registered_nodes['/engine/status/running'][0].parameter.value = not self.ossia_server.osc_registered_nodes['/engine/status/running'][0].parameter.value
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop(self, **kwargs):
        logger.info('OSC STOP!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.ossia_server.osc_registered_nodes['/engine/status/running'][0].parameter.value = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all(self, **kwargs):
        logger.info('OSC RESETALL!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def timecode(self, **kwargs):
        logger.info('OSC TIMECODE!')

    def currentcue(self, **kwargs):
        logger.info('OSC CURRENTCUE!')

    def nextcue(self, **kwargs):
        logger.info('OSC NEXTCUE!')

    def running(self, **kwargs):
        logger.info(f'OSC RUNNING: {kwargs["value"]}')
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

########################################################
class ConfigManager(threading.Thread):
    def __init__(self, path, *args, **kwargs):
        super().__init__(name='CfgMan', args=args, kwargs=kwargs)
        self.cuems_path = path
        self.start()

    def load_node_settings(self):
        try:
            engine_settings = Settings(self.cuems_path + 'settings.xsd', self.cuems_path + 'settings.xml')
            engine_settings.read()
        except FileNotFoundError as e:
            raise e

        logger.info(f'Cuems {engine_settings["node"][0]} config loaded')

        return engine_settings['node'][0]


########################################################
class RunningQueue():
    def __init__(self, main_flag, name, mtcmaster):
        self.main_flag = main_flag
        self.queue_name = name
        self.mtcmaster = mtcmaster

        self.queue = CuePriorityQueue()
        self.processor = CueQueueProcessor(self.queue)

        self.running_flag = False

        self.previous_cue_uuid = None
        self.current_cue_uuid = None
        self.next_cue_uuid = None

    def go(self, **kwargs):
        logger.info(f'{self.queue_name} queue GO! -> CUE : {kwargs["value"]}')
        try:
            libmtcmaster.MTCSender_play(self.mtcmaster)
            self.running_flag = True
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def pause(self, **kwargs):
        logger.info(f'{self.queue_name} queue PAUSE!')
        try:
            libmtcmaster.MTCSender_pause(self.mtcmaster)
            self.running_flag = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop(self, **kwargs):
        logger.info(f'{self.queue_name} queue STOP!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.running_flag = False
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
