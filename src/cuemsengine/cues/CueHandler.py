import asyncio
from threading import Lock

from cuemsutils.cues import VideoCue, AudioCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import logged, Logger

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
            cls._instance._armed_cues: list[Cue] = []
            cls._instance._armed_cues_set: set[str] = set()
            cls._instance._video_players = {}
            cls._instance._front_video_player = None
            cls._instance._lock = Lock()
        return cls._instance

    ## Armed Cues List Methods

    def add_armed_cue(self, cue: Cue) -> None:
        """Adds an armed cue to the list."""
        with self._lock:
            self._armed_cues.append(cue)
            self._armed_cues_set.add(cue.id)

    def get_armed_cues(self) -> list[Cue]:
        """Returns the list of armed cues."""
        with self._lock:
            return self._armed_cues

    def get_armed_cue(self, cue: Cue) -> Cue | None:
        """Returns the armed cue with the given uuid."""
        try:
            return self.get_armed_cues().index(cue)
        except ValueError:
            return None

    def find_armed_cue(self, cue: Cue) -> Cue | None:
        """Finds an armed cue with the given uuid."""
        with self._lock:
            return cue.id in self._armed_cues_set

    def remove_armed_cue(self, cue: Cue) -> bool:
        """Removes an armed cue from the list."""
        with self._lock:
            if cue.id in self._armed_cues_set:
                self._armed_cues.remove(cue)
                self._armed_cues_set.remove(cue.id)
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
            found = cue in self._armed_cues
        if hasattr(cue, 'loaded') and cue.loaded:
            if not cue.enabled:
                _ = self.disarm(cue)
            return False
        elif not init:
            if not found:
                self.add_armed_cue(cue)
            return True
        
        if cue._local and cue.enabled:
            Logger.info(f"Arming {type(cue)} {cue.id}")
            # Arm the cue
            arm_cue(cue)
            cue.loaded = True
            if not found:
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
    def go(self, cue: Cue, mtc: MtcListener):
        """Starts a cue in an async task."""
        Logger.info(f'GO command received. Starting cue {cue.id}')
        if not cue.loaded:
            raise Exception(f'{cue.__class__.__name__} {cue.id} not loaded to go')

        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        task = loop.create_task(
            self._go_async(cue, mtc),
            name=f'GO:{cue.__class__.__name__}:{cue.id}'
        )

        # Arm next target if needed
        if isinstance(cue._target_object, Cue):
            if hasattr(cue._target_object, 'loaded') and not cue._target_object.loaded:
                self.arm(cue._target_object)
        return task

    async def _go_async(self, cue: Cue, mtc: MtcListener):
        """Runs a cue based on its properties."""
        if cue.prewait > 0:
            await asyncio.sleep(cue.prewait.milliseconds / 1000)

        if cue._local:
            await run_cue(cue, mtc)

        if cue.postwait > 0:
            await asyncio.sleep(cue.postwait.milliseconds / 1000)

        if cue.post_go == 'go':
            Logger.info(f'Running post go for next cue:{cue.target}')
            post_go_task = self.go(cue._target_object, mtc)

        Logger.info(f'Going to loop for {cue.__class__.__name__}:{cue.id}')
        await loop_cue(cue, mtc)

        if cue.post_go == 'go_at_end' and cue._target_object:
            Logger.info(f'Running go at end for {cue.__class__.__name__}:{cue.id}')
            go_at_end_task = self.go(cue._target_object, mtc)

        self.disarm(cue)

        if cue.post_go == 'go_at_end':
            await self._wait_for_task(go_at_end_task)

        if cue.post_go == 'go':
            await self._wait_for_task(post_go_task)

    async def _wait_for_task(self, task: asyncio.Task) -> None:
        """Waits for a task to finish."""
        Logger.info(f'Waiting for {task.get_name()} to finish')
        await task
        Logger.info(f'{task.get_name()} finished')

# ---------------------------
# Singleton
# ---------------------------

CUE_HANDLER = CueHandler()
