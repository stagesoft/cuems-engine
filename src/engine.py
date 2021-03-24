#!/usr/bin/env python3

from cuems.cuems_hwdiscovery.CuemsHwDiscovery import CuemsHWDiscovery
from cuems.CuemsEngine import CuemsEngine
from cuems.log import logger

# Launch hardware discovery process
try:
    logger.info(f'Hardware discovery launched...')
    CuemsHWDiscovery()
except Exception as e:
    logger.exception(f'Exception during HW discovery process:\n{e}')
    exit(-1)

try:
    my_engine = CuemsEngine()
except Exception as e:
    logger.exception(f'Exception during engine execution:\n{e}')
    exit(-1)
