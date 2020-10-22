from threading import Thread
from os import path, mkdir, environ
from .Settings import Settings
from .log import logger

class ConfigManager(Thread):
    def __init__(self, path, *args, **kwargs):
        super().__init__(name='CfgMan', args=args, kwargs=kwargs)
        self.cuems_conf_path = path
        self.library_path = None
        self.tmp_upload_path = None
        self.database_name = None
        self.node_conf = {}
        self.project_conf = {}
        self.project_maps = {}
        self.load_node_conf()
        self.players_port_index = { "audio":int(self.node_conf['audioplayer']['osc_in_port_base']), 
                                    "video":int(self.node_conf['videoplayer']['osc_in_port_base']), 
                                    "dmx":int(self.node_conf['dmxplayer']['osc_in_port_base'])
                                    }
        self.start()

    def load_node_conf(self):
        settings_schema = path.join(self.cuems_conf_path, 'settings.xsd')
        settings_file = path.join(self.cuems_conf_path, 'settings.xml')
        try:
            engine_settings = Settings(schema=settings_schema, xmlfile=settings_file)
            # engine_settings.read()
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

        # Now we know where the library is, let's check it out
        self.check_dir_hierarchy()

        self.node_conf = engine_settings['Settings']['node']

        logger.info(f'Cuems node_{self.node_conf["id"]:03} config loaded')
        logger.info(f'Node conf: {self.node_conf}')
        logger.info(f'Audio player conf: {self.node_conf["audioplayer"]}')
        logger.info(f'Video player conf: {self.node_conf["videoplayer"]}')
        logger.info(f'DMX player conf: {self.node_conf["dmxplayer"]}')

    def load_project_settings(self, project_uname):
        try:
            settings_schema = path.join(self.cuems_conf_path, 'project_settings.xsd')
            settings_path = path.join(self.library_path, 'projects', project_uname, 'settings.xml')
            conf = Settings(settings_schema, settings_path)
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            logger.error(e)

        self.project_conf = conf['ProjectSettings']

        logger.info(f'Project {project_uname} settings loaded')

    def load_project_mappings(self, project_uname):
        try:
            mappings_schema = path.join(self.cuems_conf_path, 'project_mappings.xsd')
            mappings_path = path.join(self.library_path, 'projects', project_uname, 'mappings.xml')
            maps = Settings(mappings_schema, mappings_path)
        except FileNotFoundError as e:
            raise e
        except Exception as e:
            logger.error(e)

        self.project_maps = maps['ProjectMappings']
        logger.info(f'Project {project_uname} mappings loaded')

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
                mkdir( self.library_path )

        except Exception as e:
            logger.error("error: {} {}".format(type(e), e))
