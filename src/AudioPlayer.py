import subprocess
import threading
import os
import pyossia as ossia

from log import *

import time


class AudioPlayer(threading.Thread):
    # class that runs the player in its own thread

    def __init__(self, port, card_id, path):
        self.port = port
        self.stdout = None
        self.stderr = None
        self.card_id = card_id
        self.firstrun = True
        self.path = path
        
        
    def __init_trhead(self):
        super().__init__()
        self.daemon = True

    def run(self):
        if __debug__:
            logger.debug('AudioPlayer starting on card:{}'.format(self.card_id))
           
        try:
            # exec call -- ad command line args here as list 
            # TODO: get command line args from xml
            self.p=subprocess.Popen([self.path, str(self.port), "/audioplayer"], shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.stdout, self.stderr = self.p.communicate()
        except OSError as e:
            logger.warning("Failed to start AudioPlayer on card:{}".format(self.card_id))
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
            threading.Thread.start(self)
            self.firstrun = False
        else:
            if not self.is_alive():
                self.__init_trhead()
                threading.Thread.start(self)
            else:
                logger.debug("AudioPlayer allready running")


class AudioPlayerRemote():
    # class that exposes osc control of the player and manages the player
    def __init__(self, port, card_id, path):
        self.port = port
        self.card_id = card_id
        self.audioplayer = AudioPlayer(self.port, self.card_id, path)
        self.__start_remote()

    def __start_remote(self):
        self.remote_osc_audioplayer = ossia.ossia.OSCDevice("remoteAudioPlayer{}".format(self.card_id), "127.0.0.1", self.port, self.port+1)

        self.remote_audioplayer_quit_node = self.remote_osc_audioplayer.add_node("/audioplayer/quit")
        self.audioplayer_quit_parameter = self.remote_audioplayer_quit_node.create_parameter(ossia.ValueType.Impulse)

        self.remote_audioplayer_level_node = self.remote_osc_audioplayer.add_node("/audioplayer/level")
        self.audioplayer_level_parameter = self.remote_audioplayer_level_node.create_parameter(ossia.ValueType.Int)

        self.remote_audioplayer_load_node = self.remote_osc_audioplayer.add_node("/audioplayer/load")
        self.audioplayer_load_parameter = self.remote_audioplayer_load_node.create_parameter(ossia.ValueType.String)

    def start(self):
        self.audioplayer.start()

    def kill(self):
        self.audioplayer.kill()

    def load(self, load_path):
        self.audioplayer_load_parameter.value = load_path

    def level(self, level):
        self.audioplayer_level_parameter.value = level

    def quit(self):
        self.audioplayer.kill()
        self.audioplayer_quit_parameter.value = True

class NodeAudioPlayers():
    # class to group  al the audio players in a node

    def __init__(self, audioplayer_settings):
        #initialize array to store the player with the number of audio cards we have ( no more players than audio outputs for the moment)
        self.aplayer=[None]*audioplayer_settings["audio_cards"]
        #start a remote controller for each audio output (could be multiple channels), it will controll it own player
        for i, v in enumerate(self.aplayer):
            self.aplayer[i] = AudioPlayerRemote(audioplayer_settings["instance"][i]["osc_in_port"], i, audioplayer_settings["path"])
    
    def __getitem__(self, subscript):
        return self.aplayer[subscript]

    def len(self):
        return len(self.aplayer)

