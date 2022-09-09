from os import path
from pyossia import ossia
from threading import Thread
from time import sleep

from .Cue import Cue
from .CTimecode import CTimecode
from .VideoPlayer import VideoPlayer
from .OssiaServer import OssiaServer, OSCConfData, PlayerOSCConfData
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
        super().__init__(init_dict)
            
        self._player = None
        self._osc_route = None
        self._go_thread = None

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
                    self.disarm(ossia)
            return False
        elif self.loaded and not init:
            if not self in self._armed_list:
                self._armed_list.append(self)
            return True

        if self._local:
            try:
                key = f'{self._osc_route}/jadeo/cmd'
                ossia.send_message(key, 'midi disconnect')
                logger.info(key + " " + str(ossia._oscquery_registered_nodes[key][0].value))
            except KeyError:
                logger.debug(f'Key error 1 (disconnect) in arm_callback {key}')

            try:
                key = f'{self._osc_route}/jadeo/load'
                value = str(path.join(self._conf.library_path, 'media', self.media.file_name))
                ossia.send_message(key, value)
                logger.info(key + " " + str(ossia._oscquery_registered_nodes[key][0].value))
            except KeyError:
                logger.debug(f'Key error 2 (load) in arm_callback {key}')

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
            self._go_thread = Thread(name = f'GO:{self.__class__.__name__}:{self.uuid}', target = self.go_thread_func, args = [ossia, mtc])
            self._go_thread.start()

    def go_thread_func(self, ossia, mtc):
        # ARM NEXT TARGET
        if self._target_object:
            self._target_object.arm(self._conf, ossia, self._armed_list)

        # PREWAIT
        if self.prewait > 0:
            sleep(self.prewait.milliseconds / 1000)

        if self._local:
            # PLAY : specific video cue stuff
            try:
                key = f'{self._osc_route}/jadeo/offset'
                self._start_mtc = mtc.main_tc
                duration = self.media.regions[0].out_time - self.media.regions[0].in_time
                duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
                self._end_mtc = self._start_mtc + duration
                cue_in_time_fr_adjusted = self.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate)
                offset_to_go = cue_in_time_fr_adjusted.frame_number - self._start_mtc.frame_number
                # ossia._oscquery_registered_nodes[key][0].value = offset_to_go
                ossia.send_message(key, offset_to_go)
                logger.info(key + " " + str(ossia._oscquery_registered_nodes[key][0].value))
            except KeyError:
                logger.debug(f'Key error 1 (offset) in go_callback {key}')

            try:
                key = f'{self._osc_route}/jadeo/cmd'
                ossia.send_message(key, "midi connect Midi Through")
            except KeyError:
                logger.debug(f'Key error 2 (connect) in go_callback {key}')

        # POSTWAIT
        if self.postwait > 0:
            sleep(self.postwait.milliseconds / 1000)

        if self.post_go == 'go' and self._target_object:
            self._target_object.go(ossia, mtc)

        try:
            loop_counter = 0
            duration = self.media.regions[0].out_time - self.media.regions[0].in_time
            duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
            in_time_adjusted = self.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate)

            while not self.media.regions[0].loop or loop_counter < self.media.regions[0].loop:
                while mtc.main_tc.milliseconds < self._end_mtc.milliseconds:
                    sleep(0.005)

                if self._local:
                    try:
                        key = f'{self._osc_route}/jadeo/offset'
                        self._start_mtc = mtc.main_tc
                        self._end_mtc = self._start_mtc + duration
                        offset_to_go = in_time_adjusted.frame_number - self._start_mtc.frame_number
                        ossia.send_message(key, offset_to_go)
                        logger.info(key + " " + str(ossia._oscquery_registered_nodes[key][0].value))
                    except KeyError:
                        logger.debug(f'Key error 1 (offset) in go_callback {key}')

                loop_counter += 1

            if self._local:
                try:
                    key = f'{self._osc_route}/jadeo/cmd'
                    ossia.send_message(key, 'midi disconnect')
                    logger.info(key + " " + str(ossia._oscquery_registered_nodes[key][0].value))
                except KeyError:
                    logger.debug(f'Key error 1 (disconnect) in arm_callback {key}')

        except AttributeError:
            pass
        
        if self in self._armed_list:
            self.disarm(ossia)

    def disarm(self, ossia = None):
        if self.loaded is True:
            '''
            # Needed when each cue launched its own player
            try:
                self._player.kill()
                self._conf.osc_port_index['used'].remove(self._player.port)
                self._player.join()
                self._player = None

                ossia.remove_nodes( OSCConfData(device_name=self._osc_route, dictionary = self.OSC_VIDEOPLAYER_CONF) )

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

    def stop(self):
        self._stop_requested = True

    def check_mappings(self, settings):
        if not settings.project_node_mappings:
            return True

        found = True
        
        map_list = ['default']

        if settings.project_node_mappings['video']['outputs']:
            for elem in settings.project_node_mappings['video']['outputs']:
                for map in elem['mappings']:
                    map_list.append(map['mapped_to'])

        for output in self.outputs:
            # if output['node_uuid'] == settings.node_conf['uuid']:
            if output['output_name'][:36] == settings.node_conf['uuid']:
                self._local = True
                if output['output_name'][37:] not in map_list:
                    found = False
                    break
            else:
                self._local = False
                found = True

        return found
