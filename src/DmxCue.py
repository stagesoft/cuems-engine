from Cue import Cue
from collections.abc import Mapping


#### TODO: asegurar asignacion de escenas a cue, no copia!!

class DmxCue(Cue):
    def __init__(self, time=None, dmxscene=None, in_time=0, out_time=0):
        super().__init__(time)
        if dmxscene:
            if isinstance(dmxscene, DmxScene):
                super().__setitem__('dmx_scene', dmxscene)
            else:
                raise NotImplementedError
        
        if in_time:
            super().__setitem__('in_time', in_time)
        if out_time:
            super().__setitem__('out_time', out_time)

    def dmxscene(self, dmxscene):
        if isinstance(dmxscene, DmxScene):
            super().__setitem__('dmx_scene', dmxscene)
        else:
            raise NotImplementedError

    

class DmxScene(dict):
    def __init__(self, universe=None):
        super().__init__()
        if dict:
            for k, v, in universe.items():
                super().__setitem__(k, DmxUniverse(v))

    def universe(self, num=0):
        return super().__getitem__(num)
      
    def set_universe(self, universe, num=0):
        super().__setitem__(num, DmxUniverse(universe))

       

        #merge two universes, priority on the newcoming
    def merge_universe(self, universe, num=0):
        super().__getitem__(num).update(universe)


class DmxUniverse(dict):

    def __init__(self, dict=None):
        super().__init__()
        if dict:
            for k, v, in dict.items():
                super().__setitem__(k, DmxChannel(v))
    


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

class DmxChannel(int):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return str(self.value)