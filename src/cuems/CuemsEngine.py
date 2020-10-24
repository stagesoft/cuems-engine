#!/usr/bin/env python3

# %%
import threading
import queue
import multiprocessing
import signal
import time
import os
import pyossia as ossia
from uuid import uuid1
from functools import partial

from .CTimecode import CTimecode
import xmlschema.exceptions

from .cuems_editor.CuemsWsServer import CuemsWsServer

from .MtcListener import MtcListener
from .mtcmaster import libmtcmaster

from .log import logger
from .OssiaServer import OssiaServer, QueueData, QueueOSCData
from .OscServer import OscServer
from .Settings import Settings
from .CuemsScript import CuemsScript
from .CueList import CueList
from .Cue import Cue
from .AudioCue import AudioCue
from .VideoCue import VideoCue
from .DmxCue import DmxCue
from .CueProcessor import CuePriorityQueue, CueQueueProcessor
from .XmlReaderWriter import XmlReader
from .ConfigManager import ConfigManager

from pprint import pprint

CUEMS_CONF_PATH = '/etc/cuems/'
CUEMS_USER_CONF_PATH = os.environ['HOME'] + '/.cuems/'


# %%
class CuemsEngine():
    def __init__(self):
        logger.info('CUEMS ENGINE INITIALIZATION')
        # Main thread ids
        logger.info(f'Main thread PID: {os.getpid()}')

        # Running flag
        self.stop_requested = False

        # Conf load manager
        try:
            self.cm = ConfigManager(path=CUEMS_CONF_PATH)
        except FileNotFoundError:
            logger.critical('Node config file could not be found. Exiting !!!!!')
            exit(-1)

        #########################################################
        # System signals handlers
        signal.signal(signal.SIGINT, self.sigIntHandler)
        signal.signal(signal.SIGTERM, self.sigTermHandler)
        signal.signal(signal.SIGUSR1, self.sigUsr1Handler)
        signal.signal(signal.SIGUSR2, self.sigUsr2Handler)
        signal.signal(signal.SIGCHLD, self.sigChldHandler)

        # Our empty script object
        self.script = None
        self.currentcues = list()
        self.nextcues = list()
        self.armedcues = list()

        # MTC master object creation through bound library and open port
        self.mtcmaster = libmtcmaster.MTCSender_create()

        # MTC listener (could be usefull)
        try:
            self.mtclistener = MtcListener( port=self.cm.node_conf['mtc_port'], 
                                            step_callback=partial(CuemsEngine.mtc_step_callback, self), 
                                            reset_callback=partial(CuemsEngine.mtc_step_callback, self, CTimecode('0:0:0:0')))
        except KeyError:
            logger.error('mtc_port config could bot be properly loaded. Exiting.')
            exit(-1)

        # WebSocket server
        settings_dict = {}
        settings_dict['session_uuid'] = str(uuid1())
        settings_dict['library_path'] = self.cm.library_path
        settings_dict['tmp_upload_path'] = self.cm.tmp_upload_path
        settings_dict['database_name'] = self.cm.database_name
        self.ws_queue = queue.Queue()
        self.ws_server = CuemsWsServer(self.ws_queue, settings_dict)
        try:
            self.ws_server.start(self.cm.node_conf['websocket_port'])
        except KeyError:
            self.stop_all_threads()
            logger.error('Config error, websocket_port key not found. Exiting.')
            exit(-1)

        # OSSIA OSCQuery server
        self.ossia_queue = queue.Queue()
        self.ossia_server = OssiaServer(self.cm.node_conf['id'], 
                                        self.cm.node_conf['oscquery_port'], 
                                        self.cm.node_conf['oscquery_out_port'], 
                                        self.ossia_queue)
        self.ossia_server.start()

        # Initial OSC nodes to tell ossia to configure
        OSC_ENGINE_CONF = { '/engine' : [ossia.ValueType.Impulse, None],
                            '/engine/command' : [ossia.ValueType.Impulse, None],
                            '/engine/command/load' : [ossia.ValueType.String, self.load_callback],
                            '/engine/command/go' : [ossia.ValueType.String, self.go_callback],
                            '/engine/command/pause' : [ossia.ValueType.Impulse, self.pause_callback],
                            '/engine/command/stop' : [ossia.ValueType.Impulse, self.stop_callback],
                            '/engine/command/resetall' : [ossia.ValueType.Impulse, self.reset_all_callback],
                            '/engine/command/preload' : [ossia.ValueType.String, self.preload_callback],
                            '/engine/status/timecode' : [ossia.ValueType.String, None], 
                            '/engine/status/currentcue' : [ossia.ValueType.String, None],
                            '/engine/status/nextcue' : [ossia.ValueType.String, None],
                            '/engine/status/running' : [ossia.ValueType.Bool, None]
                            }

        self.ossia_queue.put(QueueData('add', OSC_ENGINE_CONF))

        # Execution Queues
        # self.main_queue = RunningQueue(True, 'Main', self.mtcmaster)
        # self.preview_queue = RunningQueue(False, 'Preview', self.mtcmaster)

        # Everything is ready now and should be working, let's run!
        while not self.stop_requested:
            time.sleep(0.005)

        self.stop_all_threads()

    #########################################################
    # Check functions
    def check_project_mappings(self):
        pass

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

        self.cm.join()

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
        if self.cm.is_alive():
            logger.info(self.cm.getName() + ' is alive)')
        else:
            logger.info(self.cm.getName() + ' is not alive, trying to restore it')
            self.cm.start()

        '''
        if self.ws_server.is_alive():
            logger.info(self.ws_server.getName() + ' is alive')
            try:
                # os.kill(self.ws_pid, 0)
            except OSError:
                logger.info('\tws child process is NOT running')
            else:
                logger.info('\tws child process is running')
        else:
            logger.info(self.ws_server.getName() + ' is not alive, trying to restore it')
            # self.ws_server.start()
        '''

        logger.info(f'MTC: {self.mtclistener.timecode()}')

    #########################################################
    # Usefull callbacks
    def mtc_step_callback(self, mtc):
        # self.timecode(value = str(mtc))
        self.ossia_server.oscquery_registered_nodes['/engine/status/timecode'][0].parameter.value = mtc.milliseconds

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
        if self.mtclistener.is_alive():
            print('mtcl alive')
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
    def load_callback(self, **kwargs):
        logger.info(f'OSC LOAD! -> PROJECT : {kwargs["value"]}')
        try:
            self.cm.load_project_mappings(kwargs["value"])
            logger.info(self.cm.project_maps)
        except FileNotFoundError:
            logger.error('Project mappings file not found')

        try:
            self.cm.load_project_settings(kwargs["value"])
            logger.info(self.cm.project_conf)
        except FileNotFoundError:
            logger.error('Project settings file not found')

        try:
            schema = os.path.join(self.cm.cuems_conf_path, 'script.xsd')
            xml_file = os.path.join(self.cm.library_path, 'projects', kwargs['value'], 'script.xml')
            reader = XmlReader( schema, xml_file )
            self.script = reader.read_to_objects()
        except FileNotFoundError:
            logger.error('Project script file not found')

        self.process_script()

        # We directly start the MTC! we are on running mode, right now
        libmtcmaster.MTCSender_play(self.mtcmaster)

    def go_callback(self, **kwargs):
        try:
            cue_to_go = self.script.find(kwargs['value'])
        except AttributeError:
            logger.warning('Go method called with no script loaded')
            return

        if cue_to_go is None:
            if cue_to_go is None:
                logger.error(f'Cue {kwargs["value"]} does not exist.')
            else:
                logger.error(f'Cue {kwargs["value"]} not prepared. Prepare it first.')
        else:
            logger.info(f'OSC GO! -> CUE : {cue_to_go.uuid}')
            try:
                key = f'{cue_to_go.osc_route}{cue_to_go.offset_route}'
                self.ossia_server.osc_registered_nodes[key][0].parameter.value = cue_to_go.review_offset(self.mtclistener.main_tc)
                logger.info(key + " " + str(self.ossia_server.osc_registered_nodes[key][0].parameter.value))
            except KeyError:
                logger.debug(f'Key error 1 in go_callback {key}')

            try:
                key = f'{cue_to_go.osc_route}/mtcfollow'
                self.ossia_server.osc_registered_nodes[key][0].parameter.value = True
            except:
                try: 
                    key = f'{cue_to_go.osc_route}/jadeo/midi/connect'
                    self.ossia_server.osc_registered_nodes[key][0].parameter.value = "Midi Through Port-0"
                except KeyError:
                    logger.debug(f'Key error 2 in go_callback {key}')

            try:
                self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = True
                self.ossia_server.oscquery_registered_nodes['/engine/status/currentcue'][0].parameter.value += kwargs['value']
            except:
                logger.info('NO MTCMASTER ASSIGNED!')

                self.currentcues.append(cue_to_go)
                logger.info(f'Current Cues CueList: {self.currentcues}')

    def preload_callback(self, **kwargs):
        logger.info(f'OSC PRELOAD! -> CUE : {kwargs["value"]}')

    def pause_callback(self, **kwargs):
        logger.info('OSC PAUSE!')
        try:
            libmtcmaster.MTCSender_pause(self.mtcmaster)
            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = not self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop_callback(self, **kwargs):
        logger.info('OSC STOP!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all_callback(self, **kwargs):
        logger.info('OSC RESETALL!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = False

        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    ########################################################

    ########################################################
    # Script treating methods
    def process_script(self):
        #######################################
        # Floating cues preparation
        logger.info('Arming:')
        try:
            for item in self.script.cuelist.contents:
                '''Each item in the floating list must be prepared when the script
                is just loaded to allow the user to play any of those cues, so...'''
                if item.timecode == False:
                    item.arm(self.cm, self.ossia_queue)
        except Exception as e:
            logger.error(f'Error arming cue : {e}')
            
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
'''
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
'''

