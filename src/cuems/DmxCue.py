from collections.abc import Mapping
from os import path
from pyossia import ossia
from .Cue import Cue
from .DmxPlayer import DmxPlayer
from .OssiaServer import QueueOSCData
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

    def __init__(self, time=None, scene=None, in_time=0, out_time=0, init_dict=None):
        super().__init__(time, init_dict)
        self._player = None
        self._osc_route = None
        self._offset_route = '/offset'

        self.conf = None
        self.ossia_queue = None
        self.armed_list = None

        self.OSC_DMXPLAYER_CONF[self._offset_route] = [ossia.ValueType.Float, None]

        if scene:
                self.scene = scene
        
        super().__setitem__('in_time', in_time)
        super().__setitem__('out_time', out_time)

    @property
    def Media(self):
        return super().__getitem__('Media')

    @Media.setter
    def Media(self, Media):
        super().__setitem__('Media', Media)

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

    def arm(self, conf, queue, armed_list):
        self.conf = conf
        self.ossia_queue = queue
        self.armed_list = armed_list

        if not self.enabled or not self.loaded:
            if not self.enabled and self.loaded:
                self.disarm(conf, queue, armed_list)
            return False

        try:
            # Assign its own audioplayer object
            self._player = DmxPlayer(    conf.players_port_index, 
                                        conf.node_conf['dmxplayer']['path'],
                                        str(conf.node_conf['dmxplayer']['args']),
                                        str(path.join(conf.library_path, 'media', self.Media['file_name'])))
        except Exception as e:
            raise e

        self._player.start()

        # And dinamically attach it to the ossia for remote control it
        self._osc_route = f'/node{conf.node_conf["id"]:03}/dmxplayer-{self.uuid}'

        queue.put(   QueueOSCData(  'add', 
                                    self._osc_route, 
                                    conf.node_conf['osc_dest_host'], 
                                    self._player.port,
                                    self._player.port + 1, 
                                    self.OSC_DMXPLAYER_CONF))

        self.loaded = True
        if not self in armed_list:
            armed_list.append(self)

        return True

    def disarm(self, conf, queue, armed_list):
        if self.loaded is True:
            try:
                self._player.kill()
                conf.players_port_index['used'].remove(self._player.port)
                self._player.join()
                self._player = None

                queue.put(QueueOSCData( 'remove', 
                                        self._osc_route, 
                                        dictionary = self.OSC_DMXPLAYER_CONF))

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
            print(init_dict)
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