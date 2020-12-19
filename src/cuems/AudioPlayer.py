from subprocess import Popen, PIPE, STDOUT, CalledProcessError
from threading import Thread
import os
import pyossia as ossia

from .log import logger

import time

class AudioPlayer(Thread):
    def __init__(self, port_index, path, args, media):
        super().__init__()
        self.port = port_index['start']
        while self.port in port_index['used']:
            self.port += 2

        port_index['used'].append(self.port)
            
        self.stdout = None
        self.stderr = None
        # self.card_id = card_id
        self.firstrun = True
        self.path = path
        self.args = args
        self.media = media

    '''        
    def __init_thread(self):
        super().__init__()
        self.daemon = True
    '''

    def run(self):
        if __debug__:
            # logger.info('AudioPlayer starting on card:{}'.format(self.card_id))
            logger.info(f'AudioPlayer starting for {self.media}')
           
        try:
            # Calling audioplayer-cuems in a subprocess
            process_call_list = [self.path]
            if self.args:
                for arg in self.args.split():
                    process_call_list.append(arg)
            process_call_list.extend(['--port', str(self.port), self.media])
            # self.p=subprocess.Popen(process_call_list, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # self.stdout, self.stderr = self.p.communicate()

            self.p = Popen(process_call_list, stdout=PIPE, stderr=STDOUT)
            stdout_lines_iterator = iter(self.p.stdout.readline, b'')
            while self.p.poll() is None:
                for line in stdout_lines_iterator:
                    logger.info(line)

        except OSError as e:
            # logger.warning("Failed to start AudioPlayer on card:{}".format(self.card_id))
            logger.warning(f'Failed to start AudioPlayer for {self.media}')
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
                logger.debug("AudioPlayer allready running")
            else:
                '''
                self.__init_trhead()
                Thread.start(self)
                '''
                super().start()

'''
class AudioPlayerRemote():
    # class that exposes osc control of the player and manages the player
    def __init__(self, port, card_id, path, args, media):
        self.port = port
        self.card_id = card_id
        self.audioplayer = AudioPlayer(self.port, self.card_id, path, args, media)
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
'''