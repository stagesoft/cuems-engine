from Cue import Cue
from collections.abc import Mapping


#### TODO: asegurar asignacion de escenas a cue, no copia!!

class DmxCue(Cue):
    def __init__(self, time=None, scene=None, in_time=0, out_time=0, init_dict=None):
        if init_dict:
            self.scene = init_dict.pop('dmx_scene', None)
        super().__init__(time, init_dict)
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
    

    

class DmxScene(dict):
    def __init__(self, init_dict=None):
        super().__init__()
        if init_dict:
            for k, v, in init_dict.items():
                if isinstance(k, int):
                    super().__setitem__(k, DmxUniverse(v))
                elif k == 'DmxUniverse':
                    print(k)
                    print(v)
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
                        super().__setitem__(u['id'], DmxChannel(u['value']))
    


    def channel(self, channel):
        return super().__getitem__(channel)

    def set_channel(self, channel, value):
        if value > 255:
            value = 255
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
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return str(self.value)