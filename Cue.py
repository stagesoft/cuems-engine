from CTimecode import CTimecode

class Cue():
    def __init__(self, time=None):
        self.time = time
    @property
    def time(self):
        return self._time

    @time.setter
    def time(self, time):
        if isinstance(time, CTimecode):
            self._time = time
        elif isinstance(time, (int, float)):
            corrected_seconds = CTimecode(start_seconds=time)
            corrected_seconds.frames = corrected_seconds.frames + 1
            self._time = corrected_seconds #TODO: discuss this
        elif isinstance(time, str):
            self._time = CTimecode(time)
        else:
            raise NotImplementedError

    def __repr__(self):
        return self.time.__repr__()