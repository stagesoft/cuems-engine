from CTimecode import CTimecode

class Cue(dict):
    def __init__(self, time=None, init_dict=None):
        if init_dict:
            self.time = init_dict.pop('time', None)

            super().__init__(init_dict)
        else:
            super().__init__()
        if time is not None:
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
        elif isinstance(time, dict):
            dict_timecode = time.pop('CTimecode', None)
            print(dict_timecode)
            if dict_timecode is None:
                super().__setitem__('time', None)
            else:
                super().__setitem__('time', CTimecode(dict_timecode))
        elif time == None:
            super().__setitem__('time', None)
        else:
            raise NotImplementedError #TODO: disscuss raised error

    def type(self):
        return type(self)


    def __setitem__(self, key, value):
        if key == 'time':
            self.time = value
        else:
            super().__setitem__(key, value)
