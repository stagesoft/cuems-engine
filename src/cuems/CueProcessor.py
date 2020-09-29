#!/usr/bin/env python3
import threading
import queue
import time

from .log import *

class CuePriorityQueue(queue.PriorityQueue):
    def __init__(self):
      super().__init__()

    def clear(self):
        while not self.empty():
            logger.debug(str(self.get()) + "deleted")
            self.task_done()

class CueQueueProcessor(threading.Thread):
    def __init__(self, queue):
        self.queue = queue
        self.item = None

        super().__init__()
        self.daemon = False

        self.stop_processing = False
        threading.Thread.start(self)

    def run(self):
        while not self.stop_processing:
            self.item = self.queue.get(block=True, timeout=None)
            logger.debug(f'Working on {self.item}')
            logger.debug(f'Finished {self.item}')
            self.queue.task_done()

            time.sleep(0.01)

    def stop(self):
        self.stop_processing = True
