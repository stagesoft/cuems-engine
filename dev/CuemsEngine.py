import queue
from subprocess import CalledProcessError
from .Settings import Settings
from .CuemsScript import CuemsScript
from .AudioCue import AudioCue
from .DmxCue import DmxCue


class CuemsEngine():
    """
    Copilot proposal for the CuemsEngine class
    """
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.logger.info("CuemsEngine initialized")
        self.cuems = Cuems(config)

    def run(self):
        self.logger.info("CuemsEngine running")
        self.cuems.run()

    def stop(self):
        self.logger.info("CuemsEngine stopping")
        self.cuems.stop()

    def get_config(self):
        return self.config

    def get_cue(self):
        return self.cuems.get_cue()

    def get_cue_list(self):
        return self.cuems.get_cue_list()

    ### Removed code from the original CuemsEngine class
    def load_project_callback(self, **kwargs):
        ''' 20240219 Commented for proto_loop_fruta branch where we do not need to check mappings as they are hard coded
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
        ''' 

        ''' 20240219 Commented for proto_loop_fruta branch where we do not need to check media loading as media is also fixed and hard coded
        try:
            media_fail_list = self.script_media_check()
        except Exception as e:
            logger.exception(f'Exception raised while performing media check: {e}')

        if media_fail_list:
            logger.error(f'Media not found for project: {kwargs["value"]} !!!')

            if self.cm.amimaster:
                pass
                '''''' By the moment we allow the show mode to get ready even if there are media files missing...
                # self.editor_queue.put({'type':'error', 'action':'project_ready', 'action_uuid':self._editor_request_uuid, 'subtype':'media', 'data':list(media_fail_list.keys())})
                ''''''
            else:
                self.ossia_server._oscquery_registered_nodes['/engine/status/load'][0].value = 'ERROR'

                self.ossia_server._oscquery_registered_nodes['/engine/comms/type'][0].value = 'error'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/subtype'][0].value = 'media'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action'][0].value = 'project_ready'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/action_uuid'][0].value = self._editor_request_uuid
                self.ossia_server._oscquery_registered_nodes['/engine/comms/value'][0].value = 'Media not found'
                self.ossia_server._oscquery_registered_nodes['/engine/comms/data'][0].value = list(media_fail_list.keys())

            '''''' By the moment we allow the show mode to get ready even if there are media files missing...
            self.script = None
            self._editor_request_uuid = ''
            return
            ''''''
            local_media_error = True
        else:
            logger.info('Media check OK!')
        '''

        ''' 20240219 Commented for proto_loop_fruta branch where we do not need to check slaves loading as they are hard coded too and supposed to load correctly
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
        '''


        # CHECK PROJECT MAPPINGS
        ''' 20240219 Commented for proto_loop_fruta branch where we do not need to check mappings as they are hard coded
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
        ''' 
