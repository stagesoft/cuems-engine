from threading import Thread
from time import sleep

from .Cue import Cue
from .VideoCue import VideoCue
from .AudioCue import AudioCue
from .run_cue import run_cue
from .arm_cue import arm_cue
from ..log import logged

class CueHandler():
    """
    This class is responsible for handling Cue objects.

    It is a singleton class, so it will
    only be instantiated once.

    Holds a list of armed cues and provides methods to use them.
    """
    _instace = None
    _armed_cues = []

    def __new__(cls, *args, **kwargs):
        """Ensure only one instance is created"""
        if not cls._instace:
            cls._instace = super(CueHandler, cls).__new__(cls)
        return cls._instace
    
    @staticmethod
    def arm(cue: Cue, ossia = None, init = False) -> bool:
        """
        Arms a cue by appending it to the armed_cues list
         and setting its loaded attribute to True
        
        Returns true if the cue is armed, false otherwise
        """
        _found = cue in CueHandler._armed_cues
        if cue.loaded:
            if not cue.enabled:
                _ = CueHandler.disarm(cue)
                return False
            elif not init:
                if not _found:
                    CueHandler._armed_cues.append(cue)
                return True
        
        # Type-specific arm method
        arm_cue(cue, ossia)

        cue.loaded = True
        if not _found:
            CueHandler._armed_cues.append(cue)

        if cue.post_go == 'go':
            _ = CueHandler.arm(cue._target_object, init)
        
        return True
    
    @staticmethod
    def disarm(cue: Cue) -> bool:
        """
        Disarms a cue by removing it from the armed_cues list
         and setting its loaded attribute to False

        Returns true if the cue is disarmed, false otherwise
        """
        if cue._player:
            cue._player.kill()
            cue._conf.players_port_index['used'].remove(cue._player.port)
            cue._player.join()
            cue._player = None
        
        if cue.loaded and cue in CueHandler._armed_cues:
            CueHandler._armed_cues.remove(cue)
            cue.loaded = False
            return True
    
        return False

    @staticmethod
    def get_next_cue(cue: Cue) -> Cue:
        """
        Returns the next cue to be played
        """
        if cue._target_object:
            return cue._target_object
        return None

    @logged
    @staticmethod
    def go(cue: Cue, ossia, mtc) -> Thread:
        """
        Starts a cue in a thread
        """
        if not cue.loaded:
            raise Exception(f'{cue.__class__.__name__} {cue.uuid} not loaded to go')
        # THREADED GO
        thread = Thread(
            name = f'GO:{cue.__class__.__name__}:{cue.uuid}',
            target = cue.go_threaded,
            args = [ossia, mtc]
        )
        thread.start()
        return thread

    @staticmethod
    def go_threaded(cue: Cue, ossia, mtc):
        """
        Runs a cue based on its properties
        """
        # ARM NEXT TARGET
        if cue._target_object and not cue._target_object.loaded:
            _ = CueHandler.arm(cue._target_object)
        
        # PREWAIT
        if cue.prewait > 0:
            sleep(cue.prewait.milliseconds / 1000)
        
        # PLAY CUE BASED ON TYPE
        run_cue(cue, ossia, mtc)
        
        # POSTWAIT
        if cue.postwait > 0:
            sleep(cue.postwait.milliseconds / 1000)
        
        # POST-GO GO
        if cue.post_go == 'go':
            CueHandler.go(cue._target_object, ossia, mtc)
        
        # MEDIA LOOP
        if isinstance(cue, VideoCue):
            cue.video_media_loop(ossia, mtc)
        elif isinstance(cue, AudioCue):
            cue.audio_media_loop(ossia, mtc)

         # POST-GO GO AT END
        if cue.post_go == 'go_at_end' and cue._target_object:
                cue._target_object.go(ossia, mtc)

        if cue in CueHandler._armed_cues:
            CueHandler.disarm(cue)
