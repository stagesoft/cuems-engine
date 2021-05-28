#!/usr/bin/env python3

# %%
import threading
import queue
from multiprocessing import Queue as MPQueue
from subprocess import CalledProcessError
import signal
import time
from os import path, getpid, remove
import pyossia as ossia
from uuid import uuid1
from functools import partial
from ast import literal_eval

from .CTimecode import CTimecode
import xmlschema.exceptions

from .cuems_editor.CuemsWsServer import CuemsWsServer
from .cuems_nodeconf.CuemsNodeConf import CuemsNodeConf
from .cuems_hwdiscovery.CuemsHwDiscovery import CuemsHWDiscovery
from .cuems_deploy.CuemsDeploy import CuemsDeploy

from .MtcListener import MtcListener
from .mtcmaster import libmtcmaster

from .log import logger
from .OssiaServer import OssiaServer, OSCConfData, MasterOSCQueryConfData, SlaveOSCQueryConfData, PlayerOSCConfData
from .Settings import Settings
from .CuemsScript import CuemsScript
from .CueList import CueList
from .Cue import Cue
from .AudioCue import AudioCue
from .VideoCue import VideoCue
from .VideoPlayer import VideoPlayer
from .DmxCue import DmxCue
from .ActionCue import ActionCue
from .XmlReaderWriter import XmlReader
from .ConfigManager import ConfigManager

CUEMS_CONF_PATH = '/etc/cuems/'


