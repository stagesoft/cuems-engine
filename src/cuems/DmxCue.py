from threading import Thread
from time import sleep

from collections.abc import Mapping
from os import path
from pyossia import ossia
from .Cue import Cue
from .DmxPlayer import DmxPlayer
from .OssiaServer import OssiaServer, OSCConfData, PlayerOSCConfData
from .log import logger

#### TODO: asegurar asignacion de escenas a cue, no copia!!

class DmxCue(Cue):
    OSC_DMXPLAYER_CONF = {  '/quit' : [ossia.ValueType.Impulse, None],
                            '/load' : [ossia.ValueType.String, None], 
                            '/wait' : [ossia.ValueType.Float, None],
                            '/play' : [ossia.ValueType.Impulse, None],
                            '/stop' : [ossia.ValueType.Impulse, None],
                            '/stoponlost' : [ossia.ValueType.Bool, None],
                            # TODO '/mtcfollow' : [ossia.ValueType.Bool, None],
                            '/check' : [ossia.ValueType.Impulse, None]
                            }

    def __init__(self, init_dict = None):
        super().__init__(init_dict)
            
        self._player = None
        self._osc_route = None
        self._offset_route = '/offset'

        self.OSC_DMXPLAYER_CONF[self._offset_route] = [ossia.ValueType.Float, None]
        

    @property
    def media(self):
        return super().__getitem__('Media')

    @media.setter
    def media(self, media):
        super().__setitem__('Media', media)

    @property
    def fadein_time(self):
        return super().__getitem__('fadein_time')

    @fadein_time.setter
    def fadein_time(self, fadein_time):
        super().__setitem__('fadein_time', fadein_time)

    @property
    def fadeout_time(self):
        return super().__getitem__('fadeout_time')

    @fadeout_time.setter
    def fadeout_time(self, fadeout_time):
        super().__setitem__('fadeout_time', fadeout_time)

    def player(self, player):
        self._player = player

    def osc_route(self, osc_route):
        self._osc_route = osc_route

    def offset_route(self, offset_route):
        self._offset_route = offset_route

    def review_offset(self, timecode):
        return -(float(timecode.milliseconds))

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
        try:
            self._player = DmxPlayer(   self._conf.players_port_index, 
                                        self._conf.node_conf['dmxplayer']['path'],
                                        str(self._conf.node_conf['dmxplayer']['args']),
                                        str(path.join(self._conf.library_path, 'media', self.media['file_name'])))
        except Exception as e:
            raise e

        self._player.start()

        # And dinamically attach it to the ossia for remote control it
        self._osc_route = f'/players/dmxplayer-{self.uuid}'

        ossia.add_player_nodes( PlayerOSCConfData(  device_name=self._osc_route, 
                                                    host=self._conf.node_conf['osc_dest_host'], 
                                                    in_port=self._player.port,
                                                    out_port=self._player.port + 1, 
                                                    dictionary=self.OSC_DMXPLAYER_CONF))

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

        # PLAY : specific DMX cue stuff
        try:
            key = f'{self._osc_route}{self._offset_route}'
            ossia.osc_registered_nodes[key][0].value = self.review_offset(mtc)
            logger.info(key + " " + str(ossia.osc_registered_nodes[key][0].value))
        except KeyError:
            logger.debug(f'OSC key error 1 in go_callback {key}')

        try:
            key = f'{self._osc_route}/mtcfollow'
            ossia.osc_registered_nodes[key][0].value = True
        except KeyError:
            logger.debug(f'OSC key error 2 in go_callback {key}')

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
            self.disarm(ossia)

    def disarm(self, ossia):
        if self.loaded is True:
            try:
                self._player.kill()
                self._conf.players_port_index['used'].remove(self._player.port)
                self._player.join()
                self._player = None

                ossia.remove_nodes( OSCConfData(device_name=self._osc_route, dictionary = self.OSC_DMXPLAYER_CONF) )

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

    @property
    def scene(self):
        return self['dmx_scene']

    @scene.setter
    def scene(self, scene):
        if isinstance(scene, DmxScene):
            super().__setitem__('dmx_scene', scene)
        elif isinstance(scene, dict):
            super().__setitem__('dmx_scene', DmxScene(init_dict=scene))
        else:
            raise NotImplementedError

class DmxScene(dict):
    def __init__(self, init_dict=None):
        super().__init__()
        if init_dict:
            for k, v, in init_dict.items():
                if isinstance(k, int):
                    super().__setitem__(k, DmxUniverse(v))
                elif k == 'DmxUniverse':
                    for u in v:
                        super().__setitem__(u['id'], DmxUniverse(init_dict=u))

    def universe(self, num=None):
        if num is not None:
            return super().__getitem__(num)

    def universes(self):
        return self
      
    def set_universe(self, universe, num=0):
        super().__setitem__(num, DmxUniverse(universe))

       

        #merge two universes, priority on the newcoming
    def merge_universe(self, universe, num=0):
        super().__getitem__(num).update(universe)



class DmxUniverse(dict):

    def __init__(self, init_dict=None):
        super().__init__()
        if init_dict:
            for k, v, in init_dict.items():
                if isinstance(k, int):
                    super().__setitem__(k, DmxChannel(v))
                elif k == 'DmxChannel':
                    for u in v:
                        super().__setitem__(u['id'], DmxChannel(u['&']))
    


    def channel(self, channel):
        return super().__getitem__(channel)

    def set_channel(self, channel, value):
        if isinstance(value, DmxChannel):
            super().__setitem__(channel, value)
        else:
            super().__setitem__(channel, DmxChannel(value))
        return self

    def setall(self, value):
        for channel in range(512):
            super().__setitem__(channel, value)
        return self      #TODO: valorate return self to be able to do things like 'universe_full = DmxUniverse().setall(255)'

    def update(self, other=None, **kwargs):
        if other is not None:
            for k, v in other.items() if isinstance(other, Mapping) else other:
                self[k] = DmxChannel(v)
        for k, v in kwargs.items():
            self[k] = DmxChannel(v)

class DmxChannel():
    def __init__(self, value=None, init_dict = None):
        self._value = value
        if init_dict is not None:
            self.value = init_dict

    def __repr__(self):
        return str(self.value)

    @property
    def value(self):
        return self._value
    
    @value.setter
    def value (self, value):
        if value > 255:
            value = 255
        self._value = value
