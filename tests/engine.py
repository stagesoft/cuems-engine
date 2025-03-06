#!/usr/bin/env python3

from cuemsengine.CuemsEngine import CuemsEngine
from cuemsutils.log import Logger

try:
    my_engine = CuemsEngine()
except Exception as e:
    Logger.exception(f'Exception during engine execution:\n{e}')
    exit(-1)
