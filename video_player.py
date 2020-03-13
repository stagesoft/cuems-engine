import subprocess
import threading
import os
import pyossia as ossia

from log import *
import config

import time


class VideoPlayer(threading.Thread):
    def __init__(self, port, monitor_id):
        print("init monitor_id:{}".format(monitor_id))
        self.port = port
        self.stdout = None
        self.stderr = None
        self.monitor_id = monitor_id
        threading.Thread.__init__(self)
        self.daemon = True
        self.started = False
        

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

    def start(self):
        if self.started:
            if not self.is_alive():
                self.__init__(self.port, self.monitor_id)
                threading.Thread.start(self)
        else:
            threading.Thread.start(self)
            self.started = True
    


class VideoPlayerRemote():
    def __init__(self, port, monitor_id):
        self.port = port
        self.monitor_id = monitor_id
        self.videoplayer = VideoPlayer(self.port, self.monitor_id)
        self.__start_remote()

    def __start_remote(self):
        print("remote{}, {}".format(self.port, self.port+10))
        self.remote_osc_xjadeo = ossia.ossia.OSCDevice("remoteXjadeo{}".format(self.monitor_id), "127.0.0.1", self.port, self.port+10)

        self.remote_xjadeo_quit_node = self.remote_osc_xjadeo.add_node("/jadeo/quit")
        self.xjadeo_quit_parameter = self.remote_xjadeo_quit_node.create_parameter(ossia.ValueType.Impulse)

        self.remote_xjadeo_load_node = self.remote_osc_xjadeo.add_node("/jadeo/load")
        self.xjadeo_load_parameter = self.remote_xjadeo_load_node.create_parameter(ossia.ValueType.String)

        self.remote_xjadeo_seek_node = self.remote_osc_xjadeo.add_node("/jadeo/seek")
        self.xjadeo_seek_parameter = self.remote_xjadeo_seek_node.create_parameter(ossia.ValueType.Int)

    def start(self):
        self.videoplayer.start()

    def kill(self):
        self.videoplayer.kill()

    def load(self, load_path):
        self.xjadeo_load_parameter.value = load_path

    def seek(self, frame):

        self.xjadeo_seek_parameter.value = frame
    
    def quit(self, value):

        self.xjadeo_quit_parameter.value = value

class NodeVideoPlayers():

    def __init__(self):
        self.vplayer=[None]*config.number_of_displays
        for i, v in enumerate(self.vplayer):
            self.vplayer[i] = VideoPlayerRemote(config.video_osc_port + i, i)
            print(config.video_osc_port + i)
    
    def __getitem__(self, subscript):
        return self.vplayer[subscript]

    def len(self):
        return len(self.vplayer)

# get_displays_node=local_device.add_node("/node{}/get/numberofdisplays".format(config.node_id))
# get_displays_node_parameter = get_displays_node.create_parameter(ossia.ValueType.Int)
# get_displays_node_parameter.access_mode = ossia.AccessMode.Get
# get_displays_node_parameter.value = config.number_of_displays