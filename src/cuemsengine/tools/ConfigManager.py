from threading import Thread
from os import path, mkdir, environ, remove

from cuemsutils.log import Logger, logged

from ..Settings import Settings

CUEMS_CONF_PATH = '/etc/cuems/'
LIBRARY_PATH = '.local/share/cuems/'
TMP_PATH = '/tmp/cuems/'
DATABASE_NAME = 'project-manager.db'
SHOW_LOCK_FILE = '.lock_file'
CUEMS_MASTER_LOCK_FILE = 'master.lock'


class ConfigManager():
    def __init__(self, config_dir: str = CUEMS_CONF_PATH):
        """
        ConfigManager constructor.
        This class is responsible for loading the configuration files and providing
        the configuration data to the rest of the application.

        It also provides methods to check the project files and to load them on demand.

        Args:
            config_dir (str): The directory containing the configuration files.

        Raises:
            Exception: If the configuration files are not found.
        """
        # Initialize with default values
        self.config_dir = config_dir
        self.library_path = path.join(environ['HOME'], LIBRARY_PATH)
        self.tmp_path = TMP_PATH
        self.set_dir_hierarchy()

        self.database_name = DATABASE_NAME
        self.show_lock_file = SHOW_LOCK_FILE

        self.using_default_mappings = False

        self.number_of_nodes = 1

        self.load_config()

    @logged
    def load_config(self) -> None:
        """
        Loads the system configuration.
        """
        # Initialize with empty values
        self.node_conf = {}
        self.network_map = {}
        self.network_mappings = {}
        self.node_mappings = {}
        self.node_hw_outputs = {
            'audio_inputs':[],
            'audio_outputs':[],
            'video_inputs':[],
            'video_outputs':[],
            'dmx_inputs':[],
            'dmx_outputs':[]
        }
        
        self._load_node_conf()
        self._load_network_map()
        self._load_net_and_node_mappings()

    def _load_network_map(self):
        try:
            netmap_file = self.conf_path('network_map.xml')
            netmap = Settings(
                schema='network_map',
                xmlfile=netmap_file
            )
            self.network_map = netmap['CuemsNodeDict']
        except Exception as e:
            Logger.exception(f'Exception catched while load_network_map: {e}')
            raise e

    def _load_node_conf(self):
        try:
            settings_file = self.conf_path('settings.xml')
            engine_settings = Settings(
                schema = 'settings',
                xmlfile = settings_file
            )
            engine_settings = engine_settings['Settings']
        except Exception as e:
            Logger.exception(f'Exception catched while load_node_conf: {e}')
            raise e

        if engine_settings['library_path'] != '':
            self.library_path = engine_settings['library_path']
    
        if engine_settings['tmp_path'] != '':
            self.tmp_path = engine_settings['tmp_path']

        if engine_settings['database_name'] != '':
            self.database_name = engine_settings['database_name']

        if engine_settings['show_lock_file'] != '':
            self.show_lock_file = engine_settings['show_lock_file']

        # Now we know where the library is, let's check it out
        self.set_dir_hierarchy()

        self.node_conf = engine_settings['node']
        self.osc_initial_port = self.node_conf['osc_in_port_base']
        self.host_name = f"{self.node_conf['uuid'].split('-')[-1]}.local"

        Logger.info(f'Cuems node_{self.node_conf["uuid"]} config loaded')

    def _load_net_and_node_mappings(self):
        """
        Loads the network and node mappings.
        """
        try:
            settings_file = self.project_path('mappings.xml')
        except FileNotFoundError as e:
            settings_file = self.conf_path('default_mappings.xml')

        try:
            self.network_mappings = Settings(
                schema='project_mappings',
                xmlfile=settings_file
            )
        except Exception as e:
            Logger.exception(f'Exception in load_net_and_node_mappings: {e}')

        self.network_mappings = self.process_network_mappings(self.network_mappings.copy())

        for node in self.network_mappings['nodes']:
            if node['uuid'] == self.node_conf['uuid']:
                self.node_mappings = node
                break

        if not self.node_mappings:
            raise Exception('Node uuid could not be recognised in the network outputs map')

        # Select just output names for node_hw_outputs var
        for section, value in self.node_mappings.items():
            if isinstance(value, dict):
                for subsection, subvalue in value.items():
                    for subitem in subvalue:
                        self.node_hw_outputs[section+'_'+subsection].append(subitem['name'])

    @logged
    def load_project_config(self, project_uname: str) -> None:
        """
        Loads the project configuration.

        Args:
            project_uname (str): The name of the project.
        """
        ## Initialize with empty values
        self.project_conf = {}
        self.project_mappings = {}
        self.project_node_mappings = {}
        self.project_default_outputs = {}

        self._load_project_settings(project_uname)
        self._load_project_mappings(project_uname)

    def _load_project_settings(self, project_uname):
        conf = {}
        try:
            settings_path = self.project_path(project_uname, 'settings.xml')
            conf = Settings(
                schema='project_settings',
                xmlfile=settings_path
            )
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            Logger.exception(e)
        self.project_conf = conf.copy()
        for key, value in self.project_conf.items():
            corrected_dict = {}
            if value:
                for item in value:
                    corrected_dict.update(item)
                self.project_conf[key] = corrected_dict

        Logger.info(f'Project {project_uname} settings loaded')

    def _load_project_mappings(self, project_uname):
        try:
            mappings_path = self.project_path(project_uname, 'mappings.xml')
            self.project_mappings = Settings(
                schema='project_mappings',
                xmlfile=mappings_path
            )
        except FileNotFoundError as e:
            Logger.info(f'Project mappings not found. Adopting default mappings.')
            self.project_mappings = self.node_mappings
            self.project_node_mappings = self.node_mappings
        except Exception as e:
            Logger.exception(f'Exception in _load_project_mappings: {e}')
            raise e

        self.number_of_nodes = int(self.project_mappings['number_of_nodes'])
        # By now we need to correct the data structure from the xml
        # the converter is not getting what we really intended but we'll
        # correct it here by the moment

        self.project_mappings = self.process_network_mappings(self.project_mappings.copy())

        for node in self.project_mappings['nodes']:
            if node['uuid'] == self.node_conf['uuid']:
                self.project_node_mappings = node
                break
        if not self.project_node_mappings:
            Logger.warning(f'No mappings assigned for this node in project {project_uname}')
            
        Logger.info(f'Project {project_uname} mappings loaded')

    def get_video_player_id(self, mapping_name):
        if mapping_name == 'default':
            return self.node_conf['default_video_output']
        else:
            if 'outputs' in self.project_node_mappings['video'].keys():
                for each_out in self.project_node_mappings['video']['outputs']:
                    for each_map in each_out['mappings']:
                        if mapping_name == each_map['mapped_to']:
                            return each_out['name']

        raise Exception(f'Video output wrongly mapped')

    def get_audio_output_id(self, mapping_name):
        if mapping_name == 'default':
            return self.node_conf['default_audio_output']
        else:
            for each_out in self.project_mappings['audio']['outputs']:
                for each_map in each_out[0]['mappings']:
                    if mapping_name == each_map['mapped_to']:
                        return each_out[0]['name']

        raise Exception(f'Audio output wrongly mapped')

    def check_project_mappings(self):
        if self.using_default_mappings:
            return True

        nodes_to_check = [self.project_node_mappings]
        for node in nodes_to_check:
            for area, contents in node.items():
                if isinstance(contents, dict):
                    for section, elements in contents.items():
                        for element in elements:
                            if element['name'] not in self.node_hw_outputs[f'{area}_{section}']:
                                err_str = f'Project {area} {section} mapping incorrect: {element["name"]} not present in node: {self.node_conf["uuid"]}'
                                Logger.error(err_str)
                                raise Exception(err_str)
        return True

    def process_network_mappings(self, mappings):
        '''Temporary process instead of reviewing xml read and convert to objects'''
        temp_nodes = []
        
        for node in mappings['nodes']:
            temp_node = {}
            for section, contents in node['node'].items():
                if not isinstance(contents, list):
                    temp_node[section] = contents
                else:
                    temp_node[section] = {}
                    for item in contents:
                        for key, values in item.items():
                            temp_node[section][key] = []
                            if values:
                                for elem in values:
                                    for subkey, subvalue in elem.items():
                                        temp_node[section][key].append(subvalue)
            temp_nodes.append(temp_node)
        
        mappings['nodes'] = temp_nodes
        return mappings

    ## helper functions
    def project_path(self, project_uname: str, file_name: str) -> str:
        """
        Returns the path to the project file if it exists.

        Args:
            project_uname (str): The name of the project.
            file_name (str): The name of the file to be checked.

        Returns:
            str: The path to the project file.

        Raises:
            FileNotFoundError: If the project file does not exist.
        """
        project_path = path.join(self.library_path, 'projects', project_uname, file_name)
        if not path.exists(project_path):
            raise FileNotFoundError(f'Project file {project_path} not found')
        return project_path
    
    def conf_path(self, file_name: str) -> str:
        """
        Returns the path to the configuration file.

        Args:
            file_name (str): The name of the file to be checked.

        Returns:
            str: The path to the configuration file.

        Raises:
            FileNotFoundError: If the configuration file does not exist.
        """
        conf_path = path.join(self.config_dir, file_name)
        if not path.exists(conf_path):
            raise FileNotFoundError(f'Configuration file {conf_path} not found')
        return conf_path
    
    def set_dir_hierarchy(self) -> None:
        """
        Sets the directory hierarchy for the library path.
        """
        paths_to_check = [
            path.join(self.library_path, 'projects'),
            path.join(self.library_path, 'media'),
            path.join(self.library_path, 'trash', 'projects'),
            path.join(self.library_path, 'trash', 'media'),
            self.tmp_path
        ]
        try:
            for each_path in paths_to_check:
                self.mkdir_recursive(each_path)
        except Exception as e:
            Logger.error("error: {} {}".format(type(e), e))
    
    def set_show_lock(self) -> None:
        """
        Sets the show lock file.
        """
        file_path = path.join(self.library_path, self.show_lock_file)
        if not path.exists(file_path):
            with open(file_path, 'w') as f:
                f.write('')

    def remove_show_lock(self) -> None:
        """
        Removes the show lock file.
        """
        file_path = path.join(self.library_path, self.show_lock_file)
        if path.exists(file_path):
            remove(file_path)

    def mkdir_recursive(self, folder: str) -> None:
        """
        Creates a directory recursively.

        Args:
            folder (str): The folder to be created.
        """
        if path.exists(folder):
            return
        if not path.exists(path.dirname(folder)):
            self.mkdir_recursive(path.dirname(folder))
        mkdir(folder)
