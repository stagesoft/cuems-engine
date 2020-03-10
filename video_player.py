import subprocess
import threading
import os

from log import *
import config


class VideoPlayer(threading.Thread):
    def __init__(self, port, monitor_id):
        print("init")
        self.port = port
        self.stdout = None
        self.stderr = None
        self.monitor_id = monitor_id
        threading.Thread.__init__(self)
        self.daemon = True

    def run(self):
        print("run")
        if __debug__:
            logging.debug('VideoPlayer starting on display:{}'.format(self.monitor_id))
           
        try:
            self.p=subprocess.Popen([config.videoplayer_path, "--no-splash", "--osc", str(self.port)], shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.stdout, self.stderr = self.p.communicate()
        except OSError as e:
            logging.warning("Failed to start VideoPlayer on display:{}".format(self.monitor_id))
            if __debug__:
                logging.debug(e)

        if __debug__:
            logging.debug(self.stdout)
            logging.debug(self.stderr)
    
    def kill(self):
        self.p.kill()