import subprocess
from threading import Thread
import os
import pyossia as ossia

from .log import logger

import time


class DmxPlayer(Thread):
    def __init__(self, port, path, args, media):
        self.port = port
        self.stdout = None
        self.stderr = None
        # self.card_id = card_id
        self.firstrun = True
        self.path = path
        self.args = args
        self.media = media
        
        
    def __init_trhead(self):
        super().__init__()
        self.daemon = True

    def run(self):
        if __debug__:
            logger.info(f'DmxPlayer starting for {self.media}')
           
        try:
            # Calling audioplayer-cuems in a subprocess
            process_call_list = [self.path]
            if self.args is not None:
                for arg in self.args.split():
                    process_call_list.append(arg)
            process_call_list.extend(['--port', str(self.port), self.media])
            self.p=subprocess.Popen(process_call_list, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.stdout, self.stderr = self.p.communicate()
        except OSError as e:
            logger.warning(f'Failed to start DmxPlayer for {self.media}')
            if __debug__:
                logger.debug(e)

        if __debug__:
            logger.debug(self.stdout)
            logger.debug(self.stderr)
    
    def kill(self):
        self.p.kill()
        self.started = False
    def start(self):
        if self.firstrun:
            self.__init_trhead()
            Thread.start(self)
            self.firstrun = False
        else:
            if not self.is_alive():
                self.__init_trhead()
                Thread.start(self)
            else:
                logger.debug("AudioPlayer allready running")

