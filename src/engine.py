#!/usr/bin/env python3

# %%

import threading
from log import *
from MtcListener import MtcListener


class cuems_engine():
    def __init__(self):
        self.start_threads()
        logger

    def start_threads(self):
        self.mtclistener = MtcListener()
        t1 = threading.Thread()
        t2 = threading.Thread()

        t1.start()
        t2.start()
        logger.info("Threads started")

    def print_status(self):
        pass

