from threading import Thread
from os import path, mkdir, environ
import enum
import time
from zeroconf import IPVersion, ServiceInfo, ServiceListener, ServiceBrowser, Zeroconf, ZeroconfServiceTypes
from .Settings import Settings
from .log import logger



CUEMS_MASTER_LOCK_FILE = 'master.lock'

################################################################################
# Config Manager Avahi monitoring import
class NodeType(enum.Enum):
    slave = 0
    master = 1
    firstrun = 2

class MyAvahiListener():
    @enum.unique
    class Action(enum.Enum):
        DELETE = 0
        ADD = 1
        UPDATE = 2

    def __init__(self, callback = None):
        self.callback = callback
        self.nodeconf_services = {}
        self.osc_services = {}

    def remove_service(self, zeroconf, type_, name):
        try:
            if type_ == '_cuems_nodeconf._tcp.local.':
                self.nodeconf_services.pop(name)
                #logger.info(f'Avahi nodeconf service removed: {name}')
            elif type_ == '_cuems_osc._tcp.local.':
                self.osc_services.pop(name)
                #logger.info(f'Avahi OSC service removed: {name}')
        except KeyError:
            pass

        if self.callback:
            self.callback(None, action=MyAvahiListener.Action.DELETE)

    def add_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if type_ == '_cuems_nodeconf._tcp.local.':
            self.nodeconf_services[name] = info
            #logger.info(f'New avahi nodeconf service added: {info}')
        elif type_ == '_cuems_osc._tcp.local.':
            self.osc_services[name] = info
            #logger.info(f'New avahi OSC service added: {info}')

        if self.callback:
            self.callback(info, action=MyAvahiListener.Action.ADD)

    def update_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if type_ == '_cuems_nodeconf._tcp.local.':
            self.nodeconf_services[name] = info
            #logger.info(f'Avahi nodeconf service updated: {info}')
        elif type_ == '_cuems_osc._tcp.local.':
            self.osc_services[name] = info
            #logger.info(f'Avahi OSC service updated: {info}')

        if self.callback:
            self.callback(info, action=MyAvahiListener.Action.UPDATE)

class CuemsAvahiMonitor():
    def __init__(self):
        self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)

        self.services = ['_cuems_nodeconf._tcp.local.', '_cuems_osc._tcp.local.']

        self.listener = MyAvahiListener()
        self.browser = ServiceBrowser(self.zeroconf, self.services, self.listener)
        time.sleep(2)

    def callback(self, caller_node=None, action=MyAvahiListener.Action.ADD):
        print(f" {action} callback!!!, Node: {caller_node} ")

    def shutdown(self):
        self.zeroconf.close()
################################################################################

class ConfigManager(Thread):
    def __init__(self, path, nodeconf=False, *args, **kwargs):
        super().__init__(name='CfgMan', args=args, kwargs=kwargs)

        self.avahi_monitor = CuemsAvahiMonitor()

        self.cuems_conf_path = path
        self.library_path = None
        self.tmp_path = None
        self.database_name = None
        self.node_conf = {}
        self.network_map = {}
        self.network_mappings = {}
        self.node_mappings = {}
        self.node_hw_outputs = {'audio_inputs':[], 'audio_outputs':[], 'video_inputs':[], 'video_outputs':[], 'dmx_inputs':[], 'dmx_outputs':[]}

        self.amimaster = False

        self.project_conf = {}
        self.project_mappings = {}
        self.project_node_mappings = {}
        self.project_default_outputs = {}

        self.using_default_mappings = False

        self.number_of_nodes = 1

        try:
            self.load_node_conf()
        except Exception as e:
            logger.exception(f'Exception catched while load_node_conf: {e}')
            raise e

        self.check_amimaster()

        if self.amimaster:
            try:
                self.load_network_map()
            except Exception as e:
                logger.exception(f'Exception catched while load_network_map: {e}')
                raise e

        if not nodeconf:
            try:
                self.load_net_and_node_mappings()
            except Exception as e:
                logger.exception(f'Exception catched while load_net_and_node_mappings: {e}')
                raise e


        self.osc_port_index = { "start":int(self.node_conf['osc_in_port_base']), 
                                    "used":[]
                                    }
        self.start()

    def load_network_map(self):
        netmap_schema = path.join(self.cuems_conf_path, 'network_map.xsd')
        netmap_file = path.join(self.cuems_conf_path, 'network_map.xml')
        try:
            netmap = Settings(schema=netmap_schema, xmlfile=netmap_file)
