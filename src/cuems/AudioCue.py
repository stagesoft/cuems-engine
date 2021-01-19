from os import path
from pyossia import ossia
from time import sleep
from threading import Thread

from .Cue import Cue
from .CTimecode import CTimecode
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
                            '/stoponlost' : [ossia.ValueType.Int, None],
                            '/mtcfollow' : [ossia.ValueType.Int, None],
                            '/offset' : [ossia.ValueType.Float, None],
                            '/check' : [ossia.ValueType.Impulse, None]
                            }

    def __init__(self, init_dict = None):
        super().__init__(init_dict)
            
        self._player = None
        self._osc_route = None

        # self.OSC_AUDIOPLAYER_CONF['/offset'] = [ossia.ValueType.Float, None]

    @property
    def master_vol(self):
        return super().__getitem__('master_vol')

    @master_vol.setter
    def master_vol(self, master_vol):
        super().__setitem__('master_vol', master_vol)

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

        # Assign its own audioplayer object
        try:
            self._player = AudioPlayer( self._conf.players_port_index, 
                                        self._conf.node_conf['audioplayer']['path'],
                                        self._conf.node_conf['audioplayer']['args'],
                                        str(path.join(self._conf.library_path, 'media', self.media['file_name'])))
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

        # POST_GO CHAINED ARM
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
        if self.post_go != 'go' and self._target_object:
            self._target_object.arm(self._conf, ossia, self._armed_list)

        # PREWAIT
        if self.prewait > 0:
            sleep(self.prewait.milliseconds / 1000)

        # PLAY : specific audio cue stuff
            # Set offset
        try:
            key = f'{self._osc_route}/offset'
            self._start_mtc = CTimecode(frames=mtc.main_tc.milliseconds)
            self._end_mtc = self._start_mtc + (self.media.regions[0].out_time - self.media.regions[0].in_time)
            offset_to_go = float(-(self._start_mtc.milliseconds) + self.media.regions[0].in_time.milliseconds)
            ossia.oscquery_registered_nodes[key][0].parameter.value = offset_to_go
            logger.info(key + " " + str(ossia.oscquery_registered_nodes[key][0].parameter.value))
        except KeyError:
            logger.debug(f'Key error 1 in go_callback {key}')

            # Connect to mtc signal
        try:
            key = f'{self._osc_route}/mtcfollow'
            ossia.oscquery_registered_nodes[key][0].parameter.value = 1
        except KeyError:
            logger.debug(f'Key error 2 in go_callback {key}')

        # POSTWAIT
        if self.postwait > 0:
            sleep(self.postwait.milliseconds / 1000)

        # POST-GO GO
        if self.post_go == 'go' and self._target_object:
                self._target_object.go(ossia, mtc)

        try:
            loop_counter = 0
            duration = self.media.regions[0].out_time - self.media.regions[0].in_time

            while not self.media.regions[0].loop or loop_counter < self.media.regions[0].loop:
                while self._player.is_alive() and (mtc.main_tc.milliseconds < self._end_mtc.milliseconds):
                    sleep(0.005)

                # Recalculate offset and apply
                self._start_mtc = CTimecode(frames=mtc.main_tc.milliseconds)
                self._end_mtc = self._start_mtc + (duration)
                offset_to_go = float(-(self._start_mtc.milliseconds) + self.media.regions[0].in_time.milliseconds)
                key = f'{self._osc_route}/offset'
                ossia.oscquery_registered_nodes[key][0].parameter.value = offset_to_go

                loop_counter += 1
                
            try:
                key = f'{self._osc_route}/mtcfollow'
                ossia.oscquery_registered_nodes[key][0].parameter.value = 0
            except KeyError:
                logger.debug(f'Key error 2 in go_callback {key}')

        except AttributeError:
            pass

        # POST-GO GO AT END
        if self.post_go == 'go_at_end' and self._target_object:
                self._target_object.go(ossia, mtc)

        if self in self._armed_list:
            self.disarm(ossia.conf_queue)

    def disarm(self, ossia_queue):
        if self.loaded is True:
            try:
                self._conf.players_port_index['used'].remove(self._player.port)
                self._player.kill()
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

    def stop(self):
        self._stop_requested = True
        if self._player and self._player.is_alive():
            self._player.kill()

    def check_mappings(self, settings):
        if settings.project_maps:
            found = False
            for output in self.outputs:
                if output['output_name'] == 'default':
                    break
                try:
                    out_list = settings.project_maps['audio']['outputs']
                except:
                    found = False
                else:
                    for each_out in out_list:
                        for each_map in each_out[0]['mappings']:
                            if output['output_name'] == each_map['mapped_to']:
                                found = True
                                break

            if not found:
                return False 
        else:
            for output in self.outputs:
                if output['output_name'] != 'default':
                    output['output_name'] = 'default'

        return True
