from threading import Thread, Lock
from time import sleep

from cuemsutils.cues import VideoCue, AudioCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import logged

from .run_cue import run_cue
from .arm_cue import arm_cue
from .loop_cue import loop_cue
from ..osc.OssiaClient import PlayerClient
from ..players import VideoPlayer, VideoClient
from ..players.PlayerHandler import PLAYER_HANDLER
from ..tools import MtcListener


class CueHandler:
    """
    Singleton class responsible for handling Cue objects.

    Holds a list of armed cues and manages video players.
    Thread-safe: internal state mutations are guarded by a Lock.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize instance attributes
            cls._instance._armed_cues = []
            cls._instance._video_players = {}
            cls._instance._front_video_player = None
            cls._instance._lock = Lock()
        return cls._instance

    ## Armed Cues List Methods

    def add_armed_cue(self, cue: Cue) -> None:
        """Adds an armed cue to the list."""
        with self._lock:
            self._armed_cues.append(cue)

    def get_armed_cues(self) -> list[Cue]:
        """Returns the list of armed cues."""
        with self._lock:
            return self._armed_cues

    def get_armed_cue(self, cue: Cue) -> Cue | None:
        """Returns the armed cue with the given uuid."""
        return self.get_armed_cues().get(cue, None)

    def remove_armed_cue(self, cue: Cue) -> bool:
        """Removes an armed cue from the list."""
        with self._lock:
            if cue in self._armed_cues:
                self._armed_cues.remove(cue)
                return True
        return False

    def reset_armed_cues(self) -> None:
        """Resets the list of armed cues."""
        with self._lock:
            self._armed_cues = []


    # ---------------------------
    # Cue Management
    # ---------------------------

    def arm(self, cue: Cue, init=False) -> bool:
        """Arms a cue by appending it to the armed_cues list."""
        with self._lock:
            _found = cue in self._armed_cues
        if hasattr(cue, 'loaded') and cue.loaded:
            if not cue.enabled:
                _ = self.disarm(cue)
            return False
        elif not init:
            if not _found:
                self.add_armed_cue(cue)
            return True
        
        if cue._local and cue.enabled:
            # Arm the cue
            arm_cue(cue)
            cue.loaded = True
            if not _found:
                self.add_armed_cue(cue)

        if cue.post_go == 'go':
            self.arm(cue._target_object, init)

        return True

    def disarm(self, cue: Cue) -> bool:
        """Disarms a cue by removing it from the armed_cues list."""
        PLAYER_HANDLER.remove_cue_player(cue)

        if hasattr(cue, 'loaded') and cue.loaded:
            self.remove_armed_cue(cue)
            cue.loaded = False
            return True

        return False

    def disarm_all(self) -> None:
        """Disarms all cues."""
        all_cues = self.get_armed_cues()
        for cue in all_cues:
            self.disarm(cue)
        self.reset_armed_cues()

    def get_next_cue(self, cue: Cue) -> Cue | None:
        """Returns the next cue to be played."""
        return cue._target_object if cue._target_object else None

    # ---------------------------
    # Cue Execution
    # ---------------------------

    @logged
    def go(self, cue: Cue, mtc: MtcListener) -> Thread:
        """Starts a cue in a thread."""
        if not cue.loaded:
            raise Exception(f'{cue.__class__.__name__} {cue.uuid} not loaded to go')

        thread = Thread(
            name=f'GO:{cue.__class__.__name__}:{cue.uuid}',
            target=self.go_threaded,
            args=[cue, mtc],
        )
        thread.start()

        # Arm next target if needed
        if isinstance(cue._target_object, Cue):
            if hasattr(cue._target_object, 'loaded') and not cue._target_object.loaded:
                self.arm(cue._target_object)
        return thread

    def go_threaded(self, cue: Cue, mtc: MtcListener):
        """Runs a cue based on its properties."""
        if cue.prewait > 0:
            sleep(cue.prewait.milliseconds / 1000)

        if cue._local:
            run_cue(cue, mtc)

        if cue.postwait > 0:
            sleep(cue.postwait.milliseconds / 1000)

        if cue.post_go == 'go':
            self.go(cue._target_object, mtc)

        loop_cue(cue, mtc)

        if cue.post_go == 'go_at_end' and cue._target_object:
            self.go(cue._target_object, mtc)

        self.disarm(cue)

# ---------------------------
# Singleton
# ---------------------------

CUE_HANDLER = CueHandler()
