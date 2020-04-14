from CTimecode import CTimecode

class Cue(dict):
    def __init__(self, time=None):
        super().__init__()
        self.time = time
    
    @property
    def time(self):
        return super().__getitem__('time')

    @time.setter
    def time(self, time):
        if isinstance(time, CTimecode):
            super().__setitem__('time', time)
        elif isinstance(time, (int, float)):
            corrected_seconds = CTimecode(start_seconds=time)
            corrected_seconds.frames = corrected_seconds.frames + 1
            super().__setitem__('time', corrected_seconds) #TODO: discuss this
        elif isinstance(time, str):
            super().__setitem__('time', CTimecode(time))
        else:
            raise NotImplementedError

    def __setitem__(self, key, value):
        if key == 'time':
            self.time = value
        else:
            super().__setitem__(key, value)