#            netmap.pop('xmlns:cms')
#            netmap.pop('xmlns:xsi')
            if "schemaLocation" in netmap:
                netmap.pop('schemaLocation')
                
            self.network_map = netmap['CuemsNodeDict']
        except FileNotFoundError as e:
            raise e
        else:
            logger.info('Network map loaded on master')


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

        if engine_settings['Settings']['tmp_path'] == None:
            logger.warning('No temp upload path specified in settings. Assuming default /tmp/cuemsupload.')
            self.tmp_path = path.join('/', 'tmp', 'cuems')
        else:
            self.tmp_path = engine_settings['Settings']['tmp_path']

        if engine_settings['Settings']['database_name'] == None:
            logger.warning('No database name specified in settings. Assuming default project-manager.db.')
            self.database_name = 'project-manager.db'
        else:
            self.database_name = engine_settings['Settings']['database_name']

        self.show_lock_file = engine_settings['Settings']['show_lock_file']

        # Now we know where the library is, let's check it out
        self.check_dir_hierarchy()

        self.node_conf = engine_settings['Settings']['node']

        logger.info(f'Cuems node_{self.node_conf["uuid"]} config loaded')
        #logger.info(f'Node conf: {self.node_conf}')
        #logger.info(f'Audio player conf: {self.node_conf["audioplayer"]}')
        #logger.info(f'Video player conf: {self.node_conf["videoplayer"]}')
        #logger.info(f'DMX player conf: {self.node_conf["dmxplayer"]}')

    def load_net_and_node_mappings(self):
        settings_schema = path.join(self.cuems_conf_path, 'project_mappings.xsd')
        settings_file = path.join(self.cuems_conf_path, 'default_mappings.xml')
        try:
            self.network_mappings = Settings(schema=settings_schema, xmlfile=settings_file).copy()
            self.network_mappings.pop('xmlns:cms')
            self.network_mappings.pop('xmlns:xsi')
            self.network_mappings.pop('xsi:schemaLocation')
        except FileNotFoundError as e:
            raise e
        except KeyError:
            pass
        except Exception as e:
            logger.exception(f'Exception in load_net_and_node_mappings: {e}')

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
        mappings_schema = path.join(self.cuems_conf_path, 'project_mappings.xsd')
        mappings_path = path.join(self.library_path, 'projects', project_uname, 'mappings.xml')
        try:
            self.project_mappings = Settings(mappings_schema, mappings_path)
            self.project_mappings.pop('xmlns:cms')
            self.project_mappings.pop('xmlns:xsi')
            self.project_mappings.pop('xsi:schemaLocation')

            self.using_default_mappings = False
        except FileNotFoundError as e:
            logger.info(f'Project mappings not found. Adopting default mappings.')

            self.using_default_mappings = True
            self.project_mappings = self.node_mappings
            self.project_node_mappings = self.node_mappings
            return
        except KeyError:
            pass
        except Exception as e:
            logger.exception(f'Exception in load_project_mappings: {e}')

        self.number_of_nodes = int(self.project_mappings['number_of_nodes'])
        # By now we need to correct the data structure from the xml
        # the converter is not getting what we really intended but we'll
        # correct it here by the moment

        self.project_mappings = self.process_network_mappings(self.project_mappings.copy())

        for node in self.project_mappings['nodes']:
            if node['uuid'] == self.node_conf['uuid']:
                self.project_node_mappings = node
                break
            
        logger.info(f'Project {project_uname} mappings loaded')

        if not self.project_node_mappings:
            logger.warning(f'No mappings assigned for this node in project {project_uname}')

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

            if not path.exists( self.tmp_path ) :
                mkdir( self.tmp_path )

        except Exception as e:
            logger.error("error: {} {}".format(type(e), e))

    # def check_amimaster(self):
    #     for name, node in self.avahi_monitor.listener.osc_services.items():
    #         if node.properties[b'node_type'] == b'master' and self.node_conf['uuid'] == node.properties[b'uuid'].decode('utf8'):
    #             self.amimaster = True
    #             break
            
    def check_amimaster(self):
        if path.exists(path.join(self.cuems_conf_path, CUEMS_MASTER_LOCK_FILE)):
            self.amimaster = True

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
