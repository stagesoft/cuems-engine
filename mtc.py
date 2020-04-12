from timecode import Timecode


class CTimecode(Timecode):
    def __init__(self, start_timecode=None, start_seconds=None, frames=None, framerate=25):
        super().__init__(framerate, start_timecode, start_seconds, frames)
    
    
    @property
    def milliseconds(self):
        """returns time as milliseconds
        """
        #TODO: float math for other framerates                               
        millis_per_frame = int(1000/self._int_framerate)
        return (millis_per_frame * self.frame_number)

    def __hash__(self):
        return hash((self.milliseconds, self.milliseconds))
    
    def __eq__(self, other):
        """Compares seconds of tc""" #TODO: decide if we cheek framerate and frame equality or time equiality 
        if isinstance(other, CTimecode):
            return self.milliseconds == other.milliseconds
        return NotImplemented
