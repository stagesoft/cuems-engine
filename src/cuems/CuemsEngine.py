#!/usr/bin/env python3

# %%
import threading
import queue
import multiprocessing
from subprocess import CalledProcessError
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
from .ActionCue import ActionCue
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
        self.go_offset = 0

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
        self.engine_queue = queue.Queue()
        self.editor_queue = queue.Queue()
        self.ws_server = CuemsWsServer(self.engine_queue, self.editor_queue, settings_dict)
        try:
            self.ws_server.start(self.cm.node_conf['websocket_port'])
        except KeyError:
            self.stop_all_threads()
            logger.error('Config error, websocket_port key not found. Exiting.')
            exit(-1)
        else:
            # Threaded own queue consumer loop
            self.engine_queue_loop = threading.Thread(target=self.engine_queue_consumer, name='engineq_consumer')
            self.engine_queue_loop.start()

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

    def engine_queue_consumer(self):
        while not self.stop_requested:
            if not self.editor_queue.empty():
                item = self.editor_queue.get()
                logger.debug(f'Received queue message from WS server: {item}')
                self.editor_command_callback(item)
                self.editor_queue.task_done()
            time.sleep(0.004)

    def editor_command_callback(self, item):
        try:
            if not item['action'] in ['load_project']:
                self.editor_queue.put({"type":"error", "action":None, "value":"Command not recognized"})
            else:
                if item['action'] == 'load_project':
                    logger.info(f'Load project command received via WS')
                    self.load_project_callback(kwargs={'value' : item['value']})
        except KeyError:
            try:
                if not item['type'] in ['error', 'initial_settings']:
                    self.editor_queue.put({"type":"error", "action":None, "value":"Response not recognized"})
            except KeyError:
                logger.exception(f'Not recognized communications with WSServer. Item received: {item}')

    #########################################################
    # Check functions
    def check_project_mappings(self):
        if self.cm.project_maps['Audio']['inputs']:
            '''
            for item in self.cm.project_maps['Audio']['inputs']['mapping']:
                if item['mapped_to'] is in self.cm.node_conf['audio_inputs']['input']:
                    raise Exception(f'Audio input mapping incorrect')
            '''
            pass
        if self.cm.project_maps['Audio']['outputs']:
            '''
            for item in self.cm.project_maps['Audio']['outputs']['mapping']:
                if item['mapped_to'] is in self.cm.node_conf['audio_outputs']['output']:
                    raise Exception(f'Audio output mapping incorrect')
            '''
            pass

        if self.cm.project_maps['Video']['inputs']:
            for item in self.cm.project_maps['Video']['inputs']['mapping']:
                if item['mapped_to'] not in self.cm.node_conf['video_inputs']['input']:
                    raise Exception(f'Video input mapping incorrect')
        if self.cm.project_maps['Video']['outputs']:
            for item in self.cm.project_maps['Video']['outputs']:
                if item['mapping']['mapped_to'] not in self._video_players.keys():
                    raise Exception(f'Video output mapping incorrect')
        
        if self.cm.project_maps['DMX']['inputs']:
            '''
            for item in self.cm.project_maps['DMX']['inputs']['mapping']:
                if item['mapped_to'] is in self.cm.node_conf['dmx_inputs']['input']:
                    raise Exception(f'DMX input mapping incorrect')
            '''
            pass
        if self.cm.project_maps['DMX']['outputs']:
            '''
            for item in self.cm.project_maps['DMX']['outputs']['mapping']:
                if item['mapped_to'] is in self.cm.node_conf['dmx_outputs']['output']:
                    raise Exception(f'DMX output mapping incorrect')
            '''
            pass

    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        for index, item in enumerate(self.cm.node_conf['video_outputs']):
            # Assign a videoplayer object
            port = self.cm.players_port_index['start']
            while port in self.cm.players_port_index['used']:
                port += 2

            player_id = item['output']
            self._video_players[player_id] = dict()

            try:
                self._video_players[player_id]['player'] = VideoPlayer(  port, 
                                                                    item['output'],
                                                                    self.cm.node_conf['videoplayer']['path'],
                                                                    self.cm.node_conf['videoplayer']['args'],
                                                                    '')
            except Exception as e:
                raise e

            self._video_players[player_id]['player'].start()

            # And dinamically attach it to the ossia for remote control it
            self._video_players[player_id]['route'] = f'/node{self.cm.node_conf["id"]:03}/videoplayer-{index}'

            OSC_VIDEOPLAYER_CONF = {    '/jadeo/xscale' : [ossia.ValueType.Float, None],
                                        '/jadeo/yscale' : [ossia.ValueType.Float, None], 
                                        '/jadeo/corners' : [ossia.ValueType.List, None],
                                        '/jadeo/corner1' : [ossia.ValueType.List, None],
                                        '/jadeo/corner2' : [ossia.ValueType.List, None],
                                        '/jadeo/corner3' : [ossia.ValueType.List, None],
                                        '/jadeo/corner4' : [ossia.ValueType.List, None],
                                        '/jadeo/start' : [ossia.ValueType.Bool, None],
                                        '/jadeo/load' : [ossia.ValueType.String, None],
                                        '/jadeo/cmd' : [ossia.ValueType.String, None],
                                        '/jadeo/quit' : [ossia.ValueType.Bool, None],
                                        '/jadeo/offset' : [ossia.ValueType.String, None],
                                        '/jadeo/offset' : [ossia.ValueType.Int, None],
                                        '/jadeo/midi/connect' : [ossia.ValueType.String, None],
                                        '/jadeo/midi/disconnect' : [ossia.ValueType.Bool, None]
                                        }

            self.cm.players_port_index['used'].append(port)

            self.ossia_queue.put(   QueueOSCData(   'add', 
                                                    self._video_players[player_id]['route'], 
                                                    self.cm.node_conf['osc_dest_host'], 
                                                    port,
                                                    port + 1, 
                                                    OSC_VIDEOPLAYER_CONF))

    def stop_video_devs(self):
        for dev in self._video_players.values():
            key = f'{dev["route"]}/jadeo/quit'
            try:
                self.ossia_server.osc_registered_nodes[key][0].parameter.value = True
            except CalledProcessError:
                pass

    def disconnect_video_devs(self):
        for dev in self._video_players.values():
            try:
                key = f'{dev["route"]}/jadeo/cmd'
                self.ossia_server.osc_registered_nodes[key][0].parameter.value = 'midi disconnect'
            except KeyError:
                logger.debug(f'Key error (cmd midi disconnect) in disconnect all method {key}')

    def check_dmx_devs(self):
        pass

    #########################################################
    # Ordered stopping
    def stop_all_threads(self):
        self.stop_video_devs()

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
            while not self.engine_queue.empty():
                self.engine_queue.get()
            self.engine_queue_loop.join()
        except:
            pass

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
        if self.go_offset:
            self.ossia_server.oscquery_registered_nodes['/engine/status/timecode'][0].parameter.value = mtc.milliseconds - self.go_offset

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
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.disarm_all()
            self.armedcues.clear()
            self.ongoing_cue = None
            self.next_cue_pointer = None
            self.go_offset = 0

        try:
            self.cm.load_project_settings(kwargs["value"])
            # logger.info(self.cm.project_conf)
        except FileNotFoundError as e:
            logger.exception(f'Project settings file not found : {e}')

        try:
            self.cm.load_project_mappings(kwargs["value"])
            logger.info(self.cm.project_maps)
        except FileNotFoundError:
            logger.exception(f'Project mappings file not found . {e}')

        try:
            self.check_project_mappings()
        except Exception as e:
            logger.exception(e)
            raise Exception('Script could not be loaded.')

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
            self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
            # And get it ready to wait a GO command
            self.next_cue_pointer = self.script.cuelist.contents[0]
            self.ossia_server.oscquery_registered_nodes['/engine/status/nextcue'][0].parameter.value = self.next_cue_pointer.uuid

            # Start MTC!
            libmtcmaster.MTCSender_play(self.mtcmaster)

        # Everything went OK we notify it to the WS server through the queue
        self.editor_queue.put({'type':'load_project', 'value':'OK'})

    def load_cue_callback(self, **kwargs):
        logger.info(f'OSC LOAD! -> CUE : {kwargs["value"]}')

        cue_to_load = self.script.find(kwargs['value'])

        if cue_to_load != None:
            if cue_to_load not in self.armedcues:
                cue_to_load.arm(self.cm, self.ossia_server, self.armedcues)

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
                if self.next_cue_pointer:
                    cue_to_go = self.next_cue_pointer
                else:
                    logger.info(f'Reached end of scrip. Last cue was {self.ongoing_cue.__class__.__name__} {self.ongoing_cue.uuid}')
                    self.ongoing_cue = None
                    self.go_offset = 0
                    self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
                    return

            if cue_to_go not in self.armedcues:
                logger.error(f'Trying to go a cue that is not yet loaded. CUE : {cue_to_go.uuid}')
            else:
                self.ongoing_cue = cue_to_go
                self.ongoing_cue.go(self.ossia_server, self.mtclistener)
                self.next_cue_pointer = self.ongoing_cue.get_next_cue()
                self.go_offset = self.mtclistener.main_tc.milliseconds

                # OSC Query cues status notification
                self.ossia_server.oscquery_registered_nodes['/engine/status/currentcue'][0].parameter.value = self.ongoing_cue.uuid
                if self.next_cue_pointer:
                    self.ossia_server.oscquery_registered_nodes['/engine/status/nextcue'][0].parameter.value = self.next_cue_pointer.uuid
                else:
                    self.ossia_server.oscquery_registered_nodes['/engine/status/nextcue'][0].parameter.value = ""

                self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = True
        else:
            logger.warning('No script loaded, cannot process GO command.')

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
            self.go_offset = 0
            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = False
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all_callback(self, **kwargs):
        logger.info('OSC RESETALL!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.disarm_all()
            self.disconnect_video_devs()
            self.armedcues.clear()
            self.ongoing_cue = None
            self.go_offset = 0

            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = False

            if self.script:
                self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)

                self.ossia_server.oscquery_registered_nodes['/engine/status/currentcue'][0].parameter.value = ""
                self.ossia_server.oscquery_registered_nodes['/engine/status/nextcue'][0].parameter.value = self.script.cuelist.contents[0].uuid
            libmtcmaster.MTCSender_play(self.mtcmaster)

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
            if os.path.isfile(os.path.join(self.cm.library_path, 'media', key)):
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
                if item.check_mappings(self.cm.project_maps):
                    if isinstance(item, VideoCue):
                        try:
                            for output in item.outputs:
                                video_player_id = self.cm.get_video_player_id(output['output_name'])
                                item._player = self._video_players[video_player_id]['player']
                                item._osc_route = self._video_players[video_player_id]['route']
                        except Exception as e:
                            logger.exception(e)
                            raise e

                if item.loaded and not item in self.armedcues:
                    item.arm(self.cm, self.ossia_server, self.armedcues, init = True)

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
                elif isinstance(item, ActionCue):
                    item._action_target_object = self.script.find(item.action_target)

        except Exception as e:
            logger.error(f'Error arming cuelist : {cuelist.uuid} : {e}')
            
    def disarm_all(self):
        for item in self.armedcues:
            if item in self.armedcues:
                item.disarm(self.ossia_queue)


    ########################################################
