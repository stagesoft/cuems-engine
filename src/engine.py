#!/usr/bin/env python3

from cuems.cuems_hwdiscovery.CuemsHwDiscovery import HWDiscovery
from cuems.CuemsEngine import CuemsEngine
from cuems.log import logger

# Launch hardware discovery process
try:
    logger.info(f'Hardware discovery launched...')
    HWDiscovery()
except Exception as e:
    logger.exception(f'Exception: {e}')
    exit(-1)

my_engine = CuemsEngine()
