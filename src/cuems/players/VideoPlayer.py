from subprocess import Popen, PIPE, STDOUT, CalledProcessError
from threading import Thread
import os
from sys import stdout, stderr
import pyossia as ossia

from ..log import logger

import time


class VideoPlayer(Thread):
    def __init__(self, port, output, path, args, media):
        super().__init__()
        self._port = port
        self.output = output
        self.path = path
        self.args = args
        self.media = media

        self.firstrun = True
        self.stdout = None
        self.stderr = None
        
    '''
    def __init_trhead(self):
        super().__init__()
        self.daemon = True
    '''

    def run(self):
        if __debug__:
            logger.info(f'VideoPlayer starting on display : {self.output}.')
           
        try:
            # Calling xjadeo in a subprocess
            process_call_list = [self.path]
            if self.args:
                for arg in self.args.split():
                    process_call_list.append(arg)
            process_call_list.extend(['--osc', str(self._port), '--start-screen', self.output, self.media])
            # self.p = Popen(process_call_list, shell=False, stdout=PIPE, stderr=PIPE)
            # self.stdout, self.stderr = self.p.communicate()

            self.p = Popen(process_call_list, stdout=PIPE, stderr=STDOUT)
            stdout_lines_iterator = iter(self.p.stdout.readline, b'')
            while self.p.poll() is None:
                for line in stdout_lines_iterator:
                    logger.info(line)
        except OSError as e:
            logger.info(f'Failed to start VideoPlayer on display : {self.output}.')
            logger.exception(e)
        except CalledProcessError as e:
            if self.p.returncode < 0:
                raise CalledProcessError(self.p.returncode, self.p.args)


    def kill(self):
        self.p.kill()
        self.started = False

    def start(self):
        if self.firstrun:
            '''
            self.__init_trhead()
            Thread.start(self)
            '''
            super().start()
            self.firstrun = False
        else:
            if self.is_alive():
                logger.debug("VideoPlayer allready running")
            else:
                '''
                self.__init_trhead()
                Thread.start(self)
                '''
                super().start()

    def port(self):
        return self._port

'''
class VideoPlayerRemote():
    def __init__(self, port, monitor_id, path, args, media):
        self.port = port
        self.monitor_id = monitor_id
        self.videoplayer = VideoPlayer(self.port, self.monitor_id, path, args, media)
        self.__start_remote()

    def __start_remote(self):
        self.remote_osc_xjadeo = ossia.ossia.OSCDevice("remoteXjadeo{}".format(self.monitor_id), "127.0.0.1", self.port, self.port+1)

        self.remote_xjadeo_quit_node = self.remote_osc_xjadeo.add_node("/jadeo/quit")
        self.xjadeo_quit_parameter = self.remote_xjadeo_quit_node.create_parameter(ossia.ValueType.Impulse)

        self.remote_xjadeo_seek_node = self.remote_osc_xjadeo.add_node("/jadeo/seek")
        self.xjadeo_seek_parameter = self.remote_xjadeo_seek_node.create_parameter(ossia.ValueType.Int)

        self.remote_xjadeo_load_node = self.remote_osc_xjadeo.add_node("/jadeo/load")
        self.xjadeo_load_parameter = self.remote_xjadeo_load_node.create_parameter(ossia.ValueType.String)

    def start(self):
        self.videoplayer.start()

    def kill(self):
        self.videoplayer.kill()

    def load(self, load_path):
        self.xjadeo_load_parameter.value = load_path

    def seek(self, frame):
        self.xjadeo_seek_parameter.value = frame

    def quit(self):

        self.xjadeo_quit_parameter.value = True

class NodeVideoPlayers():

    def __init__(self, videoplayer_settings):
        self.vplayer=[None]*videoplayer_settings["outputs"]
        for i, v in enumerate(self.vplayer):
            self.vplayer[i] = VideoPlayerRemote(videoplayer_settings["instance"][i]["osc_in_port"], i, videoplayer_settings["path"])
    
    def __getitem__(self, subscript):
        return self.vplayer[subscript]

    def len(self):
        return len(self.vplayer)
'''
