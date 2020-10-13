from collections.abc import Mapping
from os import path
from pyossia import ossia
from .Cue import Cue
from .DmxPlayer import DmxPlayer
from .OssiaServer import QueueOSCData


#### TODO: asegurar asignacion de escenas a cue, no copia!!

class DmxCue(Cue):
    def __init__(self, time=None, scene=None, in_time=0, out_time=0, init_dict=None):
        super().__init__(time, init_dict)
        self.offset_route = '/offset'

        if scene:
                self.scene = scene
        
        if in_time:
            super().__setitem__('in_time', in_time)
        if out_time:
            super().__setitem__('out_time', out_time)
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

    @property
    def player(self):
        return super().__getitem__('player')

    @player.setter
    def player(self, player):
        super().__setitem__('player', player)

    @property
    def osc_route(self):
        return super().__getitem__('osc_route')

    @osc_route.setter
    def osc_route(self, osc_route):
        super().__setitem__('osc_route', osc_route)

    @property
    def offset_route(self):
        return super().__getitem__('offset_route')

    @offset_route.setter
    def offset_route(self, offset_route):
        super().__setitem__('offset_route', offset_route)

    def review_offset(self, timecode):
        return -(float(timecode.milliseconds))

    @property
    def armed(self):
        return super().__getitem__('armed')

    @armed.setter
    def armed(self, armed):
        super().__setitem__('armed', armed)

    def arm(self, conf, queue):
        # Assign its own audioplayer object
        self.player = DmxPlayer(    conf.players_port_index['dmx'], 
                                    conf.node_conf['dmxplayer']['path'],
                                    str(conf.node_conf['dmxplayer']['args']),
                                    str(path.join(conf.library_path, 'media', self.media)))

        self.player.start()

        # And dinamically attach it to the ossia for remote control it
        OSC_DMXPLAYER_CONF = {  '/quit' : [ossia.ValueType.Impulse, None],
                                '/load' : [ossia.ValueType.String, None], 
                                self.offset_route : [ossia.ValueType.Float, None],
                                '/wait' : [ossia.ValueType.Float, None],
                                '/play' : [ossia.ValueType.Impulse, None],
                                '/stop' : [ossia.ValueType.Impulse, None],
                                '/stoponlost' : [ossia.ValueType.Bool, None],
                                # TODO '/mtcfollow' : [ossia.ValueType.Bool, None],
                                '/check' : [ossia.ValueType.Impulse, None]
                                }

        self.osc_route = f'/node{conf.node_conf["id"]:03}/dmxplayer-{self.uuid}'

        queue.put(   QueueOSCData(  'add', 
                                    self.osc_route, 
                                    conf.node_conf['osc_dest_host'], 
                                    conf.players_port_index['dmx'],
                                    conf.players_port_index['dmx'] + 1, 
                                    OSC_DMXPLAYER_CONF))

        conf.players_port_index['audio'] = conf.players_port_index['audio'] + 2

        self.armed = True

    def disarm(self, cm, queue):
        self.armed = False


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