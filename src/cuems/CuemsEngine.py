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
from .Settings import Settings
from .CuemsScript import CuemsScript
from .CueList import CueList
from .Cue import Cue
from .AudioCue import AudioCue
from .VideoCue import VideoCue
from .VideoPlayer import VideoPlayer
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

        #########################################################
        # System signals handlers
        signal.signal(signal.SIGINT, self.sigIntHandler)
        signal.signal(signal.SIGTERM, self.sigTermHandler)
        signal.signal(signal.SIGUSR1, self.sigUsr1Handler)
        signal.signal(signal.SIGUSR2, self.sigUsr2Handler)
        signal.signal(signal.SIGCHLD, self.sigChldHandler)

        # Conf load manager
        try:
            self.cm = ConfigManager(path=CUEMS_CONF_PATH)
        except FileNotFoundError:
            logger.critical('Node config file could not be found. Exiting !!!!!')
            exit(-1)

        # Our empty script object
        self.script = None
        '''
        CUE "POINTERS":
        here we use the "standard" point of view that there is an
        ongoing cue already running (one or many, at least the last to be gone)
        and a pointer indicating which is the next to be gone when go is pressed
        '''
        self.ongoing_cue = None
        self.next_cue_pointer = None
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
                            '/engine/command/load' : [ossia.ValueType.String, self.load_project_callback],
                            '/engine/command/loadcue' : [ossia.ValueType.String, self.load_cue_callback],
                            '/engine/command/go' : [ossia.ValueType.Impulse, self.go_callback],
                            '/engine/command/gocue' : [ossia.ValueType.String, self.go_cue_callback],
                            '/engine/command/pause' : [ossia.ValueType.Impulse, self.pause_callback],
                            '/engine/command/stop' : [ossia.ValueType.Impulse, self.stop_callback],
                            '/engine/command/resetall' : [ossia.ValueType.Impulse, self.reset_all_callback],
                            '/engine/command/preload' : [ossia.ValueType.String, self.load_cue_callback],
                            '/engine/command/unload' : [ossia.ValueType.String, self.unload_cue_callback],
                            '/engine/status/timecode' : [ossia.ValueType.String, None], 
                            '/engine/status/currentcue' : [ossia.ValueType.String, None],
                            '/engine/status/nextcue' : [ossia.ValueType.String, None],
                            '/engine/status/running' : [ossia.ValueType.Bool, None]
                            }

        self.ossia_queue.put(QueueData('add', OSC_ENGINE_CONF))

        # Check, start and OSC register video devices/players
        self._video_players = {}
        try:
            self.check_video_devs()
        except Exception as e:
            logger.exception(e)

        # Everything is ready now and should be working, let's run!
        while not self.stop_requested:
            time.sleep(0.005)

        self.stop_all_threads()

    #########################################################
    # Check functions
    def check_project_mappings(self):
        for output in self.cm.project_maps['Video']['outputs']['mapping']:
            print(output)

    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        for item in self.cm.node_conf['video_outputs']['output']:
            # Assign a videoplayer object
            try:
                self._video_players[item] = VideoPlayer(    self.cm.players_port_index, 
                                                            item,
                                                            self.cm.node_conf['videoplayer']['path'],
                                                            str(self.cm.node_conf['videoplayer']['args']),
                                                            '')
            except Exception as e:
                raise e

            self._video_players[item].start()

            # And dinamically attach it to the ossia for remote control it
            self._osc_route = f'/node{self.cm.node_conf["id"]:03}/videoplayer-{item}'

            OSC_VIDEOPLAYER_CONF = {    '/jadeo/xscale' : [ossia.ValueType.Float, None],
                                        '/jadeo/yscale' : [ossia.ValueType.Float, None], 
                                        '/jadeo/corners' : [ossia.ValueType.List, None],
                                        '/jadeo/corner1' : [ossia.ValueType.List, None],
                                        '/jadeo/corner2' : [ossia.ValueType.List, None],
                                        '/jadeo/corner3' : [ossia.ValueType.List, None],
                                        '/jadeo/corner4' : [ossia.ValueType.List, None],
                                        '/jadeo/start' : [ossia.ValueType.Bool, None],
                                        '/jadeo/load' : [ossia.ValueType.String, None],
                                        '/jadeo/quit' : [ossia.ValueType.Bool, None],
                                        '/jadeo/offset' : [ossia.ValueType.String, None],
                                        '/jadeo/offset' : [ossia.ValueType.Int, None],
                                        '/jadeo/midi/connect' : [ossia.ValueType.String, None],
                                        '/jadeo/midi/disconnect' : [ossia.ValueType.Impulse, None]
                                        }

            port = self.cm.players_port_index['start']
            while port in self.cm.players_port_index['used']:
                port += 2

            self.cm.players_port_index['used'].append(port)

            self.ossia_queue.put(   QueueOSCData(   'add', 
                                                    self._osc_route, 
                                                    self.cm.node_conf['osc_dest_host'], 
                                                    port,
                                                    port + 1, 
                                                    OSC_VIDEOPLAYER_CONF))

    def check_dmx_devs(self):
        pass

    #########################################################
    # Ordered stopping
    def stop_all_threads(self):
        self.stop_requested = True

        self.disarm_all()

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
    def load_project_callback(self, **kwargs):
        logger.info(f'OSC LOAD! -> PROJECT : {kwargs["value"]}')

        if self.script != None:
            self.disarm_all()

        try:
            self.cm.load_project_settings(kwargs["value"])
            # logger.info(self.cm.project_conf)
        except FileNotFoundError as e:
            logger.exception(f'Project settings file not found : {e}')

        try:
            self.cm.load_project_mappings(kwargs["value"])
            # logger.info(self.cm.project_maps)
        except FileNotFoundError:
            logger.exception(f'Project mappings file not found . {e}')

        try:
            self.check_project_mappings()
        except Exception as e:
            logger.exception(e)

        try:
            schema = os.path.join(self.cm.cuems_conf_path, 'script.xsd')
            xml_file = os.path.join(self.cm.library_path, 'projects', kwargs['value'], 'script.xml')
            reader = XmlReader( schema, xml_file )
            self.script = reader.read_to_objects()

        except FileNotFoundError:
            logger.error('Project script file not found')
        except xmlschema.exceptions.XMLSchemaException as e:
            logger.exception(f'XML error: {e}')

        if self.script is None:
            logger.warning(f'Script could not be loaded. Check consistency and retry please.')
            raise Exception('Script could not be loaded.')
        
        try:
            self.script_media_check()
        except FileNotFoundError:
            logger.error(f'Script {kwargs["value"]} cannot be run, media not found!')
        else:
            self.initial_cuelist_process(self.script.cuelist)

            # Then we force-arm the first item in the main list
            self.script.cuelist.contents[0].arm(self.cm, self.ossia_queue, self.armedcues)

            # Start MTC!
            libmtcmaster.MTCSender_play(self.mtcmaster)

    def load_cue_callback(self, **kwargs):
        logger.info(f'OSC LOAD! -> CUE : {kwargs["value"]}')

        cue_to_load = self.script.find(kwargs['value'])

        if cue_to_load != None:
            if cue_to_load not in self.armedcues:
                cue_to_load.arm(self.cm, self.ossia_queue, self.armedcues)

    def unload_cue_callback(self, **kwargs):
        logger.info(f'OSC UNLOAD! -> CUE : {kwargs["value"]}')

        cue_to_unload = self.script.find(kwargs['value'])

        if cue_to_unload != None:
            if cue_to_unload in self.armedcues:
                cue_to_unload.disarm(self.ossia_queue)

    def go_cue_callback(self, **kwargs):
        cue_to_go = self.script.find(kwargs['value'])

        if cue_to_go is None:
            logger.error(f'Cue {kwargs["value"]} does not exist.')
        else:
            if cue_to_go not in self.armedcues:
                logger.error(f'Cue {kwargs["value"]} not prepared. Prepare it first.')
            else:
                logger.info(f'Cue {kwargs["value"]} in armedcues list. Ready!')
                logger.info(f'OSC GO! -> CUE : {cue_to_go.uuid}')

                cue_to_go.go(self.ossia_server, self.mtclistener)

                self.ongoing_cue = cue_to_go
                logger.info(f'Current Cue: {self.ongoing_cue}')

    def go_callback(self, **kwargs):
        if self.script:
            if not self.ongoing_cue:
                cue_to_go = self.script.cuelist.contents[0]
            else:
                cue_to_go = self.next_cue_pointer
                if not cue_to_go:
                    logger.info(f'Reached end of playing at {self.ongoing_cue.__class__.__name__} {self.ongoing_cue.uuid}')
                    self.ongoing_cue = None
                    return

            if cue_to_go not in self.armedcues:
                logger.error(f'Trying to go a cue that is not yet loaded. CUE : {cue_to_go.uuid}')
            else:
                self.ongoing_cue = cue_to_go
                self.ongoing_cue.go(self.ossia_server, self.mtclistener)
                self.next_cue_pointer = self.ongoing_cue.get_next_cue()
        else:
            logger.warning('No script loaded, cannot process GO command.')

    def pause_callback(self, **kwargs):
        logger.info('OSC PAUSE!')
        try:
            libmtcmaster.MTCSender_pause(self.mtcmaster)
            # self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = not self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop_callback(self, **kwargs):
        logger.info('OSC STOP!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            # self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all_callback(self, **kwargs):
        logger.info('OSC RESETALL!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.disarm_all()
            self.armedcues.clear()
            self.ongoing_cue = None

            self.script.cuelist.contents[0].arm(self.cm, self.ossia_queue, self.armedcues)
            libmtcmaster.MTCSender_play(self.mtcmaster)

            # self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = False

        except:
            pass

    ########################################################

    ########################################################
    # Script treating methods
    def script_media_check(self):
        '''
        Checks for all the media files referred in the script.
        Returns the list of those which were not found in the media library.
        '''
        media_list = self.script.get_media()

        for key, value in media_list.copy().items():
            if os.path.isfile(os.path.join(self.cm.library_path, 'media', value[0])):
                media_list.pop(key)

        if media_list:
            string = f'These media files could not be found:'
            for key, value in media_list.items():
                string += f'\n{value[1]} : {key} : {value[0]}'
            logger.error(string)
            raise FileNotFoundError
        
    def initial_cuelist_process(self, cuelist, caller = None):
        ''' 
        Review all the items recursively to update target uuids and objects
        and to load all the "loaded" flagged
        '''
        try:
            for index, item in enumerate(cuelist.contents):
                if item.loaded and not item in self.armedcues:
                    item.arm(self.cm, self.ossia_queue, self.armedcues, init = True)

                if item.target is None or item.target == "":
                    if (index + 1) == len(cuelist.contents):
                        '''
                        If the item is the last in the cuelist we leave the
                        target fields as None
                        '''
                        item.target = None
                        item._target_object = None
                    else:
                        item.target = cuelist.contents[index + 1].uuid
                        item._target_object = cuelist.contents[index + 1]
                else:
                    item._target_object = self.script.find(item.target)

                if isinstance(item, CueList):
                    self.initial_cuelist_process(item, cuelist)

        except Exception as e:
            logger.error(f'Error arming cuelist : {cuelist.uuid} : {e}')
            
    def disarm_all(self):
        for item in self.armedcues:
            if item in self.armedcues:
                item.disarm(self.ossia_queue)


    ########################################################

# %%

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