# %%
class CuemsEngine():
    '''
    Our main engine class. An object of this class runs all the inner
    logical part of communications with the WebSocket system as well as
    with the Ossia System to deal with the projects and execute them
    launching players, controlling their logics and so on...
    '''

    def __init__(self):
        logger.info('CUEMS ENGINE INITIALIZATION')
        # Main thread ids
        logger.info(f'Main thread PID: {getpid()}')

        # Running flag
        self.stop_requested = False

        self.test_running = False
        self.test_data = None
        self.test_thread = threading.Thread(target=self.test_thread_function, name='test_thread')

        self._editor_request_uuid = ''

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
        except Exception as e:
            logger.exception(f'Exception while loading config: {e}')
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
        if self.cm.amimaster:
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
        if (self.cm.amimaster):
            logger.info('Master node starting Websocket Server')
            settings_dict = {}
            settings_dict['session_uuid'] = str(uuid1())
            settings_dict['library_path'] = self.cm.library_path
            settings_dict['tmp_path'] = self.cm.tmp_path
            settings_dict['database_name'] = self.cm.database_name
            settings_dict['load_timeout'] = self.cm.node_conf['load_timeout']
            settings_dict['discovery_timeout'] = self.cm.node_conf['discovery_timeout']
            self.engine_queue = MPQueue()
            self.editor_queue = MPQueue()
            self.ws_server = CuemsWsServer(self.engine_queue, self.editor_queue, settings_dict, self.cm.network_mappings)
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
        else:
            logger.info('Slave node, no WS server needed')


        # OSSIA OSCQuery server
        self.ossia_server = OssiaServer(node_id=self.cm.node_conf['uuid'], 
                                        ws_port=self.cm.node_conf['oscquery_ws_port'], 
                                        osc_port=self.cm.node_conf['oscquery_osc_port'], 
                                        master = self.cm.amimaster)

        # Initial OSC nodes to tell ossia to configure
        OSC_ENGINE_CONF = { '/engine/command/load' : [ossia.ValueType.String, self.load_project_callback],
                            '/engine/command/loadcue' : [ossia.ValueType.String, self.load_cue_callback],
                            '/engine/command/go' : [ossia.ValueType.String, self.go_callback],
                            '/engine/command/gocue' : [ossia.ValueType.String, self.go_cue_callback],
                            '/engine/command/pause' : [ossia.ValueType.Impulse, self.pause_callback],
                            '/engine/command/stop' : [ossia.ValueType.Impulse, self.stop_callback],
                            '/engine/command/resetall' : [ossia.ValueType.Impulse, self.reset_all_callback],
                            '/engine/command/preload' : [ossia.ValueType.String, self.load_cue_callback],
                            '/engine/command/unload' : [ossia.ValueType.String, self.unload_cue_callback],
                            '/engine/command/hwdiscovery' : [ossia.ValueType.Impulse, self.hwdiscovery_callback],
                            '/engine/command/deploy' : [ossia.ValueType.String, self.deploy_callback],
                            '/engine/command/test' : [ossia.ValueType.String, self.test_callback],
                            '/engine/comms/type' : [ossia.ValueType.String, self.comms_callback],
                            '/engine/comms/subtype' : [ossia.ValueType.String, None],
                            '/engine/comms/action' : [ossia.ValueType.String, None],
                            '/engine/comms/action_uuid' : [ossia.ValueType.String, self.action_uuid_callback],
                            '/engine/comms/value' : [ossia.ValueType.String, None],
                            '/engine/comms/data' : [ossia.ValueType.String, None],
                            '/engine/status/load' : [ossia.ValueType.String, None],
                            '/engine/status/loadcue' : [ossia.ValueType.String, None],
                            '/engine/status/go' : [ossia.ValueType.String, None],
                            '/engine/status/gocue' : [ossia.ValueType.String, None],
                            '/engine/status/pause' : [ossia.ValueType.String, None],
                            '/engine/status/stop' : [ossia.ValueType.String, None],
                            '/engine/status/resetall' : [ossia.ValueType.String, None],
                            '/engine/status/preload' : [ossia.ValueType.String, None],
                            '/engine/status/unload' : [ossia.ValueType.String, None],
                            '/engine/status/hwdiscovery' : [ossia.ValueType.String, None],
                            '/engine/status/deploy' : [ossia.ValueType.String, None],
                            '/engine/status/test' : [ossia.ValueType.String, self.test_callback],
                            '/engine/status/timecode' : [ossia.ValueType.Int, None], 
                            '/engine/status/currentcue' : [ossia.ValueType.String, None],
                            '/engine/status/nextcue' : [ossia.ValueType.String, None],
                            '/engine/status/running' : [ossia.ValueType.Int, None]
                            }

        self.ossia_server.add_local_nodes(MasterOSCQueryConfData(device_name=self.cm.node_conf['uuid'], dictionary=OSC_ENGINE_CONF))

        # Check, start and OSC register video devices/players
        self._video_players = {}
        try:
            self.check_video_devs()
        except Exception as e:
            logger.error(f'Error checking & starting video devices...')
            logger.exception(e)
            logger.error(f'Exiting...')
            exit(-1)

        try:
            if self.cm.amimaster:
                time.sleep(1.5)
            else:
                time.sleep(0.5)
            self.add_nodes_oscquery_devices()
        except Exception as e:
            logger.exception(e)

        # Everything is ready now and should be working, let's run!
        while not self.stop_requested:
            time.sleep(0.1)

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
            if item['type'] not in ['error', 'initial_settings']:
                self.editor_queue.put({"type":"error", "action":None, 'action_uuid':self._editor_request_uuid, "value":"Response not recognized"})
                self._editor_request_uuid = ''
        except KeyError:
            try:
                try:
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'command'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = item['action']
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = item['action_uuid']
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = item['value']
                except KeyError as e:
                    logger.exception(f"/engine/comms/ parameters not copied because '{e}' does not exist in _oscquery_registered_nodes")

                try:
                    for device in self.ossia_server.oscquery_slave_devices:
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/type'][0].value = 'command'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action'][0].value = item['action']
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action_uuid'][0].value = item['action_uuid']
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/value'][0].value = item['value']
                except KeyError as e:
                    logger.exception(f"/engine/comms/ parameters not copied because '{e}' does not exist in oscquery_slave_registered_nodes")

                if item['action'] not in ['project_ready', 'hw_discovery', 'project_deploy']:
                    self.editor_queue.put({"type":"error", "action":None, 'action_uuid':self._editor_request_uuid, "value":"Command not recognized"})
                    self._editor_request_uuid = ''
                else:
                    if item['action'] == 'project_ready':
                        self._editor_request_uuid = item['action_uuid']
                        logger.info(f'Load project command received via WS. project: {item["value"]} request: {self._editor_request_uuid}')

                        self.load_project_callback(value = item['value'])
            
                    elif item['action'] == 'hw_discovery':
                        self._editor_request_uuid = item['action_uuid']
                        logger.info(f'HW discovery command received via WS. project: {item["value"]} request: {self._editor_request_uuid}')
                        try:
                            CuemsNodeConf()
                            CuemsHWDiscovery()
                        except:
                            self.editor_queue.put({'type':'error', 'action':'hw_discovery', 'action_uuid':self._editor_request_uuid, 'value':'HW discovery failed, check logs.'})
                            logger.error(f'HW discovery failed after editor request id: {self._editor_request_uuid}')
                            self._editor_request_uuid = ''
                        else:
                            self.editor_queue.put({'type':'hw_discovery', 'action_uuid':self._editor_request_uuid, 'value':'OK'})
                            self._editor_request_uuid = ''

                    elif item['action'] == 'project_deploy':
                        self._editor_request_uuid = item['action_uuid']
                        logger.info(f'Deploy command received via WS. Editor request uuid: {self._editor_request_uuid}')
                        self.deploy_callback(value = item['value'])

            except KeyError:
                logger.exception(f'Not recognized communications with WSServer. Queue msg received: {item}')

    #########################################################
    # Check functions
    def check_project_mappings(self):
        if self.cm.using_default_mappings:
            return True
        '''
        if self.cm.amimaster:
            nodes_to_check = self.cm.project_mappings['nodes']
        else:
        '''
        nodes_to_check = [self.cm.project_node_mappings]

        for node in nodes_to_check:
            for area, contents in node.items():
                if isinstance(contents, dict):
                    for section, elements in contents.items():
                        for element in elements:
                            if element['name'] not in self.cm.node_hw_outputs[f'{area}_{section}']:
                                raise Exception(f'Project {area} {section} mapping incorrect: {element["name"]} not present in node: {self.cm.node_conf["uuid"]}')

        return True
                
    def check_audio_devs(self):
        pass

    def check_video_devs(self):
        try:
            if self.cm.node_hw_outputs['video_outputs']:
                for index, item in enumerate(self.cm.node_hw_outputs['video_outputs']):
                    # Select the OSC port number for our new videoplayer
                    port = self.cm.osc_port_index['start']
                    while port in self.cm.osc_port_index['used']:
                        port += 2

                    self.cm.osc_port_index['used'].append(port)

                    player_id = item
                    self._video_players[player_id] = dict()

                    try:
                        # Assign a videoplayer object
                        self._video_players[player_id]['player'] = VideoPlayer( port, 
                                                                                item,
                                                                                self.cm.node_conf['videoplayer']['path'],
                                                                                self.cm.node_conf['videoplayer']['args'],
                                                                                '')
                    except Exception as e:
                        raise e

                    self._video_players[player_id]['player'].start()

                    # And dinamically attach it to the ossia for remote control it
                    self._video_players[player_id]['route'] = f'/players/videoplayer-{index}'

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

                    self.ossia_server.add_player_nodes( PlayerOSCConfData(  device_name=self._video_players[player_id]['route'], 
                                                                            host=self.cm.node_conf['osc_dest_host'], 
                                                                            in_port=port,
                                                                            out_port=port + 1, 
                                                                            dictionary=OSC_VIDEOPLAYER_CONF))
            else:
                logger.info('No video outputs detected.')
        except Exception as e:
            logger.exception(f'Exception raise when checking vidio outputs: {e}.')

    def quit_video_devs(self):
        for dev in self._video_players.values():
            key = f'{dev["route"]}/jadeo/cmd'
            try:
                self.ossia_server.osc_player_registered_nodes[key][0].value = 'quit'
            except Exception as e:
                logger.exception(e)

    def disconnect_video_devs(self):
        for dev in self._video_players.values():
            try:
                key = f'{dev["route"]}/jadeo/cmd'
                self.ossia_server.osc_player_registered_nodes[key][0].value = 'midi disconnect'
            except KeyError:
                logger.exception(f'Key error (cmd midi disconnect) in disconnect all method {key}')

    def unload_video_devs(self):
        for dev in self._video_players.values():
            try:
                key = f'{dev["route"]}/jadeo/load'
                # ossia._oscquery_registered_nodes[key][0].value = str(path.join(self._conf.library_path, 'media', self.media.file_name))
                self.ossia_server.osc_player_registered_nodes[key][0].value = ''
            except Exception as e:
                logger.debug(f'Exception while unloading video players: {e}')

    def check_dmx_devs(self):
        pass

    #########################################################
    # Ordered stopping
    def stop_all_threads(self):
        self.mtclistener.stop()
        self.mtclistener.join()

        try:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_stop(self.mtcmaster)
                libmtcmaster.MTCSender_release(self.mtcmaster)
                logger.info('MTC Master released')
        except Exception as e:
            logger.exception(f'MTC Master could not be released: {e}')

        try:
            self.disarm_all()
            logger.info('Cues disarmed')
        except Exception as e:
            logger.exception(f'Exception raised disarming all cues: {e}')

        try:
            self.quit_video_devs()
            logger.info('Quitted video devs')
        except Exception as e:
            logger.exception(f'Exception raised when quitting video devs: {e}')

        self.stop_requested = True

        try:
            if self.cm.amimaster:
                while not self.engine_queue.empty():
                    self.engine_queue.get()
                self.engine_queue_loop.join()
                self.engine_queue.close()

                while not self.editor_queue.empty():
                    self.editor_queue.get()
                self.editor_queue.close()
                logger.debug('IPC queues clean and closed')
        except Exception as e:
            logger.exception(f'Exception raised when cleaning and closing IPC queues: {e}')

        try:
            if self.cm.amimaster:
                self.ws_server.stop()
                logger.info(f'Ws-server thread finished')
        except Exception as e:
            logger.exception(f'Exception raised when stopping Ws-server: {e}')

        try:
            self.ossia_server.stop()
            self.ossia_server.join()
            logger.info(f'Ossia server thread finished')
        except Exception as e:
            logger.exception(f'Exception raised when stopping Ossia server: {e}')

        self.cm.join()

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
    # Usefull callbacks and functions
    def mtc_step_callback(self, mtc):
        # self.timecode(value = str(mtc))
        if self.go_offset:
            self.ossia_server._oscquery_registered_nodes['/engine/status/timecode'][0].value = mtc.milliseconds - self.go_offset

    def deploy_requests_reset(self, project_name='', tag_name=''):
        path_to_reset = path.join(self.cm.tmp_path, f'rsync_request_{project_name}_{tag_name}.log')
        with open(path_to_reset, 'w') as f:
            logger.info(f'Rsync requests log file {path_to_reset} emptied!!')

    def log_deploy_request(self, project_name='', tag_name='project', file_names=[]):
        if project_name:
            if tag_name == 'project':
                file_names = [  '/projects/' + project_name + '/script.xml\n',
                                '/projects/' + project_name + '/mappings.xml\n', 
                                '/projects/' + project_name + '/settings.xml\n']

            try:
                with open(path.join(self.cm.tmp_path, f'rsync_request_{project_name}_{tag_name}.log'), 'w') as f:
                    f.writelines(file_names)
            except Exception as e:
                logger.exception(f'Exception raised when writing rsync request log file: {e}')
                return False
            else:
                return True

    def try_deploy(self, project_name='', tag_name='project'):
        if project_name:
            try:
                deploy_manager = CuemsDeploy(library_path=self.cm.library_path, master_hostname=None, log_file='/tmp/cuems_rsync.log')

                if deploy_manager.sync(path.join(self.cm.tmp_path, f'rsync_request_{project_name}_{tag_name}.log')):
                    # If deploy is successful...
                    logger.info(f'Deploy sync successful from master')

                    self.ossia_server._oscquery_registered_nodes['/engine/status/deploy'][0].value = 'OK'

                    self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'OK'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_deploy'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Deploy succesful!'
                else:
                    # If deploy is NOT succesful...
                    logger.error(f'Deploy sync returned errors. {deploy_manager.errors}')

                    self.ossia_server._oscquery_registered_nodes['/engine/status/deploy'][0].value = 'ERROR'

                    self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_deploy'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = deploy_manager.errors
            except Exception as e:
                # If deploy raised any exception...
                logger.error(f'Deploy raised an exception {e} after master request id : {self._editor_request_uuid}')

                self.ossia_server._oscquery_registered_nodes['/engine/status/deploy'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_deploy'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Local deploy fail!'

            self.deploy_requests_reset(project_name = project_name, tag_name = tag_name)


    def set_show_lock_file(self):
        path = '/etc/cuems/show.lock'
        if  not path.isfile(path):
            try:
                with open(path, 'w') as results_file:
                    results_file.write(' ')
            except:
                self.logger.warning("Could not write show lock file")

    def remove_show_lock_file(self):
        path = '/etc/cuems/show.lock'
        if path.isfile(path):
            try:
                remove(path)
            except OSError:
                self.logger.warning("Could not delete master lock file")

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
    # OSC devices usefull methods
    def add_nodes_oscquery_devices(self):
        if self.cm.amimaster:
            logger.info(f'----- Master node trying to add slave nodes to OSCQuery tree -----')

            # Create OSC remote device routes for each slave node
            for name, node in self.cm.avahi_monitor.listener.osc_services.items():
                decoded_uuid = node.properties[b'uuid'].decode('utf8')
                if decoded_uuid != self.cm.node_conf['uuid']:
                    # Select the OSC out port number for our new slave node OSC
                    udp_port = self.cm.osc_port_index['start']
                    while udp_port in self.cm.osc_port_index['used']:
                        udp_port += 2

                    self.cm.osc_port_index['used'].append(udp_port)

                    self.ossia_server.add_slave_nodes( SlaveOSCQueryConfData(   device_name = decoded_uuid, 
                                                                                host = node.parsed_addresses()[0], 
                                                                                ws_port = int(node.port), 
                                                                                osc_port = udp_port) )
                
                    logger.info(f'Loaded OSCQuery tree for slave node {decoded_uuid}\n    ip : {node.parsed_addresses()[0]} ws : {node.port} udp : {udp_port}')

            logger.info(f'----- All slave nodes added to the OSC tree in some way -----')
        else:
            logger.info(f'----- Slave node trying to add master node to OSCQuery tree -----')

            # Create OSC remote device routes for each slave node
            for name, node in self.cm.avahi_monitor.listener.osc_services.items():
                if node.properties[b'node_type'] == b'master':
                    # Select the OSC out port number for our new slave node OSC
                    udp_port = self.cm.osc_port_index['start']
                    while udp_port in self.cm.osc_port_index['used']:
                        udp_port += 2

                    self.cm.osc_port_index['used'].append(udp_port)

                    decoded_uuid = node.properties[b'uuid'].decode('utf8')
                    self.ossia_server.add_master_node( SlaveOSCQueryConfData(  device_name = decoded_uuid, 
                                                                                host = node.parsed_addresses()[0], 
                                                                                ws_port = int(node.port), 
                                                                                osc_port = udp_port) )
                
                    logger.info(f'Loaded OSCQuery tree for master node {decoded_uuid}\n    ip : {node.parsed_addresses()[0]} ws : {node.port} udp : {udp_port}')
                    break

            logger.info(f'----- MASTER node added to the OSC tree in some way -----')

    ########################################################

    ########################################################
    # OSC messages handlers
    def load_project_callback(self, **kwargs):
        try:
            if kwargs['value'][-1] == '*':
                # if argument is marked is already treated...
                return
            else:
                # Mark back our load command on slaves
                self.ossia_server._oscquery_registered_nodes[f'/engine/command/load'][0].value = kwargs['value'] + '*'
        except IndexError:
            return

        logger.info(f'PROJECT READY/LOAD CALLBACK! -> PROJECT : {kwargs["value"]}')

        # As we only allow one project in show mode we dismantle whatever other was loaded previously to this one...
        logger.info(f'Unloading previous content on video players...')
        self.unload_video_devs()

        # Init working stuff...
        local_media_error = False
        slave_media_error = False

        # Call OSC load on all slaves:
        # by the moment we are using the direct /engine/command/load callback on the slaves
        if self.cm.amimaster:
            for device in self.ossia_server.oscquery_slave_devices.keys():
                try:
                    self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/type'][0].value = 'command'
                    self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action'][0].value = 'project_ready'
                    self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                    self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/value'][0].value = kwargs['value']

                    logger.info(f'Calling load project {kwargs["value"]} via OSC on slave node {device}')
                    self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/command/load'][0].value = kwargs['value']
                except Exception as e:
                    logger.exception(e)
        else:
            # Let's request a deploy of the project files
            self.log_deploy_request(project_name = kwargs['value'], tag_name = 'project')
            self.try_deploy(project_name=kwargs['value'], tag_name='project')

        # If there was already an script we discard it and restart the run engine
        if self.script:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.disarm_all()
            self.armedcues.clear()
            self.ongoing_cue = None
            self.next_cue_pointer = None
            self.go_offset = 0
            self.script = None

        # LOAD PROJECT SETTINGS
        try:
            self.cm.load_project_settings(kwargs["value"])
            # logger.info(self.cm.project_conf)
        except FileNotFoundError:
            '''Not loading project settings yet, so no need to check any further '''
            logger.info(f'Project settings file not found. Adopting defaults.')
        except:
            logger.info(f'Project settings error while loading. Adopting defaults.')

        # LOAD PROJECT MAPPINGS
        try:
            self.cm.load_project_mappings(kwargs["value"])
            logger.info('Project mappings load OK!')
            # logger.info(self.cm.project_mappings)
        except Exception as e:
            logger.info(f'Exception raised while loading project mappings: {type(e)} {e}')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Mapping files error while loading.'})
            else:
                logger.info(f'Project mappings file problem. Noted to get it from master.')

                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'mappings'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Mapping files error while loading.'
            return

        # CHECK PROJECT MAPPINGS
        try:
            if self.check_project_mappings():
                logger.info('Project mappings check OK!')
        except Exception as e:
            logger.exception(f'Wrong configuration on input/output mappings: {e}')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Wrong configuration on input/output mappings'})
            else:
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'mappings'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Wrong configuration on input/output mappings'
            return

        try:
            schema = path.join(self.cm.cuems_conf_path, 'script.xsd')
            xml_file = path.join(self.cm.library_path, 'projects', kwargs['value'], 'script.xml')
            reader = XmlReader( schema, xml_file )
            self.script = reader.read_to_objects()
        except FileNotFoundError:
            logger.error('Project script file not found')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Project script file not found'})
                self._editor_request_uuid = ''
            else:
                logger.info(f'Project script not found. Noted to get it from master.')
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'script_file_not_found'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Project script file not found'

        except xmlschema.exceptions.XMLSchemaException as e:
            logger.exception(f'XML error: {e}')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Script XML parsing error'})
                self._editor_request_uuid = ''
            else:
                logger.info(f'Project script XML exception.')
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'xml'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Script XML parsing error'

        except Exception as e:
            logger.error(f'Project script could not be loaded {e}')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Script could not be loaded'})
                self._editor_request_uuid = ''
            else:
                logger.info(f'Project script could not be loaded. Check logs.')
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Script could not be loaded'

        if self.script is None:
            logger.warning(f'Script could not be loaded. Check consistency and retry please.')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Script could not be loaded'})
            else:
                logger.info(f'Project script could not be loaded. Check logs.')
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Script could not be loaded'

            self._editor_request_uuid = ''
            return
        else:
            logger.info('Project script loaded OK!')
            self.script.unix_name = kwargs['value']

        try:
            media_fail_list = self.script_media_check()
        except Exception as e:
            logger.exception(f'Exception raised while performing media check: {e}')

        if media_fail_list:
            logger.error(f'Media not found for project: {kwargs["value"]} !!!')

            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'subtype':'media', 'data':list(media_fail_list.keys())})
            else:
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'media'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Media not found'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/data'][0].value = list(media_fail_list.keys())

            ''' By the moment we allow the show mode to get ready even if there are media files missing...
            self.script = None
            self._editor_request_uuid = ''
            return
            '''
            local_media_error = True
        else:
            logger.info('Media check OK!')

        try:
            #### CHECK LOAD PROCESS ON SLAVES... :
            if self.cm.amimaster:
                # If we are master, prior to process the script cuelist in local, we check the load process on the slaves...
                node_ok_list = []
                node_error_dict = {}
                logger.info(f'I\'m master. Waiting for slaves to load...')
                while (len(node_ok_list) + len(node_error_dict)) < len(self.ossia_server.oscquery_slave_devices):
                    ok_count = 0
                    for device in self.ossia_server.oscquery_slave_devices:
                        try:
                            if self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/load'][0].value == 'ERROR':
                                node_error_dict[device] = self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/comms/subtype'][0].value + self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/comms/data'][0].value
                                # Reset the status field
                                self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/load'][0].value == ''
                            elif self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/load'][0].value == 'OK':
                                if device not in node_ok_list:
                                    logger.info(f'Slave {device} load successfull, OK!')
                                    # Reset the status field
                                    self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/load'][0].value == ''
                                    node_ok_list.append(device)
                        except KeyError:
                            # a KeyError means that OSC route is not found because the slave is not present in OSC tree
                            node_error_dict[device] = 'osc'
                            # Reset the status field

                    time.sleep(0.05)

                if node_error_dict:
                    # if only media errors we can continue (by now)...
                    for item in node_error_dict.values():
                        if item[0:5] != 'media':
                            # Some slave could not load the project
                            self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'subtype':'slave_errors', 'value':f'Errors loading project on nodes: {node_error_dict}'})

                            self._editor_request_uuid = ''
                            self.script = None
                            # if there is any error on a slave different than media missing, we cancel the project loading and show mode change...
                            return
                        else:
                            # Some slave loaded the project with media errors
                            slave_media_error = True

                # if slaves are correctly loaded (even with missing media), we, master, process now the script cuelist
                self.initial_cuelist_process(self.script.cuelist)

            else:
                # If we are slave and everthing is OK till here, we perform the initial process of the script
                self.initial_cuelist_process(self.script.cuelist)
        except Exception as e:
            logger.error(f"Error processing script data. Can't be loaded.")
            logger.exception(e)
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':"Error processing script data. Can't be loaded."})
            else:
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = "Error processing script data. Can't be loaded."

            self._editor_request_uuid = ''
            self.script = None
            return

        # Then we force-arm the first item in the main list
        self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
        # And get it ready to wait a GO command
        self.next_cue_pointer = self.script.cuelist.contents[0]
        self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = self.next_cue_pointer.uuid

        # Start MTC!
        if self.cm.amimaster:
            libmtcmaster.MTCSender_play(self.mtcmaster)

        # Everything went OK while loading the project locally...
        if local_media_error: # For slaves...
            logger.info(f'Project loaded with local media errors...')
        else:
            if self.cm.amimaster:
                if slave_media_error:
                    logger.warning(f'Project loaded OK but some slaves could not load all their media...')
                    self.editor_queue.put({'type':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'OK_deploy_needed'})
                else:
                    logger.info(f'Project loaded OK.')
                    self.editor_queue.put({'type':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'OK'})

            else:
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'OK'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'OK'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'OK'

        self._editor_request_uuid = ''

    def load_cue_callback(self, **kwargs):
        logger.info(f'LOAD CUE CALLBACK! -> CUE : {kwargs["value"]}')

        cue_to_load = self.script.find(kwargs['value'])

        if cue_to_load != None:
            if cue_to_load not in self.armedcues:
                cue_to_load.arm(self.cm, self.ossia_server, self.armedcues)

    def unload_cue_callback(self, **kwargs):
        logger.info(f'UNLOAD CUE CALLBACK! -> CUE : {kwargs["value"]}')

        cue_to_unload = self.script.find(kwargs['value'])

        if cue_to_unload != None:
            if cue_to_unload in self.armedcues:
                cue_to_unload.disarm(self.ossia_server)

    def go_cue_callback(self, **kwargs):
        logger.info(f'GO CUE CALLBACK! -> ARGS : {kwargs["value"]}')

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
        try:
            if kwargs['value'][-1] == '*':
                return
        except IndexError:
            pass

        # Mark back our load command on slaves
        if self.ossia_server._oscquery_registered_nodes[f'/engine/command/go'][0].value and self.ossia_server._oscquery_registered_nodes[f'/engine/command/go'][0].value[-1] != '*':
            self.ossia_server._oscquery_registered_nodes[f'/engine/command/go'][0].value = kwargs['value'] + '*'

        logger.info(f'GO CALLBACK! -> ARGS : {kwargs["value"]}')

        if self.script:
            # Call OSC go on all slaves:
            # by the moment we are using the direct /engine/command/go callback on the slaves
            if self.cm.amimaster:
                for device in self.ossia_server.oscquery_slave_devices.keys():
                    try:
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/type'][0].value = 'command'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action'][0].value = 'go'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/value'][0].value = ''

                        logger.info(f'Calling GO CALLBACK via OSC on slave node {device}')
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/command/go'][0].value = 'go'
                    except Exception as e:
                        logger.exception(e)

            if not self.ongoing_cue:
                cue_to_go = self.script.cuelist.contents[0]
            else:
                if self.next_cue_pointer:
                    cue_to_go = self.next_cue_pointer
                else:
                    logger.info(f'Reached end of script. Last cue was {self.ongoing_cue.__class__.__name__} {self.ongoing_cue.uuid}')
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
                self.ossia_server._oscquery_registered_nodes['/engine/status/currentcue'][0].value = self.ongoing_cue.uuid
                if self.next_cue_pointer:
                    self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = self.next_cue_pointer.uuid
                else:
                    self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = ""

                self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value = 1
        else:
            logger.warning('No script loaded, cannot process GO command.')

    def pause_callback(self, **kwargs):
        logger.info(f'PAUSE CALLBACK! -> ARGS : {kwargs["value"]}')
        try:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_pause(self.mtcmaster)
            self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value = int(not self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value)
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def stop_callback(self, **kwargs):
        logger.info(f'STOP CALLBACK! -> ARGS : {kwargs["value"]}')
        try:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.go_offset = 0
            self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value = 0
        except:
            logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all_callback(self, **kwargs):
        logger.info(f'RESET ALL CALLBACK! -> ARGS : {kwargs["value"]}')
        try:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.disarm_all()
            self.armedcues.clear()
            self.disconnect_video_devs()
            self.unload_video_devs()
            self.ongoing_cue = None
            self.go_offset = 0

            self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value = 0

            if self.script:
                self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
                self.next_cue_pointer = self.script.cuelist.contents[0]
                self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = self.next_cue_pointer.uuid

                self.ossia_server._oscquery_registered_nodes['/engine/status/currentcue'][0].value = ""
                self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = self.script.cuelist.contents[0].uuid
            if self.cm.amimaster:
                libmtcmaster.MTCSender_play(self.mtcmaster)

        except Exception as e:
            logger.exception(e)

    def hwdiscovery_callback(self, **kwargs):
        try:
            CuemsNodeConf()
            CuemsHWDiscovery()
        except Exception as e:
            logger.exception(e)

    def deploy_callback(self, **kwargs):
        try:
            if kwargs['value'][-1] == '*':
                return
        except IndexError:
            pass

        # Mark back our load command on slaves
        if self.ossia_server._oscquery_registered_nodes[f'/engine/command/deploy'][0].value and self.ossia_server._oscquery_registered_nodes[f'/engine/command/deploy'][0].value[-1] != '*':
            self.ossia_server._oscquery_registered_nodes[f'/engine/command/deploy'][0].value = kwargs['value'] + '*'

        logger.info(f'DEPLOY CALLBACK! -> ARGS : {kwargs["value"]}')

        if not self.script and self.cm.amimaster:
            # First the user should load/ready a project to try to deploy it... ERROR to UI!
            self.editor_queue.put({'type':'error', 'action':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':'Project not yet loaded!'})
            logger.error(f'Deploy request failed because project is not yet loaded, request id: {self._editor_request_uuid}')
            self._editor_request_uuid = ''
            return
        
        try:
            # Check local needs for script media
            media_fail_list = self.script_media_check()
        except Exception as e:
            logger.exception(f'Exception raised while performing media check: {type(e)} {e}')
        
        if media_fail_list:
            if self.cm.amimaster:
                # If local media check failed and I'm master... ERROR to UI!
                self.editor_queue.put({'type':'error', 'action':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':'Master local media check failed, check logs.'})
                logger.error(f'Master local media check failed after deploy ws request, request id: {self._editor_request_uuid}')
            else:
                deploy_request_list = []
                for item in list(media_fail_list.keys()):
                    deploy_request_list.append('/media/' + item + '\n')

                self.log_deploy_request(project_name=self.script.unix_name, tag_name='media', file_names=deploy_request_list)
            
                # If local media check failed and I'm slave... Try to deploy from master...
                try:
                    self.try_deploy(project_name=self.script.unix_name, tag_name='media')
                except Exception as e:
                    logger.exception(f'Exception raised while performing deploy: {e}')
                    self.ossia_server._oscquery_registered_nodes['/engine/status/deploy'][0].value = 'ERROR'

                    self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_deploy'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Deploy raised and exception on this slave!'
                else:
                    self.ossia_server._oscquery_registered_nodes['/engine/status/deploy'][0].value = 'OK'

                    self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'OK'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_deploy'
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                    self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Deploy went OK on this slave!'

        else:
            if self.cm.amimaster:
                ''' LAUNCH SLAVES DEPLOYS '''
                # Call OSC go on all slaves:
                # by the moment we are using the direct /engine/command/deploy callback on the slaves
                for device in self.ossia_server.oscquery_slave_devices.keys():
                    try:
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/type'][0].value = 'command'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action'][0].value = 'deploy'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/value'][0].value = ''

                        logger.info(f'Calling DEPLOY via OSC on slave node {device}')
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/command/deploy'][0].value = self.script.unix_name
                    except Exception as e:
                        logger.exception(e)

                ''' CHECK SLAVES DEPLOYS '''
                # Check slaves deploy return
                node_error_dict = {}
                node_ok_list = []
                logger.info(f'I\'m master. Waiting for slaves to deploy...')
                while len(node_error_dict) + len(node_ok_list) < len(self.ossia_server.oscquery_slave_devices):
                    ok_count = 0
                    for device in self.ossia_server.oscquery_slave_devices:
                        if self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == 'ERROR':
                            node_error_dict[device] = self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/comms/value'][0].value
                            # Reset the status field
                            self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == ''
                        elif self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == 'OK':
                            logger.info(f'Slave {device} deploy successfull, OK!')
                            # Reset the status field
                            self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == ''
                            node_ok_list.append(device)

                    time.sleep(0.05)

                if node_error_dict:
                    # Some slave could not load the project
                    logger.error(f'Deploy failed in some slave node. Editor request id: {self._editor_request_uuid} Node errors: {node_error_dict}')
                    self.editor_queue.put({'type':'error', 'action':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':f'Errors deploying on nodes: {node_error_dict}'})
                else:
                    logger.info(f'Deploy process completed succesfully on all slave nodes...')
                    self.editor_queue.put({'type':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':'OK'})

            else:
                # Deploy is not needed on this slave...
                logger.info(f'Deploy requested from master but it is not needed on this slave')

                self.ossia_server._oscquery_registered_nodes['/engine/status/deploy'][0].value = 'OK'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'OK'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_deploy'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Deploy not needed on this slave!'

        self._editor_request_uuid = ''

    def comms_callback(self, **kwargs):
        logger.info(f'COMMS CALLBACK! -> ARGS : {kwargs["value"]}')

        if self.cm.amimaster:
            for device in self.ossia_server.oscquery_slave_devices:
                logger.debug(f'COMMS CALLBACK: {kwargs["value"]}\ntype : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/type"][0].value} // '
                            + f'action : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/action"][0].value} // '
                            + f'action_uuid : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/action_uuid"][0].value} // '
                            + f'value : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/value"][0].value}')
        else:
            logger.debug(f'COMMS CALLBACK: {kwargs["value"]}\ntype : {self.ossia_server._oscquery_registered_nodes["/engine/comms/type"][0].value} // '
                        + f'action : {self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value} // '
                        + f'action_uuid : {self.ossia_server._oscquery_registered_nodes["/engine/comms/action_uuid"][0].value} // '
                        + f'value : {self.ossia_server._oscquery_registered_nodes["/engine/comms/value"][0].value}')

            if self.ossia_server._oscquery_registered_nodes["/engine/comms/type"][0].value == 'command' and self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value == 'go':
                self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value == 'command_done'
                self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value == 'go_done'
                self.go_callback()

    def action_uuid_callback(self, **kwargs):
        self._editor_request_uuid = kwargs['value']

    def test_callback(self, **kwargs):
        logger.info(f'TEST CALLBACK! -> ARGS : {kwargs["value"]}')

        '''OSC callback for internal test porpouses'''
        self.test_data = kwargs['value']

        if self.cm.amimaster:
            try:
                self.editor_command_callback(item=literal_eval(self.test_data))
            except Exception as e:
                logger.exception(f'Exception raised in test_thread: {e}')
        else:
            try:
                d = literal_eval(self.test_data)
                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'test'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = d['action']
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = d['action_uuid']
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = d['value']
            except Exception as e:
                logger.exception(f'Exception raised in test_thread: {e}')

    def test_thread_function(self):
        try:
            self.editor_command_callback(item=literal_eval(self.test_data))
        except Exception as e:
            logger.exception(f'Exception raised in test_thread: {e}')

    ########################################################

    ########################################################
    # Script treating methods
    def script_media_check(self):
        '''
        Checks for all the media files referred in the script.
        Returns the list of those which were not found in the media library.
        '''
        if self.cm.amimaster:
            media_list = self.script.get_media()
        else:
            media_list = self.script.get_own_media(config=self.cm)

        for key, value in media_list.copy().items():
            if path.isfile(path.join(self.cm.library_path, 'media', key)):
                media_list.pop(key)

        if media_list:
            string = f'These media files could not be found:'
            for filename, cue in media_list.items():
                string += f'\n{type(cue)} : {filename} : cue_uuid : {cue.uuid}'
            logger.error(string)

        return media_list
        
    def initial_cuelist_process(self, cuelist, caller = None):
        ''' 
        Review all the items recursively to update target uuids and objects
        and to load all the "loaded" flagged
        '''
        try:
            for index, item in enumerate(cuelist.contents):
                if item.check_mappings(self.cm):
                    if isinstance(item, VideoCue) and item._local:
                        try:
                            for output in item.outputs:
                                # TO DO : add support for multiple outputs
                                # video_player_id = self.cm.get_video_player_id(output['output_name'])
                                video_player_id = self.cm.get_video_player_id(output['output_name'][37:])
                                item._player = self._video_players[video_player_id]['player']
                                item._osc_route = self._video_players[video_player_id]['route']
                        except Exception as e:
                            logger.exception(e)
                            raise e
                else:
                    raise Exception(f"Cue outputs badly assigned in cue : {item.uuid}")

                if item.loaded and not item in self.armedcues and item._local:
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
            item.disarm(self.ossia_server)


    ########################################################
