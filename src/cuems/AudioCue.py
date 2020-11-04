
from os import path
from pyossia import ossia
from time import sleep
from threading import Thread

from .Cue import Cue
from .AudioPlayer import AudioPlayer
from .OssiaServer import QueueOSCData
from .log import logger

class AudioCue(Cue):
    # And dinamically attach it to the ossia for remote control it
    OSC_AUDIOPLAYER_CONF = {'/quit' : [ossia.ValueType.Impulse, None],
                            '/load' : [ossia.ValueType.String, None], 
                            '/vol0' : [ossia.ValueType.Float, None],
                            '/vol1' : [ossia.ValueType.Float, None],
                            '/volmaster' : [ossia.ValueType.Float, None],
                            '/play' : [ossia.ValueType.Impulse, None],
                            '/stop' : [ossia.ValueType.Impulse, None],
                            '/stoponlost' : [ossia.ValueType.Bool, None],
                            '/mtcfollow' : [ossia.ValueType.Bool, None],
                            '/check' : [ossia.ValueType.Impulse, None]
                            }

    def __init__(self, time=None, init_dict=None):
        super().__init__(time, init_dict)
        self._player = None
        self._osc_route = None
        self._offset_route = '/offset'

        self.conf = None
        self.ossia_queue = None
        self.armed_list = None

        self.OSC_AUDIOPLAYER_CONF[self._offset_route] = [ossia.ValueType.Float, None]

    @property
    def media(self):
        return super().__getitem__('media')

    @media.setter
    def media(self, media):
        super().__setitem__('media', media)

    @property
    def master_vol(self):
        return super().__getitem__('master_vol')

    @master_vol.setter
    def master_vol(self, master_vol):
        super().__setitem__('master_vol', master_vol)

    @property
    def outputs(self):
        return super().__getitem__('outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('outputs', outputs)

    def player(self, player):
        self._player = player

    def osc_route(self, osc_route):
        self._osc_route = osc_route

    def offset_route(self, offset_route):
        self._offset_route = offset_route

    def review_offset(self, mtc):
        return -(float(mtc.milliseconds()))

    def arm(self, conf, queue, armed_list, init = False):
        self.conf = conf
        self.ossia_queue = queue
        self.armed_list = armed_list

        if not self.enabled:
            if self.loaded:
                self.disarm(conf, queue, armed_list)
            return False
        elif self.loaded and not init:
            if not self in armed_list:
                armed_list.append(self)
            return True

        # Assign its own audioplayer object
        try:
            self._player = AudioPlayer( conf.players_port_index, 
                                        conf.node_conf['audioplayer']['path'],
                                        str(conf.node_conf['audioplayer']['args']),
                                        str(path.join(conf.library_path, 'media', self.media['file_name'])))
        except Exception as e:
            raise e

        self._player.start()

        # And dinamically attach it to the ossia for remote control it
        self._osc_route = f'/node{conf.node_conf["id"]:03}/audioplayer-{self.uuid}'

        queue.put(   QueueOSCData(  'add', 
                                    self._osc_route, 
                                    conf.node_conf['osc_dest_host'], 
                                    self._player.port,
                                    self._player.port + 1, 
                                    self.OSC_AUDIOPLAYER_CONF))

        self.loaded = True
        if not self in armed_list:
            armed_list.append(self)

        return True

    def go(self, ossia, mtc):
        if not self.loaded:
            logger.error(f'Cue {self.uuid} not loaded to go...')
            raise Exception(f'Cue {self.uuid} not loaded to go')

        else:
            # GO
            thread = Thread(name = f'Go:uuid:{self.uuid}', target = self.go_thread, args = [ossia, mtc])
            thread.start()

            # POSTWAIT
            if self.postwait > 0:
                sleep(self.postwait.milliseconds() / 1000)
                self._target_object.go(ossia, mtc)

    def go_thread(self, ossia, mtc):
        # PREWAIT
        if self.prewait > 0:
            sleep(self.prewait.milliseconds() / 1000)

        if self.post_go == 'pause':
            self._target_object.arm(self.conf, self.ossia_queue, self.armed_list)
        elif self.post_go == 'go':
            self._target_object.go(ossia, mtc)

        try:
            key = f'{self._osc_route}{self._offset_route}'
            ossia.osc_registered_nodes[key][0].parameter.value = self.review_offset(mtc)
            logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].parameter.value))
        except KeyError:
            logger.debug(f'Key error 1 in go_callback {key}')

        try:
            key = f'{self._osc_route}/mtcfollow'
            ossia.osc_registered_nodes[key][0].parameter.value = True
        except KeyError:
            logger.debug(f'Key error 2 in go_callback {key}')

        try:
            while self._player.is_alive():
                sleep(0.05)
        except AttributeError:
            return
        
        self.disarm(self.conf, self.ossia_queue, self.armed_list)

    def disarm(self, conf, queue, armed_list):
        if self.loaded is True:
            try:
                self._player.kill()
                conf.players_port_index['used'].remove(self._player.port)
                self._player.join()
                self._player = None

                queue.put(QueueOSCData( 'remove', 
                                        self._osc_route, 
                                        dictionary = self.OSC_AUDIOPLAYER_CONF))

            except Exception as e:
                logger.warning(f'Could not properly unload cue {self.uuid} : {e}')
            
            try:
                if self in armed_list:
                    armed_list.remove(self)
            except:
                pass

            self.loaded = False

            return True
        else:
            return False

