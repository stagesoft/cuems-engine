from threading import Thread
from os import path, mkdir, environ
from .Settings import Settings
from .log import logger

class ConfigManager(Thread):
    def __init__(self, path, nodeconf=False, *args, **kwargs):
        super().__init__(name='CfgMan', args=args, kwargs=kwargs)
        self.cuems_conf_path = path
        self.library_path = None
        self.tmp_upload_path = None
        self.database_name = None
        self.node_conf = {}
        self.network_outputs = {}
        self.node_outputs = {}
        self.project_conf = {}
        self.project_maps = {}
        self.default_mappings = False
        self.load_node_conf()

        self.players_port_index = { "start":int(self.node_conf['osc_in_port_base']), 
                                    "used":[]
                                    }

        if not nodeconf:
            self.load_node_outputs()

        self.start()

    def load_node_conf(self):
        settings_schema = path.join(self.cuems_conf_path, 'settings.xsd')
        settings_file = path.join(self.cuems_conf_path, 'settings.xml')
        try:
            engine_settings = Settings(schema=settings_schema, xmlfile=settings_file)
        except FileNotFoundError as e:
            raise e

        if engine_settings['Settings']['library_path'] == None:
            logger.warning('No library path specified in settings. Assuming default ~/cuems_library.')
            self.library_path = path.join(environ['HOME'], 'cuems_library')
        else:
            self.library_path = engine_settings['Settings']['library_path']

        if engine_settings['Settings']['tmp_upload_path'] == None:
            logger.warning('No temp upload path specified in settings. Assuming default /tmp/cuemsupload.')
            self.tmp_upload_path = path.join('/', 'tmp', 'cuemsupload')
        else:
            self.tmp_upload_path = engine_settings['Settings']['tmp_upload_path']

        if engine_settings['Settings']['database_name'] == None:
            logger.warning('No database name specified in settings. Assuming default project-manager.db.')
            self.database_name = 'project-manager.db'
        else:
            self.database_name = engine_settings['Settings']['database_name']

        self.show_lock_file = engine_settings['Settings']['show_lock_file']

        # Now we know where the library is, let's check it out
        self.check_dir_hierarchy()

        self.node_conf = engine_settings['Settings']['node']

        logger.info(f'Cuems node_{self.node_conf["id"]:03} config loaded')
        #logger.info(f'Node conf: {self.node_conf}')
        #logger.info(f'Audio player conf: {self.node_conf["audioplayer"]}')
        #logger.info(f'Video player conf: {self.node_conf["videoplayer"]}')
        #logger.info(f'DMX player conf: {self.node_conf["dmxplayer"]}')

    def load_node_outputs(self):
        settings_schema = path.join(self.cuems_conf_path, 'project_mappings.xsd')
        settings_file = path.join(self.cuems_conf_path, 'default_mappings.xml')
        try:
            self.network_outputs = Settings(schema=settings_schema, xmlfile=settings_file).copy()
            self.network_outputs.pop('xmlns:cms')
            self.network_outputs.pop('xmlns:xsi')
            self.network_outputs.pop('xsi:schemaLocation')
        except FileNotFoundError as e:
            raise e
        except KeyError:
            pass
        except Exception as e:
            logger.exception(e)

        if self.network_outputs['number_of_nodes'] > 1:
            for node in self.network_outputs['nodes']:
                if node['node']['uuid'] == self.node_conf['uuid']:
                    node_outputs = node['node']
                    break
        else:
            node_outputs = self.network_outputs['nodes'][0]['node']

        for key, value in node_outputs.items():
            if key == 'audio':
                if not value:
                    break
                
                for item in value:
                    if 'outputs' in item.keys() and item['outputs']:
                        self.node_outputs['audio_outputs'] = []
                        for subitem in item['outputs']:
                            self.node_outputs['audio_outputs'].append(subitem['output']['name'])
                    elif 'default_output' in item.keys():
                        self.node_outputs['default_audio_output'] = item['default_output']
                    elif 'inputs' in item.keys() and item['inputs']:
                        self.node_outputs['audio_inputs'] = []
                        for subitem in item['inputs']:
                            self.node_outputs['audio_inputs'].append(subitem['input']['name'])
                    elif 'default_input' in item.keys():
                        self.node_outputs['default_audio_input'] = item['default_input']
            elif key == 'video':
                if not value:
                    break

                for item in value:
                    if 'outputs' in item.keys() and item['outputs']:
                        self.node_outputs['video_outputs'] = []
                        for subitem in item['outputs']:
                            self.node_outputs['video_outputs'].append(subitem['output']['name'])
                    elif 'default_output' in item.keys():
                        self.node_outputs['default_video_output'] = item['default_output']
                    elif 'inputs' in item.keys() and item['inputs']:
                        self.node_outputs['video_inputs'] = []
                        for subitem in item['inputs']:
                            self.node_outputs['video_inputs'].append(subitem['input']['name'])
                    elif 'default_input' in item.keys():
                        self.node_outputs['default_video_input'] = item['default_input']
            elif key == 'dmx':
                self.node_outputs['dmx_outputs'] = []
                if not value:
                    break

                for item in value:
                    if 'outputs' in item.keys() and item['outputs']:
                        self.node_outputs['dmx_outputs'] = []
                        for subitem in item['outputs']:
                            self.node_outputs['dmx_outputs'].append(subitem['output']['name'])
                    elif 'default_output' in item.keys():
                        self.node_outputs['default_dmx_output'] = item['default_output']
                    elif 'inputs' in item.keys():
                        self.node_outputs['dmx_inputs'] = []
                        for subitem in item['inputs'] and item['inputs']:
                            self.node_outputs['dmx_inputs'].append(subitem['input']['name'])
                    elif 'default_input' in item.keys():
                        self.node_outputs['default_dmx_input'] = item['default_input']

    def load_project_settings(self, project_uname):
        conf = {}
        try:
            settings_schema = path.join(self.cuems_conf_path, 'project_settings.xsd')
            settings_path = path.join(self.library_path, 'projects', project_uname, 'settings.xml')
            conf = Settings(settings_schema, settings_path)
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            logger.exception(e)

        conf.pop('xmlns:cms')
        conf.pop('xmlns:xsi')
        conf.pop('xsi:schemaLocation')
        self.project_conf = conf.copy()
        for key, value in self.project_conf.items():
            corrected_dict = {}
            if value:
                for item in value:
                    corrected_dict.update(item)
                self.project_conf[key] = corrected_dict

        logger.info(f'Project {project_uname} settings loaded')

    def load_project_mappings(self, project_uname):
        maps = {}
        try:
            mappings_schema = path.join(self.cuems_conf_path, 'project_mappings.xsd')
            mappings_path = path.join(self.library_path, 'projects', project_uname, 'mappings.xml')
            maps = Settings(mappings_schema, mappings_path)
            self.default_mappings = False
        except Exception as e:
            logger.info(f'Project mappings not found. Adopting default mappings.')

            try:
                mappings_schema = path.join(self.cuems_conf_path, 'project_mappings.xsd')
                mappings_path = path.join(self.cuems_conf_path, 'default_mappings.xml')
                maps = Settings(mappings_schema, mappings_path)
                self.default_mappings = True
            except Exception as e:
                logger.error(f"Default mappings file not found. Project can't be loaded")
                raise e

        maps.pop('xmlns:cms')
        maps.pop('xmlns:xsi')
        maps.pop('xsi:schemaLocation')
        self.project_maps = maps.copy()
        # By now we need to correct the data structure from the xml
        # the converter is not getting what we really intended but we'll
        # correct it here by the moment
        try:
            for key, value in self.project_maps.items():
                if value:
                    corrected_dict = {}
                    for item in value:
                        corrected_dict.update(item)
                    self.project_maps[key] = corrected_dict
            
            for key, value in self.project_maps.items():
                if value:
                    for subkey, subvalue in value.items():
                        new_list = []
                        if isinstance(subvalue, list):
                            for elem in subvalue:
                                if isinstance(elem, dict):
                                    new_list.append(list(elem.values()))
                                else:
                                    new_list.append(elem)
                            value[subkey] = new_list
        except Exception as e:
            logger.error(f"Error loading project mappings. {e}")
        else:
            logger.info(f'Project {project_uname} mappings loaded')

    def get_video_player_id(self, mapping_name):
        if mapping_name == 'default':
            return self.node_conf['default_video_output']
        else:
            for each_out in self.project_maps['video']['outputs']:
                for each_map in each_out[0]['mappings']:
                    if mapping_name == each_map['mapped_to']:
                        return each_out[0]['name']

        raise Exception(f'Video output wrongly mapped')

    def get_audio_output_id(self, mapping_name):
        if mapping_name == 'default':
            return self.node_conf['default_audio_output']
        else:
            for each_out in self.project_maps['audio']['outputs']:
                for each_map in each_out[0]['mappings']:
                    if mapping_name == each_map['mapped_to']:
                        return each_out[0]['name']

        raise Exception(f'Audio output wrongly mapped')

    def check_dir_hierarchy(self):
        try:
            if not path.exists(self.library_path):
                mkdir(self.library_path)
                logger.info(f'Creating library forlder {self.library_path}')

            if not path.exists( path.join(self.library_path, 'projects') ) :
                mkdir(path.join(self.library_path, 'projects'))

            if not path.exists( path.join(self.library_path, 'media') ) :
                mkdir(path.join(self.library_path, 'media'))

            if not path.exists( path.join(self.library_path, 'trash') ) :
                mkdir(path.join(self.library_path, 'trash'))

            if not path.exists( path.join(self.library_path, 'trash', 'projects') ) :
                mkdir(path.join(self.library_path, 'trash', 'projects'))

            if not path.exists( path.join(self.library_path, 'trash', 'media') ) :
                mkdir(path.join(self.library_path, 'trash', 'media'))

            if not path.exists( self.tmp_upload_path ) :
                mkdir( self.tmp_upload_path )

        except Exception as e:
            logger.error("error: {} {}".format(type(e), e))
