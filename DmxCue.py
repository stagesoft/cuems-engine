from Cue import Cue


class DmxCue(Cue):
    def __init__(self, time, dmxscene, in_time=0, out_time=0):
        super().__init__(time)
        super().__setitem__('dmx_scene', dmxscene)
        super().__setitem__('in_time', in_time)
        super().__setitem__('out_time', out_time)

    

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

    def setall(self, value):
        for channel in range(512):
            super().__setitem__(channel, value)
        return self      #TODO: valorate return self to be able to do things like 'universe_full = DmxUniverse().setall(255)'

class DmxChannel(int):
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return str(self.value)