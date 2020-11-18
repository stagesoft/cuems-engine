from timecode import Timecode
import json


class CTimecode(Timecode):
    def __init__(self, init_dict = None, start_timecode=None, start_seconds=None, frames=None, framerate='ms'):
        if init_dict is not None:
            super().__init__(framerate, init_dict, start_seconds, frames)
        else:
            if start_seconds == 0:
                start_seconds = None
                frames = 0
            super().__init__(framerate, start_timecode, start_seconds, frames)
    
    @classmethod
    def from_dict(cls, init_dict):
        return cls(init_dict =  init_dict)
    @property

    
    def milliseconds(self):
        """returns time as milliseconds
        """
        #TODO: float math for other framerates                               
        millis_per_frame = 1000 / float(self._framerate)
        return int(millis_per_frame * self.frame_number)

    def __hash__(self):
        return hash((self.milliseconds, self.milliseconds))
    
    def __eq__(self, other):
        """Compares seconds of tc""" #TODO: decide if we cheek framerate and frame equality or time equiality 
        if isinstance(other, CTimecode):
            return self.milliseconds == other.milliseconds
        return NotImplemented

    def __ne__(self, other):
        """Compares seconds of tc""" #TODO: decide if we cheek framerate and frame equality or time equiality 
        if isinstance(other, CTimecode):
            return self.milliseconds != other.milliseconds
        return NotImplemented

    def __lt__(self, other):
        """Compares seconds of tc""" #TODO: decide if we cheek framerate and frame equality or time equiality 
        if isinstance(other, CTimecode):
            return self.milliseconds < other.milliseconds
        elif isinstance(other, int):
            return self.milliseconds < other
        elif isinstance(other, type(None)):
            return other

        return NotImplemented

    def __le__(self, other):
        """Compares seconds of tc""" #TODO: decide if we cheek framerate and frame equality or time equiality 
        if isinstance(other, CTimecode):
            return self.milliseconds <= other.milliseconds
        elif isinstance(other, type(None)):
            return other
        return NotImplemented

    def __gt__(self, other):
        """Compares seconds of tc""" #TODO: decide if we cheek framerate and frame equality or time equiality 
        if isinstance(other, CTimecode):
            return self.milliseconds > other.milliseconds
        elif isinstance(other, int):
            return self.milliseconds > other
        elif isinstance(other, type(None)):
            return self 
        return NotImplemented

    def __ge__(self, other):
        """Compares seconds of tc""" #TODO: decide if we cheek framerate and frame equality or time equiality 
        if isinstance(other, CTimecode):
            return self.milliseconds >= other.milliseconds
        elif isinstance(other, type(None)):
            return self
        return NotImplemented

    def __add__(self, other):
        """returns new CTimecode instance with the given timecode or frames
        added to this one
        """
        # duplicate current one
        tc = CTimecode(framerate=self._framerate, frames=self.frames)

        if isinstance(other, CTimecode):
            tc.add_frames(other.frames)
        elif isinstance(other, int):
            tc.add_frames(other)
        else:
            raise CTimecodeError(
                'Type %s not supported for arithmetic.' %
                other.__class__.__name__
            )

        return tc

    def __sub__(self, other):
        """returns new CTimecode instance with subtracted value"""
        if isinstance(other, CTimecode):
            subtracted_frames = self.frames - other.frames
        elif isinstance(other, int):
            subtracted_frames = self.frames - other
        else:
            raise CTimecodeError(
                'Type %s not supported for arithmetic.' %
                other.__class__.__name__
            )

        return CTimecode(framerate=self._framerate, frames=subtracted_frames)

    def __mul__(self, other):
        """returns new CTimecode instance with multiplied value"""
        if isinstance(other, CTimecode):
            multiplied_frames = self.frames * other.frames
        elif isinstance(other, int):
            multiplied_frames = self.frames * other
        else:
            raise CTimecodeError(
                'Type %s not supported for arithmetic.' %
                other.__class__.__name__
            )

        return CTimecode(framerate=self._framerate, frames=multiplied_frames)

    def __div__(self, other):
        """returns new CTimecode instance with divided value"""
        if isinstance(other, CTimecode):
            div_frames = self.frames / other.frames
        elif isinstance(other, int):
            div_frames = self.frames / other
        else:
            raise CTimecodeError(
                'Type %s not supported for arithmetic.' %
                other.__class__.__name__
            )

        return CTimecode(framerate=self._framerate, frames=div_frames)

    def __str__(self):
        return self.tc_to_string(*self.frames_to_tc(self.frames))

    def __iter__(self):
        yield ('timecode', self.__str__())
        yield ('framerate', self.framerate)
    


class CTimecodeError(Exception):
    """Raised when an error occurred in timecode calculation
    """
    pass