#!/usr/bin/env python3

from cuemsengine.cuems_hwdiscovery.CuemsHwDiscovery import CuemsHWDiscovery
from cuemsengine.CuemsEngine import CuemsEngine
from cuemsengine.log import logger

# Launch hardware discovery process
# try:
#     logger.info(f'Hardware discovery launched...')
#     CuemsHWDiscovery()
# except Exception as e:
#     logger.exception(f'Exception during HW discovery process:\n{e}')

try:
    my_engine = CuemsEngine()
except Exception as e:
    logger.exception(f'Exception during engine execution:\n{e}')
    exit(-1)
