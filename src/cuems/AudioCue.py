from os import path
from pyossia import ossia
from time import sleep
from threading import Thread

from .Cue import Cue
from .CTimecode import CTimecode
from .AudioPlayer import AudioPlayer
from .OssiaServer import OssiaServer, OSCConfData, PlayerOSCConfData
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
                self.disarm(ossia)
            return False
        elif self.loaded and not init:
            if not self in self._armed_list:
                self._armed_list.append(self)
            return True

        # Assign its own audioplayer object
        if self._local:
            try:
                self._player = AudioPlayer( self._conf.osc_port_index, 
                                            self._conf.node_conf['audioplayer']['path'],
                                            self._conf.node_conf['audioplayer']['args'],
                                            str(path.join(self._conf.library_path, 'media', self.media['file_name'])),
                                            self.uuid)
            except Exception as e:
                raise e

            self._player.start()

            # And dinamically attach it to the ossia for remote control it
            self._osc_route = f'/players/audioplayer-{self.uuid}'

            ossia.add_player_nodes( PlayerOSCConfData(  device_name=self._osc_route, 
                                                        host=self._conf.node_conf['osc_dest_host'], 
                                                        in_port=self._player.port,
                                                        out_port=self._player.port + 1, 
                                                        dictionary=self.OSC_AUDIOPLAYER_CONF) )

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

        ### harcoded for TODO: proto_fruta, need fixx
         #try to make all cues start at sync at 40 second timecode!
        harcoded_go_offset = 40

        if self._local:
            try:
                key = f'{self._osc_route}/offset'
                #framerate in milliseconds base, 1frame = 1 milliseconds
                #self._start_mtc = CTimecode(frames=mtc.main_tc.milliseconds)
                
                self._start_mtc = CTimecode(start_seconds = harcoded_go_offset, framerate=25)
                # round IN FRAMES SO IT MATCHES VIDEO DURATION when doing loops with audio an video
                duration = self.media.regions[0].out_time - self.media.regions[0].in_time
                duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
                self._end_mtc = self._start_mtc + duration
                cue_in_time_fr_adjusted = self.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate)
                offset_to_go = cue_in_time_fr_adjusted.frame_number - self._start_mtc.frame_number
                #now callculate rounded time to frames in milliseconds for audioplayer
                offset_to_go = offset_to_go * (1000/mtc.main_tc.framerate)
                ossia.send_message(key, offset_to_go)
                logger.info(key + " " + str(ossia._oscquery_registered_nodes[key][0].value))
            except KeyError:
                logger.debug(f'Key error 1 in go_callback {key}')

                # Connect to mtc signal
            try:
                key = f'{self._osc_route}/mtcfollow'
                ossia.send_message(key, 1)
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
            duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
            in_time_adjusted = self.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate)

            while not self.media.regions[0].loop or loop_counter < self.media.regions[0].loop:
                while self._player.is_alive() and (mtc.main_tc.milliseconds < self._end_mtc.milliseconds):
                    sleep(0.005)

                if self._local:
                    # Recalculate offset and apply
                    # round IN FRAMES SO IT MATCHES VIDEO DURATION when doing loops with audio an video
                    self._start_mtc = mtc.main_tc
                    self._end_mtc = self._start_mtc + duration
                    offset_to_go = in_time_adjusted.frame_number - self._start_mtc.frame_number
                    #now callculate rounded time to frames in milliseconds for audioplayer
                    offset_to_go = offset_to_go * 40
                    try:
                        key = f'{self._osc_route}/offset'
                        ossia.send_message(key, offset_to_go)
                    except KeyError:
                        logger.debug(f'Key error 3 in go_callback {key}')

                loop_counter += 1

            if self._local:                
                try:
                    key = f'{self._osc_route}/mtcfollow'
                    ossia.send_message(key, 0)
                except KeyError:
                    logger.debug(f'Key error 4 in go_callback {key}')

        except AttributeError:
            pass

        # POST-GO GO AT END
        if self.post_go == 'go_at_end' and self._target_object:
                self._target_object.go(ossia, mtc)

        if self in self._armed_list:
            self.disarm(ossia)

    def disarm(self, ossia):
        if self.loaded is True:
            try:
                self._conf.osc_port_index['used'].remove(self._player.port)
                self._player.kill()
                self._player = None

                ossia.remove_nodes( OSCConfData(device_name=self._osc_route, dictionary=self.OSC_AUDIOPLAYER_CONF) )

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
        if not settings.project_node_mappings:
            return True

        found = True
        
        map_list = ['default']

        if settings.project_node_mappings['audio']['outputs']:
            m = settings.project_node_mappings['audio']['outputs']
            for elem in settings.project_node_mappings['audio']['outputs']:
                for map in elem['mappings']:
                    map_list.append(map['mapped_to'])
        
        for output in self.outputs:
            #if output['node_uuid'] == settings.node_conf['uuid']:

            if output['output_name'][:36] == settings.node_conf['uuid']:
                    self._local = True
                    if output['output_name'][37:] not in map_list:
                        found = False
                        break
            else:
                self._local = False
                found = True
            
        return found
