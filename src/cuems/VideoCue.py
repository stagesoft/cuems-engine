from os import path
from pyossia import ossia
from threading import Thread
from time import sleep

from .Cue import Cue
from .CTimecode import CTimecode
from .VideoPlayer import VideoPlayer
from .OssiaServer import QueueOSCData
from .log import logger
class VideoCue(Cue):
    '''
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
    '''

    def __init__(self, init_dict = None):
        if init_dict:
            super().__init__(init_dict)
            
        self._player = None
        self._osc_route = None

        # TODO: Adjust framerates for universal use, by now 25 fps for video
        self._start_mtc = CTimecode(framerate=25)
        self._end_mtc = CTimecode(framerate=25)

        '''
        self.OSC_VIDEOPLAYER_CONF['/jadeo/offset'] = [ossia.ValueType.String, None]
        self.OSC_VIDEOPLAYER_CONF['/jadeo/offset'] = [ossia.ValueType.Int, None]
        '''

    @property
    def media(self):
        return super().__getitem__('Media')

    @media.setter
    def media(self, media):
        super().__setitem__('Media', media)

    @property
    def outputs(self):
        return super().__getitem__('Outputs')

    @outputs.setter
    def outputs(self, outputs):
        super().__setitem__('Outputs', outputs)

    def player(self, player):
        self._player = player

    def osc_route(self, osc_route):
        self._osc_route = osc_route

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

        try:
            key = f'{self._osc_route}/jadeo/cmd'
            ossia.osc_registered_nodes[key][0].parameter.value = 'midi disconnect'
            logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].parameter.value))
        except KeyError:
            logger.debug(f'Key error 1 (disconnect) in arm_callback {key}')

        try:
            key = f'{self._osc_route}/jadeo/load'
            ossia.osc_registered_nodes[key][0].parameter.value = str(path.join(self._conf.library_path, 'media', self.media.file_name))
            logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].parameter.value))
        except KeyError:
            logger.debug(f'Key error 2 (load) in arm_callback {key}')

        '''
        # Assign its own videoplayer object
        try:
            self._player = VideoPlayer( self._conf.players_port_index, 
                                        self.outputs,
                                        self._conf.node_conf['videoplayer']['path'],
                                        str(self._conf.node_conf['videoplayer']['args']),
                                        str(path.join(self._conf.library_path, 'media', self.media['file_name'])))
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
        '''

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

        # PLAY : specific video cue stuff
        try:
            key = f'{self._osc_route}/jadeo/offset'
            self._start_mtc = mtc.main_tc
            duration = self.media.regions[0].out_time - self.media.regions[0].in_time
            duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
            self._end_mtc = self._start_mtc + duration
            offset_to_go = self.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate) - self._start_mtc
            ossia.osc_registered_nodes[key][0].parameter.value = offset_to_go.frame_number
            logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].parameter.value))
        except KeyError:
            logger.debug(f'Key error 1 (offset) in go_callback {key}')

        try:
            key = f'{self._osc_route}/jadeo/cmd'
            ossia.osc_registered_nodes[key][0].parameter.value = "midi connect Midi Through"
        except KeyError:
            logger.debug(f'Key error 2 (connect) in go_callback {key}')

        # POSTWAIT
        if self.postwait > 0:
            sleep(self.postwait.milliseconds / 1000)

        if self.post_go == 'go' and self._target_object:
            self._target_object.go(ossia, mtc)

        try:
            loop_counter = 0
            while not self.media.regions[0].loop or loop_counter < self.media.regions[0].loop:
                while (mtc.main_tc.milliseconds < self._end_mtc.milliseconds):
                    sleep(0.05)

                try:
                    key = f'{self._osc_route}/jadeo/offset'
                    self._start_mtc = mtc.main_tc
                    duration = self.media.regions[0].out_time - self.media.regions[0].in_time
                    duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
                    self._end_mtc = self._start_mtc + duration
                    offset_to_go = self.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate) - self._start_mtc
                    ossia.osc_registered_nodes[key][0].parameter.value = offset_to_go.frame_number
                    logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].parameter.value))
                except KeyError:
                    logger.debug(f'Key error 1 (offset) in go_callback {key}')

                loop_counter += 1

            try:
                key = f'{self._osc_route}/jadeo/cmd'
                ossia.osc_registered_nodes[key][0].parameter.value = 'midi disconnect'
                logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].parameter.value))
            except KeyError:
                logger.debug(f'Key error 1 (disconnect) in arm_callback {key}')

        except AttributeError:
            pass
        if self in self._armed_list:
            self.disarm(ossia.conf_queue)

    def disarm(self, ossia_queue):
        if self.loaded is True:
            '''
            try:
                self._player.kill()
                self._conf.players_port_index['used'].remove(self._player.port)
                self._player.join()
                self._player = None

                ossia_queue.put(QueueOSCData(   'remove', 
                                                self._osc_route, 
                                                dictionary = self.OSC_VIDEOPLAYER_CONF))

            except Exception as e:
                logger.warning(f'Could not properly unload {self.__class__.__name__} {self.uuid} : {e}')
            '''

            try:
                if self in self._armed_list:
                    self._armed_list.remove(self)
            except:
                pass
            
            self.loaded = False

            return True
        else:
            return False

    def check_mappings(self, mappings):
        for output in self.outputs:
            for item in mappings['Video']['outputs']:
                if output['output_name'] == item['mapping']['virtual_name']:
                    return True
        return False

