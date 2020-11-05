from os import path
from pyossia import ossia
from threading import Thread
from time import sleep

from .Cue import Cue
from .VideoPlayer import VideoPlayer
from .OssiaServer import QueueOSCData
from .log import logger
class VideoCue(Cue):
    OSC_VIDEOPLAYER_CONF = {'/jadeo/xscale' : [ossia.ValueType.Float, None],
                            '/jadeo/yscale' : [ossia.ValueType.Float, None], 
                            '/jadeo/corners' : [ossia.ValueType.List, None],
                            '/jadeo/corner1' : [ossia.ValueType.List, None],
                            '/jadeo/corner2' : [ossia.ValueType.List, None],
                            '/jadeo/corner3' : [ossia.ValueType.List, None],
                            '/jadeo/corner4' : [ossia.ValueType.List, None],
                            '/jadeo/start' : [ossia.ValueType.Bool, None],
                            '/jadeo/load' : [ossia.ValueType.String, None],
                            '/jadeo/quit' : [ossia.ValueType.Bool, None],
                            '/jadeo/midi/connect' : [ossia.ValueType.String, None],
                            '/jadeo/midi/disconnect' : [ossia.ValueType.Impulse, None]
                            }

    def __init__(self, time=None, init_dict=None):
        super().__init__(time, init_dict)
        self._player = None
        self._osc_route = None
        self._offset_route = '/jadeo/offset'

        self.conf = None
        self.ossia_queue = None
        self.armed_list = None

        self.OSC_VIDEOPLAYER_CONF[self._offset_route] = [ossia.ValueType.String, None]
        self.OSC_VIDEOPLAYER_CONF[self._offset_route] = [ossia.ValueType.Int, None]

    @property
    def Media(self):
        return super().__getitem__('Media')

    @Media.setter
    def Media(self, Media):
        super().__setitem__('Media', Media)

    @property
    def Outputs(self):
        return super().__getitem__('Outputs')

    @Outputs.setter
    def Outputs(self, Outputs):
        super().__setitem__('Outputs', Outputs)

    def player(self, player):
        self._player = player

    def osc_route(self, osc_route):
        self._osc_route = osc_route

    def offset_route(self, offset_route):
        _offset_route = offset_route

    def review_offset(self, timecode):
        return -(int(timecode.frame_number))

    def arm(self, conf, ossia_queue, armed_list, init = False):
        self.conf = conf
        self.armed_list = armed_list

        if not self.enabled:
            if self.loaded and self in self.armed_list:
                    self.disarm(ossia_queue)
            return False
        elif self.loaded and not init:
            if not self in self.armed_list:
                self.armed_list.append(self)
            return True

        # Assign its own videoplayer object
        try:
            self._player = VideoPlayer( self.conf.players_port_index, 
                                        self.Outputs,
                                        self.conf.node_conf['videoplayer']['path'],
                                        str(self.conf.node_conf['videoplayer']['args']),
                                        str(path.join(self.conf.library_path, 'media', self.Media['file_name'])))
        except Exception as e:
            raise e

        self._player.start()

        # And dinamically attach it to the ossia for remote control it
        self._osc_route = f'/node{conf.node_conf["id"]:03}/videoplayer-{self.uuid}'

        ossia_queue.put(   QueueOSCData(  'add', 
                                    self._osc_route, 
                                    conf.node_conf['osc_dest_host'], 
                                    self._player.port,
                                    self._player.port + 1, 
                                    self.OSC_VIDEOPLAYER_CONF))

        self.loaded = True
        if not self in self.armed_list:
            self.armed_list.append(self)

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
            self._target_object.arm(self.conf, ossia.conf_queue, self.armed_list)
        elif self.post_go == 'go':
            self._target_object.go(ossia, mtc)

        try:
            key = f'{self._osc_route}{self._offset_route}'
            ossia.osc_registered_nodes[key][0].parameter.value = self.review_offset(mtc.main_tc)
            logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].parameter.value))
        except KeyError:
            logger.debug(f'Key error 1 in go_callback {key}')

        try:
            key = f'{self._osc_route}/jadeo/midi/connect'
            ossia.osc_registered_nodes[key][0].parameter.value = "Midi Through"
        except KeyError:
            logger.debug(f'Key error 2 in go_callback {key}')

        try:
            while self._player.is_alive():
                sleep(0.05)
        except AttributeError:
            return
        
        if self in self.armed_list:
            self.disarm(ossia.conf_queue)

    def disarm(self, ossia_queue):
        if self.loaded is True:
            try:
                self._player.kill()
                self.conf.players_port_index['used'].remove(self._player.port)
                self._player.join()
                self._player = None

                ossia_queue.put(QueueOSCData(   'remove', 
                                                self._osc_route, 
                                                dictionary = self.OSC_VIDEOPLAYER_CONF))

            except Exception as e:
                logger.warning(f'Could not properly unload cue {self.uuid} : {e}')

            try:
                if self in self.armed_list:
                    self.armed_list.remove(self)
            except:
                pass
            
            self.loaded = False

            return True
        else:
            return False

