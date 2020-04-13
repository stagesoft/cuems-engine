from Cue import Cue


class DmxCue(Cue):
    def __init__(self, time, dmxscene, in_time=0, out_time=0):
        super().__init__(time)
        self.in_time = in_time
        self.out_time = out_time
        self.dmxscene = dmxscene
    
    def __repr__(self):
        return str(dict({self.time.__repr__() : self.dmxscene}))

class DmxScene(dict):
    def __init__(self, *arg,**kw):
      super().__init__(*arg,**kw)

    def universe(self, num=0):
        return super().__getitem__(num)
      
    def set_universe(self, universe, num=0):
        super().__setitem__(num, universe)

       

        #merge two universes, priority on the newcoming
    def merge_universe(self, universe, num=0):
        super().__getitem__(num).update(universe)


class DmxUniverse(dict):

    def __init__(self, *arg,**kw):
        super().__init__(*arg,**kw)
    


    def channel(self, channel):
        return super().__getitem__(channel)

    def set_channel(self, channel, value):
        if value > 255:
            value = 255
        super().__setitem__(channel, value)

    def setall(self, value):
        for channel in range(512):
            super().__setitem__(channel, value)
        return self      #TODO: valorate return self to be able to do things like 'universe_full = DmxUniverse().setall(255)'

