from .cuems_nodeconf.CuemsNodeConf import CuemsNodeConf
from .cuems_hwdiscovery.CuemsHwDiscovery import HWDiscovery
from .log import logger


class CuemsInit():
    '''
    TEMP INIT METHOD!
    In production, systemd will call nodeconfig -> hwdiscovery -> engine
    '''

    def __init__(self):
        # Launch nodeconf
        nodeconf = CuemsNodeConf()
        
        # Launch hardware discovery process
        try:
            logger.info(f'Hardware discovery launched...')
            HWDiscovery()
        except Exception as e:
            logger.exception(f'Exception: {e}')
            exit(-1)

