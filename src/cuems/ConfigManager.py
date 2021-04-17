from threading import Thread
from os import path, mkdir, environ
import enum
import time
from zeroconf import IPVersion, ServiceInfo, ServiceListener, ServiceBrowser, Zeroconf, ZeroconfServiceTypes
from .Settings import Settings
from .log import logger

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
                logger.info(f'Avahi nodeconf service removed: {name}')
            elif type_ == '_cuems_osc._tcp.local.':
                self.osc_services.pop(name)
                logger.info(f'Avahi OSC service removed: {name}')
        except KeyError:
            pass

        if self.callback:
            self.callback(action=MyAvahiListener.Action.DELETE)

    def add_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if type_ == '_cuems_nodeconf._tcp.local.':
            self.nodeconf_services[name] = info
            logger.info(f'New avahi nodeconf service added: {info}')
        elif type_ == '_cuems_osc._tcp.local.':
            self.osc_services[name] = info
            logger.info(f'New avahi OSC service added: {info}')

        if self.callback:
            self.callback(node)

    def update_service(self, zeroconf, type_, name):
        info = zeroconf.get_service_info(type_, name)
        if type_ == '_cuems_nodeconf._tcp.local.':
            self.nodeconf_services[name] = info
            logger.info(f'Avahi nodeconf service updated: {info}')
        elif type_ == '_cuems_osc._tcp.local.':
            self.osc_services[name] = info
            logger.info(f'Avahi OSC service updated: {info}')

        if self.callback:
            self.callback(node, action=MyAvahiListener.Action.UPDATE)

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
        self.tmp_upload_path = None
        self.database_name = None
        self.node_conf = {}
        self.network_map = {}
        self.network_outputs = {}
        self.node_outputs = {'audio_inputs':[], 'audio_outputs':[], 'video_inputs':[], 'video_outputs':[], 'dmx_inputs':[], 'dmx_outputs':[]}
        self.amimaster = False
        self.project_conf = {}
        self.project_maps = {}
        self.project_default_outputs = {}

        self.default_mappings = False

        self.number_of_nodes = 1

        self.load_node_conf()

        self.check_amimaster()

        self.osc_port_index = { "start":int(self.node_conf['osc_in_port_base']), 
                                    "used":[]
                                    }

        if not nodeconf:
            self.load_node_outputs()

        if self.amimaster:
            self.load_network_map()

        self.start()

    def load_network_map(self):
        netmap_schema = path.join(self.cuems_conf_path, 'network_map.xsd')
        netmap_file = path.join(self.cuems_conf_path, 'network_map.xml')
        try:
            netmap = Settings(schema=netmap_schema, xmlfile=netmap_file)
            netmap.pop('xmlns:cms')
            netmap.pop('xmlns:xsi')
            netmap.pop('xsi:schemaLocation')
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

        logger.info(f'Cuems node_{self.node_conf["uuid"]} config loaded')
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

        for node in self.network_outputs['nodes']:
            if node['node']['mac'] == self.node_conf['mac']:
                temp_node_outputs = node['node']
                break

        temp_node_outputs.pop('uuid')
        temp_node_outputs.pop('mac')
        
        for section, value in temp_node_outputs.items():
            if section == 'audio' and value:
                for subsection in value:
                    for key, value in subsection.items():
                        if key == 'outputs':
                            for subitem in value:
                                self.node_outputs['audio_outputs'].append(subitem['output']['name'])

                        elif key == 'inputs':
                            for subitem in value:
                                self.node_outputs['audio_inputs'].append(subitem['input']['name'])

            elif section == 'video' and value:
                for subsection in value:
                    for key, value in subsection.items():
                        if key == 'outputs':
                            for subitem in value:
                                self.node_outputs['video_outputs'].append(subitem['output']['name'])
                        if key == 'inputs':
                            for subitem in value:
                                self.node_outputs['video_inputs'].append(subitem['input']['name'])

            elif section == 'dmx' and value:
                for subsection in value:
                    for key, value in subsection.items():
                        if key == 'outputs':
                            for subitem in value:
                                self.node_outputs['dmx_outputs'].append(subitem['output']['name'])
                        if key == 'inputs':
                            for subitem in value:
                                self.node_outputs['dmx_inputs'].append(subitem['input']['name'])

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
        except FileNotFoundError as e:
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
        nodes = maps.pop('nodes')
        self.number_of_nodes = maps.pop('number_of_nodes')
        self.project_default_outputs = maps.copy()
        # By now we need to correct the data structure from the xml
        # the converter is not getting what we really intended but we'll
        # correct it here by the moment
        try:
            for node in nodes:
                if node['node']['uuid'] == self.node_conf['uuid']:
                    self.project_maps = node.pop('node')
                    break
            
            self.project_maps.pop('uuid')
            self.project_maps.pop('mac')

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

    def check_amimaster(self):
        for name, node in self.avahi_monitor.listener.osc_services.items():
            if node.properties[b'node_type'] == b'master' and self.node_conf['uuid'] == node.properties[b'uuid'].decode('utf8'):
                self.amimaster = True
                break



