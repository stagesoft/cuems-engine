#!/usr/bin/env python3

# %%
import threading
import time
from os import path
import pyossia as ossia
from ast import literal_eval
import xmlschema.exceptions

from cuemsutils.log import Logger
from cuemsutils.cues import CueList, VideoCue, ActionCue
from cuemsutils.xml.XmlReaderWriter import XmlReader

from .tools.mtcmaster import libmtcmaster
from .tools.CuemsDeploy import CuemsDeploy
from .tools.communicate import hwdiscovery_callback

from .OssiaServer import OssiaServer, MasterOSCQueryConfData, SlaveOSCQueryConfData, PlayerOSCConfData

from .ControllerEngine import ControllerEngine

CUEMS_CONF_PATH = '/etc/cuems/'


# %%
class CuemsEngine(ControllerEngine):
    

    def __init__(self):

        self.test_running = False
        self.test_data = None
        self.test_thread = threading.Thread(target=self.test_thread_function, name='test_thread')
        self._editor_request_uuid = ''

        # Our empty script object
        self.armedcues = list()

        # MTC master object creation through bound library and open port
        if self.cm.amimaster:
            self.mtcmaster = libmtcmaster.MTCSender_create()

        # MTC listener (could be usefull)
 
        # OSSIA OSCQuery server
        self.ossia_server = OssiaServer(node_id=self.cm.node_conf['uuid'], 
                                        ws_port=self.cm.node_conf['oscquery_ws_port'], 
                                        osc_port=self.cm.node_conf['oscquery_osc_port'], 
                                        master = self.cm.amimaster)

        # DEV: This is a temporary solution to resend signals from main to remote engines
        # DEV: Status nodes are used in the current implementation to check the status of the engine from the web interface
        # DEV: Should be substituted by a more robust system based on pynng
        # Initial OSC nodes to tell ossia to configure
        OSC_ENGINE_CONF = {
            '/engine/command/load' : [ossia.ValueType.String, self.load_project_callback],
            '/engine/command/loadcue' : [ossia.ValueType.String, self.load_cue_callback],
            '/engine/command/go' : [ossia.ValueType.String, self.go_callback],
            '/engine/command/gocue' : [ossia.ValueType.String, self.go_cue_callback],
            '/engine/command/pause' : [ossia.ValueType.Impulse, self.pause_callback],
            '/engine/command/stop' : [ossia.ValueType.Impulse, self.stop_callback],
            '/engine/command/resetall' : [ossia.ValueType.String, self.reset_all_callback],
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
            '/engine/comms/data' : [ossia.ValueType.String, None]
                            }

        self.ossia_server.add_local_nodes(MasterOSCQueryConfData(device_name=self.cm.node_conf['uuid'], dictionary=OSC_ENGINE_CONF))

        try:
            if self.cm.amimaster:
                time.sleep(1.5)
            else:
                time.sleep(0.5)
            self.add_nodes_oscquery_devices()
        except Exception as e:
            Logger.exception(e)

        # Everything is ready now and should be working, let's run!
        while not self.stop_requested:
            time.sleep(0.1)

        self.stop_all_threads()

    def editor_command_callback(self, item):
        try:
            self._editor_request_uuid = item['action_uuid']
        except KeyError:
            self.error_to_editor(self._editor_request_uuid, "No action uuid submitted")
            return

        try:
            if item['type'] not in ['error', 'initial_settings']:
                self.error_to_editor(self._editor_request_uuid, "Response not recognized")
                self._editor_request_uuid = ''
        except KeyError:
            try:
                try:
                    self.assign_nodes_values('command', item)
                except KeyError as e:
                    Logger.exception(f"/engine/comms/ parameters not copied because '{e}' does not exist in _oscquery_registered_nodes")

                try:
                    for device in self.ossia_server.oscquery_slave_devices:
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/type'][0].value = 'command'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action'][0].value = item['action']
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action_uuid'][0].value = item['action_uuid']
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/value'][0].value = item['value']

                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/value'][0].value = '{"cmd": "command", "action": "' + item['action'] + '", "action_uuid": "' + item['action_uuid'] + '", "value": "' + item['value'] + '"}'
                except KeyError as e:
                    Logger.exception(f"/engine/comms/ parameters not copied because '{e}' does not exist in oscquery_slave_registered_nodes")

                if item['action'] not in ['project_ready', 'hw_discovery', 'project_deploy']:
                    self.error_to_editor(self._editor_request_uuid, "Command not recognized")
                    self._editor_request_uuid = ''
                else:
                    if item['action'] == 'project_ready':
                        self._editor_request_uuid = item['action_uuid']
                        Logger.info(f'Load project command received via WS. project: {item["value"]} request: {self._editor_request_uuid}')

                        self.load_project_callback(value = item['value'])
            
                    elif item['action'] == 'hw_discovery':
                        self._editor_request_uuid = item['action_uuid']
                        Logger.info(f'HW discovery command received via WS. project: {item["value"]} request: {self._editor_request_uuid}')
                        try:
                            hwdiscovery_callback()
                        except:
                            self.editor_queue.put({'type':'error', 'action':'hw_discovery', 'action_uuid':self._editor_request_uuid, 'value':'HW discovery failed, check logs.'})
                            Logger.error(f'HW discovery failed after editor request id: {self._editor_request_uuid}')
                            self._editor_request_uuid = ''
                        else:
                            self.editor_queue.put({'type':'hw_discovery', 'action_uuid':self._editor_request_uuid, 'value':'OK'})
                            self._editor_request_uuid = ''

                    elif item['action'] == 'project_deploy':
                        self._editor_request_uuid = item['action_uuid']
                        Logger.info(f'Deploy command received via WS. Editor request uuid: {self._editor_request_uuid}')
                        self.deploy_callback(value = item['value'])

            except KeyError:
                Logger.exception(f'Not recognized communications with WSServer. Queue msg received: {item}')

    #########################################################

    #########################################################
    # Ordered stopping
    def stop_all_threads(self):

        try:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_stop(self.mtcmaster)
                libmtcmaster.MTCSender_release(self.mtcmaster)
                Logger.info('MTC Master released')
        except Exception as e:
            Logger.exception(f'MTC Master could not be released: {e}')

        try:
            self.ossia_server.stop()
            self.ossia_server.join()
            Logger.info(f'Ossia server thread finished')
        except Exception as e:
            Logger.exception(f'Exception raised when stopping Ossia server: {e}')


    #########################################################
    # Usefull callbacks and functions
    def _update_deploy_status(self, status: str, message: str, device: str = None):
        """Helper method to update deployment status across nodes"""
        if device:
            self.set_slave_node_value(device, '/engine/status', 'deploy', status)
            self.assign_slave_nodes_values(device, {
                'type': 'OK' if status == 'OK' else 'error',
                'action': 'project_deploy',
                'action_uuid': self._editor_request_uuid,
                'value': message
            })
        else:
            self.set_node_value('/engine/status', 'deploy', status)
            self.assign_nodes_values({
                'type': 'OK' if status == 'OK' else 'error',
                'action': 'project_deploy',
                'action_uuid': self._editor_request_uuid,
                'value': message
            })

    def _handle_deploy_success(self, device: str = None):
        """Helper method to handle successful deployment"""
        if device:
            Logger.info(f'Slave {device} deploy successful, OK!')
            self._update_deploy_status('OK', 'Deploy went OK on this slave!', device)
        else:
            Logger.info(f'Deploy sync successful from master')
            self._update_deploy_status('OK', 'Deploy successful!')

    def _handle_deploy_error(self, error_msg: str, device: str = None):
        """Helper method to handle deployment errors"""
        if device:
            Logger.error(f'Deploy failed on slave {device}: {error_msg}')
            self._update_deploy_status('ERROR', error_msg, device)
        else:
            Logger.error(f'Deploy sync returned errors. {error_msg}')
            self._update_deploy_status('ERROR', error_msg)

    def try_deploy(self, project_name='', tag_name='project'):
        if project_name:
            try:
                deploy_manager = CuemsDeploy(
                    library_path=self.cm.library_path, master_hostname=None,
                    log_file='/tmp/cuems_rsync.log'
                )

                if deploy_manager.sync(path.join(self.cm.tmp_path, f'rsync_request_{project_name}_{tag_name}.log')):
                    self._handle_deploy_success()
                else:
                    self._handle_deploy_error(deploy_manager.errors)
            except Exception as e:
                Logger.error(f'Deploy raised an exception {e} after master request id : {self._editor_request_uuid}')
                self._handle_deploy_error('Local deploy fail!')

            self.deploy_requests_reset(project_name=project_name, tag_name=tag_name)

    def deploy_callback(self, **kwargs):
        try:
            if kwargs['value'][-1] == '*':
                return
        except IndexError:
            pass

        # Mark back our load command on slaves
        if self.ossia_server._oscquery_registered_nodes[f'/engine/command/deploy'][0].value and self.ossia_server._oscquery_registered_nodes[f'/engine/command/deploy'][0].value[-1] != '*':
            self.ossia_server._oscquery_registered_nodes[f'/engine/command/deploy'][0].value = kwargs['value'] + '*'

        Logger.info(f'DEPLOY CALLBACK! -> ARGS : {kwargs["value"]}')

        if not self.script and self.cm.amimaster:
            self.editor_queue.put({'type':'error', 'action':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':'Project not yet loaded!'})
            Logger.error(f'Deploy request failed because project is not yet loaded, request id: {self._editor_request_uuid}')
            self._editor_request_uuid = ''
            return
        
        try:
            media_fail_list = self.script_media_check()
        except Exception as e:
            Logger.exception(f'Exception raised while performing media check: {type(e)} {e}')
        
        if media_fail_list:
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':'Master local media check failed, check logs.'})
                Logger.error(f'Master local media check failed after deploy ws request, request id: {self._editor_request_uuid}')
            else:
                deploy_request_list = []
                for item in list(media_fail_list.keys()):
                    deploy_request_list.append('/media/' + item + '\n')

                self.log_deploy_request(project_name=self.script.unix_name, tag_name='media', file_names=deploy_request_list)
            
                try:
                    self.try_deploy(project_name=self.script.unix_name, tag_name='media')
                except Exception as e:
                    Logger.exception(f'Exception raised while performing deploy: {e}')
                    self._handle_deploy_error('Deploy raised an exception on this slave!')
                else:
                    self._handle_deploy_success()

        else:
            if self.cm.amimaster:
                ''' LAUNCH SLAVES DEPLOYS '''
                device_values = {
                    'action': 'deploy',
                    'action_uuid': self._editor_request_uuid,
                    'value': ''
                }
                for device in self.ossia_server.oscquery_slave_devices.keys():
                    try:
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/type'][0].value = 'command'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action'][0].value = 'deploy'
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/comms/value'][0].value = ''

                        Logger.info(f'Calling DEPLOY via OSC on slave node {device}')
                        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/engine/command/deploy'][0].value = self.script.unix_name
                    except Exception as e:
                        Logger.exception(e)

                ''' CHECK SLAVES DEPLOYS '''
                node_error_dict = {}
                node_ok_list = []
                Logger.info(f'I\'m master. Waiting for slaves to deploy...')
                while len(node_error_dict) + len(node_ok_list) < len(self.ossia_server.oscquery_slave_devices):
                    ok_count = 0
                    for device in self.ossia_server.oscquery_slave_devices:
                        if self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == 'ERROR':
                            node_error_dict[device] = self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/comms/value'][0].value
                            self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == ''
                        elif self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == 'OK':
                            Logger.info(f'Slave {device} deploy successful, OK!')
                            self.ossia_server._oscquery_registered_nodes[f'/{device}/engine/status/deploy'][0].value == ''
                            node_ok_list.append(device)

                    time.sleep(0.05)

                if node_error_dict:
                    Logger.error(f'Deploy failed in some slave node. Editor request id: {self._editor_request_uuid} Node errors: {node_error_dict}')
                    self.editor_queue.put({'type':'error', 'action':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':f'Errors deploying on nodes: {node_error_dict}'})
                else:
                    Logger.info(f'Deploy process completed successfully on all slave nodes...')
                    self.editor_queue.put({'type':'project_deploy', 'action_uuid':self._editor_request_uuid, 'value':'OK'})

            else:
                Logger.info(f'Deploy requested from master but it is not needed on this slave')
                self._handle_deploy_success()

        self._editor_request_uuid = ''

    ########################################################
    # OSC devices usefull methods
    def add_nodes_oscquery_devices(self): # DEV looks like a ConfigManager or OssiaServer method
        if self.cm.amimaster:
            Logger.info(f'----- Master node trying to add slave nodes to OSCQuery tree -----')

            # Create OSC remote device routes for each slave node
            for name, node in self.cm.avahi_monitor.listener.osc_services.items():
                decoded_uuid = node.properties[b'uuid'].decode('utf8')
                if decoded_uuid != self.cm.node_conf['uuid']:
                    # Select the OSC out port number for our new slave node OSC
                    udp_port = self.cm.osc_port_index['start']
                    while udp_port in self.cm.osc_port_index['used']:
                        udp_port += 2

                    self.cm.osc_port_index['used'].append(udp_port)

                    self.ossia_server.add_slave_nodes(
                        SlaveOSCQueryConfData(
                            device_name = decoded_uuid, 
                            host = node.parsed_addresses()[0], 
                            ws_port = int(node.port), 
                            osc_port = udp_port
                        )
                    )
                
                    Logger.info(f'Loaded OSCQuery tree for slave node {decoded_uuid}\n    ip : {node.parsed_addresses()[0]} ws : {node.port} udp : {udp_port}')

            Logger.info(f'----- All slave nodes added to the OSC tree in some way -----')
        else:
            Logger.info(f'----- Slave node trying to add master node to OSCQuery tree -----')

            # Create OSC remote device routes for each slave node
            for name, node in self.cm.avahi_monitor.listener.osc_services.items():
                if node.properties[b'node_type'] == b'master':
                    # Select the OSC out port number for our new slave node OSC
                    udp_port = self.cm.osc_port_index['start']
                    while udp_port in self.cm.osc_port_index['used']:
                        udp_port += 2

                    self.cm.osc_port_index['used'].append(udp_port)

                    decoded_uuid = node.properties[b'uuid'].decode('utf8')
                    self.ossia_server.add_master_node(
                        SlaveOSCQueryConfData(
                            device_name = decoded_uuid, 
                            host = node.parsed_addresses()[0], 
                            ws_port = int(node.port), 
                            osc_port = udp_port
                        )
                    )
                
                    Logger.info(f'Loaded OSCQuery tree for master node {decoded_uuid}\n    ip : {node.parsed_addresses()[0]} ws : {node.port} udp : {udp_port}')
                    break

            Logger.info(f'----- MASTER node added to the OSC tree in some way -----')

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
                self.ossia_server._oscquery_registered_nodes['/engine/command/load'][0].value = kwargs['value'] + '*'
        except IndexError:
            return

        Logger.info(f'PROJECT READY/LOAD CALLBACK! -> PROJECT : {kwargs["value"]}')

        # As we only allow one project in show mode we dismantle whatever other was loaded previously to this one...
        Logger.info(f'Unloading previous content on video players...')
        self.unload_video_devs()

        # Init working stuff...
        local_media_error = False
        slave_media_error = False

        # Call OSC load on all slaves:
        # by the moment we are using the direct /engine/command/load callback on the slaves
        if self.cm.amimaster:
            device_values = {
                'action': 'project_ready',
                'action_uuid': self._editor_request_uuid,
                'value': kwargs['value']
            }
            for device in self.ossia_server.oscquery_slave_devices.keys():
                try:
                    self.assign_slave_nodes_values(device, 'command', device_values)

                    Logger.info(f'Calling load project {kwargs["value"]} via OSC on slave node {device}')
                    self.set_slave_node_value(device, '/engine/command', 'load', kwargs['value'])
                except Exception as e:
                    Logger.exception(e)
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
            # Logger.info(self.cm.project_conf)
        except FileNotFoundError:
            '''Not loading project settings yet, so no need to check any further '''
            Logger.info(f'Project settings file not found. Adopting defaults.')
        except:
            Logger.info(f'Project settings error while loading. Adopting defaults.')

        # LOAD PROJECT MAPPINGS
        try:
            self.cm.load_project_mappings(kwargs["value"])
            Logger.info('Project mappings load OK!')
            # Logger.info(self.cm.project_mappings)
        except Exception as e:
            Logger.info(f'Exception raised while loading project mappings: {type(e)} {e}')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Mapping files error while loading.'})
            else:
                Logger.info(f'Project mappings file problem. Noted to get it from master.')
                self.set_node_value('/engine/status', 'load', 'ERROR')
                self.assign_nodes_values({
                    'type': 'error',
                    'subtype': 'mappings',
                    'action': 'project_ready',
                    'action_uuid': self._editor_request_uuid,
                    'value': 'Mapping files error while loading.'
                })
            return

        # THIS LOADS THE SCRIPT
        try:
            self.read_script(kwargs['value'])
        except FileNotFoundError:
            Logger.error('Project script file not found')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Project script file not found'})
                self._editor_request_uuid = ''
            else:
                Logger.info(f'Project script not found. Noted to get it from master.')
                self.set_node_value('/engine/status', 'load', 'ERROR')
                self.assign_nodes_values({
                    'type': 'error',
                    'subtype': 'script_file_not_found',
                    'action': 'project_ready',
                    'action_uuid': self._editor_request_uuid,
                    'value': 'Project script file not found'
                })
        except xmlschema.exceptions.XMLSchemaException as e:
            Logger.exception(f'XML error: {e}')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Script XML parsing error'})
                self._editor_request_uuid = ''
            else:
                Logger.info(f'Project script XML exception.')
                self.set_node_value('/engine/status', 'load', 'ERROR')
                self.assign_nodes_values({
                    'type': 'error',
                    'subtype': 'xml',
                    'action': 'project_ready',
                    'action_uuid': self._editor_request_uuid,
                    'value': 'Script XML parsing error'
                })

        except Exception as e:
            Logger.error(f'Project script could not be loaded {e}')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Script could not be loaded'})
                self._editor_request_uuid = ''
            else:
                Logger.info(f'Project script could not be loaded. Check logs.')
                self.set_node_value('/engine/status', 'load', 'ERROR')
                self.assign_nodes_values({
                    'type': 'error',
                    'subtype': 'error',
                    'action': 'project_ready',
                    'action_uuid': self._editor_request_uuid,
                    'value': 'Script could not be loaded'
                })        
        
        if self.script is None:
            Logger.warning(f'Script could not be loaded. Check consistency and retry please.')
            if self.cm.amimaster:
                self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'Script could not be loaded'})
            else:
                Logger.info(f'Project script could not be loaded. Check logs.')
                
                self.set_node_value('/engine/status', 'load', 'ERROR')
                self.assign_nodes_values({
                    'type': 'error',
                    'subtype': 'error',
                    'action': 'project_ready',
                    'action_uuid': self._editor_request_uuid,
                    'value': 'Script could not be loaded'
                })

            self._editor_request_uuid = ''
            return
        else:
            Logger.info('Project script loaded OK!')
            self.script.unix_name = kwargs['value']

        # master or slave, for the moment do the processing, (asume everithin loaded ok)
        self.initial_cuelist_process(self.script.cuelist)

        # Then we force-arm the first item in the main list
        self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
        # And get it ready to wait a GO command
        self.next_cue_pointer = self.script.cuelist.contents[0]
        self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = self.next_cue_pointer.uuid

        # Start MTC!
        if self.cm.amimaster:
            libmtcmaster.MTCSender_play(self.mtcmaster)

        if local_media_error:
            Logger.info(f'Project loaded with local media errors...')

        if self.cm.amimaster:
            if not local_media_error:
                if not slave_media_error:
                    self.editor_queue.put({'type':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'OK'})
                    Logger.info(f'Project loaded OK.')
                else:
                    Logger.warning(f'Some slaves could not load all their media...')
                    self.editor_queue.put({'type':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'OK_deploy_needed'})
            else:
                self.editor_queue.put({'type':'project_ready', 'action_uuid':self._editor_request_uuid, 'value':'OK_missing_media'})
        else:
            self.set_node_value('/engine/status', 'load', 'OK')
            self.assign_nodes_values({
                'type': 'OK',
                'action': 'project_ready',
                'action_uuid': self._editor_request_uuid,
                'value': 'OK'
            })

        # Everything went OK while loading the project locally...
        Logger.info(f'Project load COMPLETED!')

        self.set_show_lock_file()

        self._editor_request_uuid = ''

    def load_cue_callback(self, **kwargs):
        Logger.info(f'LOAD CUE CALLBACK! -> CUE : {kwargs["value"]}')

        cue_to_load = self.script.find(kwargs['value'])

        if cue_to_load != None:
            if cue_to_load not in self.armedcues:
                cue_to_load.arm(self.cm, self.ossia_server, self.armedcues)

    def unload_cue_callback(self, **kwargs):
        Logger.info(f'UNLOAD CUE CALLBACK! -> CUE : {kwargs["value"]}')

        cue_to_unload = self.script.find(kwargs['value'])

        if cue_to_unload != None:
            if cue_to_unload in self.armedcues:
                cue_to_unload.disarm(self.ossia_server)

    def go_cue_callback(self, **kwargs):
        Logger.info(f'GO CUE CALLBACK! -> ARGS : {kwargs["value"]}')

        cue_to_go = self.script.find(kwargs['value'])

        if cue_to_go is None:
            Logger.error(f'Cue {kwargs["value"]} does not exist.')
        else:
            if cue_to_go not in self.armedcues:
                Logger.error(f'Cue {kwargs["value"]} not prepared. Prepare it first.')
            else:
                Logger.info(f'Cue {kwargs["value"]} in armedcues list. Ready!')
                Logger.info(f'OSC GO! -> CUE : {cue_to_go.uuid}')

                cue_to_go.go(self.ossia_server, self.mtclistener)

                self.ongoing_cue = cue_to_go
                Logger.info(f'Current Cue: {self.ongoing_cue}')

    def go_callback(self, **kwargs):
        try:
            if kwargs['value'][-1] == '*':
                return
        except IndexError:
            pass

        # Mark back our load command on slaves
        if self.ossia_server._oscquery_registered_nodes[f'/engine/command/go'][0].value and self.ossia_server._oscquery_registered_nodes[f'/engine/command/go'][0].value[-1] != '*':
            self.ossia_server._oscquery_registered_nodes[f'/engine/command/go'][0].value = kwargs['value'] + '*'

        Logger.info(f'GO CALLBACK! -> ARGS : {kwargs["value"]}')

        if self.script:
            # Call OSC go on all slaves:
            # by the moment we are using the direct /engine/command/go callback on the slaves
            if self.cm.amimaster:
                for device in self.ossia_server.oscquery_slave_devices.keys():
                    try:
                        self.assign_slave_nodes_values(device, {
                            'type': 'command',
                            'action': 'go',
                            'action_uuid': self._editor_request_uuid,
                            'value': ''
                        })

                        Logger.info(f'Calling GO CALLBACK via OSC on slave node {device}')
                        self.set_slave_node_value(device, '/engine/command', 'go', 'go')
                    except Exception as e:
                        Logger.exception(e)

            if not self.ongoing_cue:
                cue_to_go = self.script.cuelist.contents[0]
            else:
                if self.next_cue_pointer:
                    cue_to_go = self.next_cue_pointer
                else:
                    Logger.info(f'Reached end of script. Last cue was {self.ongoing_cue.__class__.__name__} {self.ongoing_cue.uuid}')
                    self.ongoing_cue = None
                    self.go_offset = 0
                    self.script.cuelist.contents[0].arm(self.cm, self.ossia_server, self.armedcues)
                    return

            if cue_to_go not in self.armedcues:
                Logger.error(f'Trying to go a cue that is not yet loaded. CUE : {cue_to_go.uuid}')
            else:
                self.ongoing_cue = cue_to_go
                self.ongoing_cue.go(self.ossia_server, self.mtclistener)
                self.next_cue_pointer = self.ongoing_cue.get_next_cue()
                self.go_offset = self.mtclistener.main_tc.milliseconds

                # OSC Query cues status notification
                self.set_node_value('/engine/status', 'currentcue', self.ongoing_cue.uuid)
                if self.next_cue_pointer:
                    self.set_node_value('/engine/status', 'nextcue', self.next_cue_pointer.uuid)
                else:
                    self.set_node_value('/engine/status', 'nextcue', "")
                self.set_node_value('/engine/status', 'running', 1)
        else:
            Logger.warning('No script loaded, cannot process GO command.')

    def pause_callback(self, **kwargs):
        Logger.info(f'PAUSE CALLBACK! -> ARGS : {kwargs["value"]}')
        try:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_pause(self.mtcmaster)
            self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value = int(not self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value)
        except:
            Logger.info('NO MTCMASTER ASSIGNED!')

    def stop_callback(self, **kwargs):
        Logger.info(f'STOP CALLBACK! -> ARGS : {kwargs["value"]}')
        try:
            if self.cm.amimaster:
                libmtcmaster.MTCSender_stop(self.mtcmaster)
            self.go_offset = 0
            self.ossia_server._oscquery_registered_nodes['/engine/status/running'][0].value = 0
        except:
            Logger.info('NO MTCMASTER ASSIGNED!')

    def reset_all_callback(self, **kwargs):
        try:
            if kwargs['value'][-1] == '*':
                return
        except IndexError:
            pass

        # Mark back our load command on slaves
        if self.ossia_server._oscquery_registered_nodes[f'/engine/command/resetall'][0].value and self.ossia_server._oscquery_registered_nodes[f'/engine/command/resetall'][0].value[-1] != '*':
            self.ossia_server._oscquery_registered_nodes[f'/engine/command/resetall'][0].value = kwargs['value'] + '*'

        Logger.info(f'RESET ALL CALLBACK! -> ARGS : {kwargs["value"]}')
        
        # delete show.lock file
        self.remove_show_lock_file()

        # Call OSC go on all slaves:
        # by the moment we are using the direct /engine/command/go callback on the slaves
        if self.cm.amimaster:
            for device in self.ossia_server.oscquery_slave_devices.keys():
                try:
                    self.assign_slave_nodes_values(device, {
                        'type': 'command',
                        'action': 'resetall',
                        'action_uuid': self._editor_request_uuid,
                        'value': ''
                    })

                    Logger.info(f'Calling RESETALL CALLBACK via OSC on slave node {device}')
                    self.set_slave_node_value(device, '/engine/command', 'resetall', 'resetall')
                except Exception as e:
                    Logger.exception(e)

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
                # DEV: Repeated line below for nextcue?
                self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = self.next_cue_pointer.uuid

                self.ossia_server._oscquery_registered_nodes['/engine/status/currentcue'][0].value = ""
                self.ossia_server._oscquery_registered_nodes['/engine/status/nextcue'][0].value = self.script.cuelist.contents[0].uuid
            if self.cm.amimaster:
                libmtcmaster.MTCSender_play(self.mtcmaster)

        except Exception as e:
            Logger.exception(e)

    def comms_callback(self, **kwargs):
        Logger.info(f'COMMS CALLBACK! -> ARGS : {kwargs["value"]}')

        if self.cm.amimaster:
            for device in self.ossia_server.oscquery_slave_devices:
                Logger.debug(f'COMMS CALLBACK: {kwargs["value"]}\ntype : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/type"][0].value} // '
                            + f'action : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/action"][0].value} // '
                            + f'action_uuid : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/action_uuid"][0].value} // '
                            + f'value : {self.ossia_server.oscquery_slave_registered_nodes[f"/{device}/engine/comms/value"][0].value}')
        else:
            Logger.debug(
                f'COMMS CALLBACK: {kwargs["value"]}\ntype : {self.ossia_server._oscquery_registered_nodes["/engine/comms/type"][0].value} // '
                    + f'action : {self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value} // '
                    + f'action_uuid : {self.ossia_server._oscquery_registered_nodes["/engine/comms/action_uuid"][0].value} // '
                    + f'value : {self.ossia_server._oscquery_registered_nodes["/engine/comms/value"][0].value}'
            )

            if self.ossia_server._oscquery_registered_nodes["/engine/comms/type"][0].value == 'command' and self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value == 'go':
                self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value == 'command_done'
                self.ossia_server._oscquery_registered_nodes["/engine/comms/action"][0].value == 'go_done'
                self.go_callback()

    def action_uuid_callback(self, **kwargs):
        self._editor_request_uuid = kwargs['value']

    def test_callback(self, **kwargs):
        Logger.info(f'TEST CALLBACK! -> ARGS : {kwargs["value"]}')

        '''OSC callback for internal test porpouses'''
        self.test_data = kwargs['value']

        if self.cm.amimaster:
            try:
                self.editor_command_callback(item=literal_eval(self.test_data))
            except Exception as e:
                Logger.exception(f'Exception raised in test_thread: {e}')
        else:
            try:
                d = literal_eval(self.test_data)
                d['type'] = 'test'
                self.assign_nodes_values(d)
            except Exception as e:
                Logger.exception(f'Exception raised in test_thread: {e}')

    def test_thread_function(self):
        try:
            self.editor_command_callback(item=literal_eval(self.test_data))
        except Exception as e:
            Logger.exception(f'Exception raised in test_thread: {e}')

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
            Logger.error(string)

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
                        Logger.debug(f'{item.outputs}')
                        try:
                            for output in item.outputs:
                                # TO DO : add support for multiple outputs
                                video_player_id = self.cm.get_video_player_id(output['output_name'][37:])
                                Logger.debug(f'video player id: {video_player_id}')
                                item._player = self._video_players[video_player_id]['player']
                                item._osc_route = self._video_players[video_player_id]['route']
                        except Exception as e:
                            Logger.exception(e)
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
            Logger.error(f'Error arming cuelist : {cuelist.uuid} : {e}')
            raise
    
    # DEV: This block of methods probably should be moved to the OssiaServer class
    def assign_nodes_values(self, value_dict: dict, path: str = '/engine/comms') -> None:
        for k,v in value_dict.items():
            self.set_node_value(path, k, v)
    
    def assign_slave_nodes_values(self, device, value_dict: dict, path: str = 'engine/comms') -> None:
        for k,v in value_dict.items():
            self.set_slave_node_value(device, path, k, v)

    def set_node_value(self, path: str, key: str, value) -> None:
        self.ossia_server._oscquery_registered_nodes[f'{path}/{key}'][0].value = value

    def set_slave_node_value(self, device: str, path: str, key: str, value) -> None:
        self.ossia_server.oscquery_slave_registered_nodes[f'/{device}/{path}/{key}'][0].value = value

    ########################################################
