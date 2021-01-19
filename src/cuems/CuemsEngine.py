#!/usr/bin/env python3

# %%
import threading
import queue
from multiprocessing import Queue as MPQueue
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
# from .CueProcessor import CuePriorityQueue, CueQueueProcessor
from .XmlReaderWriter import XmlReader
from .ConfigManager import ConfigManager
from .HWDiscovery import hw_discovery

CUEMS_CONF_PATH = '/etc/cuems/'


# %%
class CuemsEngine():
    def __init__(self):
        logger.info('CUEMS ENGINE INITIALIZATION')
        # Main thread ids
        logger.info(f'Main thread PID: {os.getpid()}')

        try:
            logger.info(f'Hardware discovery launched...')
            hw_discovery()
        except Exception as e:
            logger.exception(f'Exception: {e}')
            exit(-1)

        # Running flag
        self.stop_requested = False

        self._editor_request_uuid = None

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
        settings_dict['load_timeout'] = self.cm.node_conf['load_timeout']
        settings_dict['discovery_timeout'] = self.cm.node_conf['discovery_timeout']
        self.engine_queue = MPQueue()
        self.editor_queue = MPQueue()
        self.ws_server = CuemsWsServer(self.engine_queue, self.editor_queue, settings_dict)
        try:
            self.ws_server.start(self.cm.node_conf['websocket_port'])
        except KeyError:
            self.stop_all_threads()
            logger.exception('Config error, websocket_port key not found in settings. Exiting.')
            exit(-1)
        except Exception as e:
            self.stop_all_threads()
            logger.error('Exception when starting websocket server. Exiting.')
            logger.exception(e)
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
                            '/engine/status/timecode' : [ossia.ValueType.Int, None], 
                            '/engine/status/currentcue' : [ossia.ValueType.String, None],
                            '/engine/status/nextcue' : [ossia.ValueType.String, None],
                            '/engine/status/running' : [ossia.ValueType.Int, None]
                            }

        self.ossia_queue.put(QueueData('add', OSC_ENGINE_CONF))

        # Check, start and OSC register video devices/players
        self._video_players = {}
        try:
            self.check_video_devs()
        except Exception as e:
            logger.error(f'Error checking & starting video devices...')
            logger.exception(e)
            logger.error(f'Exiting...')
            exit(-1)

        # Everything is ready now and should be working, let's run!
        while not self.stop_requested:
            time.sleep(0.005)

        self.stop_all_threads()

    def engine_queue_consumer(self):
        while not self.stop_requested:
            if not self.engine_queue.empty():
                item = self.engine_queue.get()
                logger.debug(f'Received queue message from WS server: {item}')
                self.editor_command_callback(item)
            time.sleep(0.004)

    def editor_command_callback(self, item):
        try:
            self._editor_request_uuid = item['action_uuid']
        except KeyError:
            self.editor_queue.put({"type":"error", "action":None, 'action_uuid':None, "value":"No action uuid submitted"})
            return

        try:
            if not item['type'] in ['error', 'initial_settings']:
                self.editor_queue.put({"type":"error", "action":None, 'action_uuid':self._editor_request_uuid, "value":"Response not recognized"})
                self._editor_request_uuid = None
        except KeyError:
            try:
                if not item['action'] in ['load_project', 'hw_discovery']:
                    self.editor_queue.put({"type":"error", "action":None, 'action_uuid':self._editor_request_uuid, "value":"Command not recognized"})
                    self._editor_request_uuid = None
                else:
                    if item['action'] == 'load_project':
                        self._editor_request_uuid = item['action_uuid']
                        logger.info(f'Load project command received via WS. project: {item["value"]} request: {self._editor_request_uuid}')
                        self.load_project_callback(value = item['value'])
                    elif item['action'] == 'hw_discovery':
                        self._editor_request_uuid = item['action_uuid']
                        logger.info(f'HW discovery command received via WS. project: {item["value"]} request: {self._editor_request_uuid}')
                        try:
                            hw_discovery()
                        except:
                            self.editor_queue.put({'type':'error', 'action':'hw_discovery', 'action_uuid':self._editor_request_uuid, 'value':'HW discovery failed, check logs.'})
                            logger.error(f'HW discovery failed after ws request, request id: {self._editor_request_uuid}')
                            self._editor_request_uuid = None
                        else:
                            self.editor_queue.put({'type':'hw_discovery', 'action_uuid':self._editor_request_uuid, 'value':'OK'})
                            self._editor_request_uuid = None

            except KeyError:
                logger.exception(f'Not recognized communications with WSServer. Queue msg received: {item}')

    #########################################################
    # Check functions
    def check_project_mappings(self):
        if self.cm.default_mappings:
            return True

        if self.cm.project_maps['audio']:
            if self.cm.project_maps['audio']['outputs']:
                # TO DO : per channel assignment
                for item in self.cm.project_maps['audio']['outputs']:
                    for subitem in item:
                        if subitem['name'] not in self.cm.node_outputs['audio_outputs']:
                            raise Exception(f'Audio output mapping incorrect')

            elif self.cm.project_maps['audio']['inputs']:
                for item in self.cm.project_maps['audio']['inputs']:
                    for subitem in item:
                        if subitem['name'] not in self.cm.node_outputs['audio_inputs']:
                            raise Exception(f'Audio input mapping incorrect')

        if self.cm.project_maps['video']:
            if self.cm.project_maps['video']['outputs']:
                for item in self.cm.project_maps['video']['outputs']:
                    for subitem in item:
                        if subitem['name'] not in self.cm.node_outputs['video_outputs']:
                            raise Exception(f'Video output mapping incorrect')

            elif self.cm.project_maps['video']['inputs']:
                for item in self.cm.project_maps['video']['inputs']:
                    for subitem in item:
                        if subitem['name'] not in self.cm.node_outputs['video_inputs']:
                            raise Exception(f'Video input mapping incorrect')

        if self.cm.project_maps['dmx']:
            if self.cm.project_maps['dmx']['outputs']:
                for item in self.cm.project_maps['dmx']['outputs']:
                    for subitem in item:
                        if subitem['name'] not in self.cm.node_outputs['dmx_outputs']:
                            raise Exception(f'dmx output mapping incorrect')

            elif self.cm.project_maps['dmx']['inputs']:
                for item in self.cm.project_maps['dmx']['inputs']:
                    for subitem in item:
                        if subitem['name'] not in self.cm.node_outputs['dmx_inputs']:
                            raise Exception(f'dmx input mapping incorrect')

    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        if self.cm.node_outputs['video_outputs']:
            for index, item in enumerate(self.cm.node_outputs['video_outputs']):
                # Assign a videoplayer object
                port = self.cm.players_port_index['start']
                while port in self.cm.players_port_index['used']:
                    port += 2

                player_id = item
                self._video_players[player_id] = dict()

                try:
                    self._video_players[player_id]['player'] = VideoPlayer(  port, 
                                                                        item,
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
                                            '/jadeo/start' : [ossia.ValueType.Int, None],
                                            '/jadeo/load' : [ossia.ValueType.String, None],
                                            '/jadeo/cmd' : [ossia.ValueType.String, None],
                                            '/jadeo/quit' : [ossia.ValueType.Int, None],
                                            '/jadeo/offset' : [ossia.ValueType.String, None],
                                            '/jadeo/offset.1' : [ossia.ValueType.Int, None],
                                            '/jadeo/midi/connect' : [ossia.ValueType.String, None],
                                            '/jadeo/midi/disconnect' : [ossia.ValueType.Int, None]
                                            }

                self.cm.players_port_index['used'].append(port)

                self.ossia_queue.put(   QueueOSCData(   'add', 
                                                        self._video_players[player_id]['route'], 
                                                        self.cm.node_conf['osc_dest_host'], 
                                                        port,
                                                        port + 1, 
                                                        OSC_VIDEOPLAYER_CONF))
        else:
            logger.info('No video outputs detected.')

    def quit_video_devs(self):
        for dev in self._video_players.values():
            key = f'{dev["route"]}/jadeo/cmd'
            try:
                self.ossia_server.osc_registered_nodes[key][0].parameter.value = 'quit'
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
        self.mtclistener.stop()
        self.mtclistener.join()

        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            libmtcmaster.MTCSender_release(self.mtcmaster)
            logger.info('MTC Master released')
        except:
            logger.exception('MTC Master could not be released')

        self.quit_video_devs()

        self.disarm_all()

        self.stop_requested = True

        self.cm.join()

        try:
            self.ws_server.stop()
            logger.info(f'Ws-server thread finished')
        except AttributeError:
            logger.exception('Could not stop Ws-server')

        try:
            while not self.engine_queue.empty():
                self.engine_queue.get()
            self.engine_queue_loop.join()
            self.engine_queue.close()

            while not self.editor_queue.empty():
                self.editor_queue.get()
            self.editor_queue.close()
            logger.debug('IPC queues clean and closed')
        except:
            logger.exception('Could not clean and close IPC queues')

        try:
            self.ossia_server.stop()
            self.ossia_server.join()
            logger.info(f'Ossia server thread finished')
        except:
            logger.exception('Could not stop Ossia server')

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
        try:
            self.stop_all_threads()
        except:
            logger.exception('Exception when closing all threads')

        time.sleep(0.1)
        string = f'SIGTERM received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        logger.info(string)
        exit()

    def sigIntHandler(self, sigNum, frame):
        try:
            self.stop_all_threads()
        except:
            logger.exception('Exception when closing all threads')

        time.sleep(0.1)
        string = f'SIGINT received! Exiting with result code: {sigNum}'
        print('\n\n' + string + '\n\n')
        logger.info(string)
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

        if self.script:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.disarm_all()
            self.armedcues.clear()
            self.ongoing_cue = None
            self.next_cue_pointer = None
            self.go_offset = 0
            self.script = None

        try:
            self.cm.load_project_settings(kwargs["value"])
            # logger.info(self.cm.project_conf)
        except FileNotFoundError:
            logger.info(f'Project settings file not found. Adopting defaults.')
        except:
            logger.info(f'Project settings error while loading. Adopting defaults.')

        try:
            self.cm.load_project_mappings(kwargs["value"])
            # logger.info(self.cm.project_maps)
        except:
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'Mapping files error while loading.'})
            return

        try:
            self.check_project_mappings()
        except Exception as e:
            logger.error('Wrong configuration on input/output mappings')
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'Wrong configuration on input/output mappings'})
            return

        try:
            schema = os.path.join(self.cm.cuems_conf_path, 'script.xsd')
            xml_file = os.path.join(self.cm.library_path, 'projects', kwargs['value'], 'script.xml')
            reader = XmlReader( schema, xml_file )
            self.script = reader.read_to_objects()
        except FileNotFoundError:
            logger.error('Project script file not found')
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'Project script file not found'})
            self._editor_request_uuid = None
        except xmlschema.exceptions.XMLSchemaException as e:
            logger.exception(f'XML error: {e}')
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'Script XML parsing error'})
            self._editor_request_uuid = None
        except Exception as e:
            logger.error(f'Project script could not be loaded {e}')
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'Script could not be loaded'})
            self._editor_request_uuid = None

        if self.script is None:
            logger.warning(f'Script could not be loaded. Check consistency and retry please.')
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'Script could not be loaded'})
            return

        try:
            self.script_media_check()
        except FileNotFoundError:
            logger.error(f'Script {kwargs["value"]} cannot be run, media not found!')
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'Media not found'})
            self.script = None
            return

        try:
            self.initial_cuelist_process(self.script.cuelist)
        except:
            logger.error(f"Error processing script data. Can't be loaded.")
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'value':"Error processing script data. Can't be loaded."})
            self.script = None
            return

        # Then we force-arm the first item in the main list
        self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
        # And get it ready to wait a GO command
        self.next_cue_pointer = self.script.cuelist.contents[0]
        self.ossia_server.oscquery_registered_nodes['/engine/status/nextcue'][0].parameter.value = self.next_cue_pointer.uuid

        # Start MTC!
        libmtcmaster.MTCSender_play(self.mtcmaster)

        # Everything went OK we notify it to the WS server through the queue
        self.editor_queue.put({'type':'load_project', 'action_uuid':self._editor_request_uuid, 'value':'OK'})
        self._editor_request_uuid = None

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

                self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = 1
        else:
            logger.warning('No script loaded, cannot process GO command.')

    def pause_callback(self, **kwargs):
        logger.info('OSC PAUSE!')
        try:
            libmtcmaster.MTCSender_pause(self.mtcmaster)
            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = int(not self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value)
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop_callback(self, **kwargs):
        logger.info('OSC STOP!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.go_offset = 0
            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = 0
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all_callback(self, **kwargs):
        logger.info('OSC RESETALL!')
        try:
            libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.disarm_all()
            self.armedcues.clear()
            self.disconnect_video_devs()
            self.ongoing_cue = None
            self.go_offset = 0

            self.ossia_server.oscquery_registered_nodes['/engine/status/running'][0].parameter.value = 0

            if self.script:
                self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
                self.next_cue_pointer = self.script.cuelist.contents[0]
                self.ossia_server.oscquery_registered_nodes['/engine/status/nextcue'][0].parameter.value = self.next_cue_pointer.uuid

                self.ossia_server.oscquery_registered_nodes['/engine/status/currentcue'][0].parameter.value = ""
                self.ossia_server.oscquery_registered_nodes['/engine/status/nextcue'][0].parameter.value = self.script.cuelist.contents[0].uuid
            libmtcmaster.MTCSender_play(self.mtcmaster)

        except Exception as e:
            logger.exception(e)

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
            self.editor_queue.put({'type':'error', 'action':'load_project', 'action_uuid':self._editor_request_uuid, 'subtype':'media', 'data':media_list})
            self._editor_request_uuid = None

            raise FileNotFoundError
        
    def initial_cuelist_process(self, cuelist, caller = None):
        ''' 
        Review all the items recursively to update target uuids and objects
        and to load all the "loaded" flagged
        '''
        try:
            for index, item in enumerate(cuelist.contents):
                if item.check_mappings(self.cm):
                    if isinstance(item, VideoCue):
                        try:
                            for output in item.outputs:
                                # TO DO : add support for multiple outputs
                                video_player_id = self.cm.get_video_player_id(output['output_name'])
                                item._player = self._video_players[video_player_id]['player']
                                item._osc_route = self._video_players[video_player_id]['route']
                        except Exception as e:
                            logger.exception(e)
                            raise e
                else:
                    raise Exception(f"Cue outputs badly assigned in cue : {item.uuid}")

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
            raise
            
    def disarm_all(self):
        for item in self.armedcues:
            item.stop()
            item.disarm(self.ossia_queue)


    ########################################################
