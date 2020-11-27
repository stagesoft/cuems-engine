
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

        self.OSC_AUDIOPLAYER_CONF[self._offset_route] = [ossia.ValueType.Float, None]

    @property
    def master_vol(self):
        return super().__getitem__('master_vol')

    @master_vol.setter
    def master_vol(self, master_vol):
        super().__setitem__('master_vol', master_vol)

    @property
    def Outputs(self):
        return super().__getitem__('Outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('Outputs', outputs)

    def offset_route(self, offset_route):
        self._offset_route = offset_route

    def review_offset(self, mtc):
        return -(float(mtc.milliseconds()))

    def arm(self, conf, ossia, armed_list, init = False):
        self._conf = conf
        self._armed_list = armed_list

        if not self.enabled:
            if self.loaded and self in self._armed_list:
                self.disarm(ossia.conf_queue)
            return False
        elif self.loaded and not init:
            if not self in self._armed_list:
                self._armed_list.append(self)
            return True

        # Assign its own audioplayer object
        try:
            self._player = AudioPlayer( self._conf.players_port_index, 
                                        self._conf.node_conf['audioplayer']['path'],
                                        str(self._conf.node_conf['audioplayer']['args']),
                                        str(path.join(self._conf.library_path, 'media', self.Media['file_name'])))
        except Exception as e:
            raise e

        self._player.start()

        # And dinamically attach it to the ossia for remote control it
        self._osc_route = f'/node{self._conf.node_conf["id"]:03}/audioplayer-{self.uuid}'

        ossia.conf_queue.put(   QueueOSCData(  'add', 
                                            self._osc_route, 
                                            self._conf.node_conf['osc_dest_host'], 
                                            self._player.port,
                                            self._player.port + 1, 
                                            self.OSC_AUDIOPLAYER_CONF))

        self.loaded = True
        if not self in self._armed_list:
            self._armed_list.append(self)

        if self.post_go == 'go' and self._target_object:
            self._target_object.arm(self._conf, ossia, self._armed_list, init)

        return True

    def go(self, ossia, mtc):
        if not self.loaded:
            logger.error(f'{self.__class__.__name__} {self.uuid} not loaded to go...')
            raise Exception(f'{self.__class__.__name__} {self.uuid} not loaded to go')
        else:
            # THREADED GO
            thread = Thread(name = f'GO:{self.__class__.__name__}:{self.uuid}', target = self.go_thread, args = [ossia, mtc])
            thread.start()

    def go_thread(self, ossia, mtc):
        # ARM NEXT TARGET
        if self._target_object:
            self._target_object.arm(self._conf, ossia, self._armed_list)

        # PREWAIT
        if self.prewait > 0:
            sleep(self.prewait.milliseconds / 1000)

        # PLAY : specific audio cue stuff
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

        # POSTWAIT
        if self.postwait > 0:
            sleep(self.postwait.milliseconds / 1000)

        # POST-GO GO
        if self.post_go == 'go' and self._target_object:
                self._target_object.go(ossia, mtc)

        try:
            while self._player.is_alive():
                sleep(0.05)
        except AttributeError:
            return
        
        if self in self._armed_list:
            self.disarm(ossia.conf_queue)

    def disarm(self, ossia_queue):
        if self.loaded is True:
            try:
                self._conf.players_port_index['used'].remove(self._player.port)
                self._player.kill()
                self._player.join()
                self._player = None

                ossia_queue.put(QueueOSCData(   'remove', 
                                                self._osc_route, 
                                                dictionary = self.OSC_AUDIOPLAYER_CONF))

            except Exception as e:
                logger.warning(f'Could not properly unload {self.__class__.__name__} {self.uuid} : {e}')
            
            try:
                if self in self._armed_list:
                    self._armed_list.remove(self)
            except:
                pass

            self.loaded = False

            return True
        else:
            return False

