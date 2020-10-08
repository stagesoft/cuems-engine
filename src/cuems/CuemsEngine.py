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
from .Cue import Cue
from .AudioCue import AudioCue
from .VideoCue import VideoCue
from .DmxCue import DmxCue
from .AudioPlayer import AudioPlayer, AudioPlayerRemote
from .VideoPlayer import VideoPlayer, VideoPlayerRemote
from .CueProcessor import CuePriorityQueue, CueQueueProcessor
from .XmlReaderWriter import XmlReader

CUEMS_CONF_PATH = os.environ['HOME'] + '/.cuems/'

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
            message = 'Node config file could not be found. Exiting.'
            print('\n\n' + message + '\n\n')
            logger.error(message)
            exit(-1)

        logger.info(f'Cuems library path: {self.cm.library_path}')

        #########################################################
        # System signals handlers
        signal.signal(signal.SIGINT, self.sigIntHandler)
        signal.signal(signal.SIGTERM, self.sigTermHandler)
        signal.signal(signal.SIGUSR1, self.sigUsr1Handler)
        signal.signal(signal.SIGUSR2, self.sigUsr2Handler)
        signal.signal(signal.SIGCHLD, self.sigChldHandler)

        # Our empty script object
        self.script = {}

        self.node_audio_players = {}
        self.node_video_players = {}
        self.node_dmx_players = {}

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
        self.ws_server = CuemsWsServer()
        try:
            self.ws_server.start(self.cm.node_conf['websocket_port'])
        except KeyError:
            self.stop_all_threads()
            logger.error('Config error, websocket_port key not found. Exiting.')
            exit(-1)

        # OSSIA OSCQuery server
        self.ossia_queue = queue.Queue()
        self.ossia_server = OssiaServer(    self.cm.node_conf['id'], 
                                            self.cm.node_conf['oscquery_port'], 
                                            self.cm.node_conf['oscquery_out_port'], 
                                            self.ossia_queue)
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
        self.ossia_server.osc_registered_nodes['/engine/status/timecode'][0].parameter.value = str(mtc)

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
    def load(self, **kwargs):
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
            schema = os.path.join(self.cm.library_path, 'script.xsd')
            xml_file = os.path.join(self.cm.library_path, 'projects', kwargs['value'], 'script.xml')
            reader = XmlReader( schema, xml_file )
            self.script = reader.read_to_objects()
        except FileNotFoundError:
            logger.error('Project script file not found')

        self.process_script()

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

    ########################################################
    # Script treating methods
    def process_script(self):
        logger.info('Timecode Cuelist:')
        for item in self.script['timecode_cuelist']:
            logger.info(f'Class: {item.__class__.__name__} UUID: {item.uuid} Outputs: {item.outputs} Time: {item.time} Media: {item.media}')
        logger.info('Floating Cuelist:')
        for item in self.script['floating_cuelist']:
            if isinstance(item, AudioCue):
                n = len(self.node_audio_players.items())
                self.node_audio_players[f'{item.uuid}'] = AudioPlayerRemote(
                    self.cm.node_conf['audioplayer']['osc_in_port_base'] + (n*2), 
                    'base_card', 
                    self.cm.node_conf['audioplayer']['path'],
                    os.path.join(self.cm.library_path, 'media', item.media))
                self.node_audio_players[f'{item.uuid}'].start()
            elif isinstance(item, VideoCue):
                n = len(self.node_video_players.items())
                self.node_video_players[f'{item.uuid}'] = VideoPlayerRemote(
                    self.cm.node_conf['videoplayer']['osc_in_port_base'] + (n*2), 
                    '1', 
                    self.cm.node_conf['videoplayer']['path'])
                self.node_video_players[f'{item.uuid}'].start()
            elif isinstance(item, DmxCue):
                pass
                '''n = len(self.node_dmx_players.items())
                self.node_dmx_players[f'{item.uuid}'] = DmxPlayerRemote(
                    self.cm.node_conf['dmxplayer']['osc_in_port_base'] + (n*2), 
                    'base_card', 
                    self.cm.node_conf['dmxplayer']['path'])
                self.node_dmx_players[f'{item.uuid}'].start()
                '''

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
        self.cuems_conf_path = path
        self.library_path = None
        self.node_conf = {}
        self.project_conf = {}
        self.project_maps = {}
        self.load_node_conf()
        self.start()

    def load_node_conf(self):
        settings_schema = os.path.join(self.cuems_conf_path, 'settings.xsd')
        settings_file = os.path.join(self.cuems_conf_path, 'settings.xml')
        try:
            engine_settings = Settings(settings_schema, settings_file)
            engine_settings.read()
        except FileNotFoundError as e:
            raise e

        if engine_settings['library_path'] == None:
            logger.warning('No library path specified in settings. Assuming default ~/cuems_library/.')
        else:
            self.library_path = engine_settings['library_path']

        # Now we know where the library is, let's check it out
        self.check_dir_hierarchy()

        self.node_conf = engine_settings['node'][0]

        logger.info(f'Cuems node_{self.node_conf["id"]:03} config loaded')
        logger.info(f'Node conf: {self.node_conf}')
        logger.info(f'Audio player conf: {self.node_conf["audioplayer"]}')
        logger.info(f'Video player conf: {self.node_conf["videoplayer"]}')
        logger.info(f'DMX player conf: {self.node_conf["dmxplayer"]}')

    def load_project_settings(self, project_uname):
        try:
            settings_schema = os.path.join(self.library_path, 'project_settings.xsd')
            settings_path = os.path.join(self.library_path, 'projects', project_uname, 'settings.xml')
            self.project_conf = Settings(settings_schema, settings_path)
            self.project_conf.read()
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            logger.error(e)

        self.project_conf.pop('xmlns:cms')
        self.project_conf.pop('xmlns:xsi')
        self.project_conf.pop('xsi:schemaLocation')

        logger.info(f'Project {project_uname} settings loaded')

    def load_project_mappings(self, project_uname):
        try:
            mappings_schema = os.path.join(self.library_path, 'project_mappings.xsd')
            mappings_path = os.path.join(self.library_path, 'projects', project_uname, 'mappings.xml')
            self.project_maps = Settings(mappings_schema, mappings_path)
            self.project_maps.read()
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            logger.error(e)

        self.project_maps.pop('xmlns:cms')
        self.project_maps.pop('xmlns:xsi')
        self.project_maps.pop('xsi:schemaLocation')

        logger.info(f'Project {project_uname} mappings loaded')

    def check_dir_hierarchy(self):
        try:
            if not os.path.exists(self.library_path):
                os.mkdir(self.library_path)
                logger.info(f'Creating library forlder {self.library_path}')

            if not os.path.exists( os.path.join(self.library_path, 'projects') ) :
                os.mkdir(os.path.join(self.library_path, 'projects'))

            if not os.path.exists( os.path.join(self.library_path, 'media') ) :
                os.mkdir(os.path.join(self.library_path, 'media'))

            if not os.path.exists( os.path.join(self.library_path, 'trash') ) :
                os.mkdir(os.path.join(self.library_path, 'trash'))

            if not os.path.exists( os.path.join(self.library_path, 'trash', 'projects') ) :
                os.mkdir(os.path.join(self.library_path, 'trash', 'projects'))

            if not os.path.exists( os.path.join(self.library_path, 'trash', 'media') ) :
                os.mkdir(os.path.join(self.library_path, 'trash', 'media'))

        except Exception as e:
            logger.error("error: {} {}".format(type(e), e))

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
