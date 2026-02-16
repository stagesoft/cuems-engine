from threading import Thread, Lock
from time import sleep

from cuemsutils.cues import VideoCue, AudioCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import logged, Logger

from ..comms.NodeCommunications import NodeCommunications
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


    # ---------------------------
    # Communications To Controller
    # ---------------------------
    def set_nng_comms(self, hub_address: str, node_id: str):
        """Set the communications infrastructure"""
        from time import sleep
        
        Logger.info(f"Starting communications for Node {node_id}")
        Logger.info(f"NNG Hub address: {hub_address}")
        self.communications_thread = NodeCommunications(
            hub_address=hub_address,
            node_id=node_id
        )
        self.communications_thread.start()
        
        # Wait for NNG thread to initialize (prevents race condition in nni_random)
        max_wait = 5.0  # seconds
        wait_interval = 0.1
        waited = 0.0
        while waited < max_wait:
            if (self.communications_thread.is_alive() and 
                self.communications_thread.event_loop is not None):
                Logger.info(f"NNG communications thread ready after {waited:.1f}s")
                break
            sleep(wait_interval)
            waited += wait_interval
        else:
            Logger.warning(f"NNG communications thread not ready after {max_wait}s")

    # ---------------------------
    # Armed Cues List Methods
    # ---------------------------

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
            Logger.info(f"Arming {type(cue).__name__} {cue.id}")
            # Arm the cue
            arm_cue(cue)
            cue.loaded = True
            if not found:
                self.add_armed_cue(cue)
            if isinstance(cue, AudioCue):
                # Non-blocking NNG notification (fire-and-forget)
                try:
                    self.communications_thread.add_player(f'audioplayer_{cue.id}', None, timeout=0.1)
                except Exception:
                    pass  # Ignore - NNG is for distributed nodes

        if cue.post_go == 'go':
            self.arm(cue._target_object, init)

        return True

    def disarm(self, cue: Cue) -> bool:
        """Disarms a cue by removing it from the armed_cues list."""
        PLAYER_HANDLER.remove_cue_player(cue)

        if hasattr(cue, 'loaded') and cue.loaded:
            self.remove_armed_cue(cue)
            cue.loaded = False
            # Non-blocking NNG notifications (fire-and-forget)
            try:
                if isinstance(cue, AudioCue):
                    self.communications_thread.remove_player(f'audioplayer_{cue.id}', timeout=0.1)
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass  # Ignore - NNG is for distributed nodes
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
    def go(self, cue: Cue, mtc: MtcListener, frozen_mtc_ms: float = None) -> Thread:
        """Starts a cue in a thread.
        
        Args:
            cue: The cue to start
            mtc: The MTC listener
            frozen_mtc_ms: Optional frozen MTC timestamp for sync with chained cues
        """
        Logger.info(f'GO command received. Starting cue {cue.id}')
        if not hasattr(cue, 'loaded') or not cue.loaded:
            raise Exception(f'{cue.__class__.__name__} {cue.id} not loaded to go')

        thread = Thread(
            name=f'GO:{cue.__class__.__name__}:{cue.id}',
            target=self.go_threaded,
            args=[cue, mtc, frozen_mtc_ms],
            daemon=True
        )
        thread.start()

        # Arm next target if needed
        if isinstance(cue._target_object, Cue):
            if hasattr(cue._target_object, 'loaded') and not cue._target_object.loaded:
                self.arm(cue._target_object)
        return thread

    def go_threaded(self, cue: Cue, mtc: MtcListener, frozen_mtc_ms: float = None):
        """Runs a cue based on its properties.
        
        Args:
            cue: The cue to run
            mtc: The MTC listener (for live MTC)
            frozen_mtc_ms: Optional frozen MTC timestamp in milliseconds.
                           If provided, this timestamp is used for sync calculations
                           and passed to chained cues (post_go='go') to ensure they
                           all use the same reference time.
        """
        if cue.prewait > 0:
            sleep(cue.prewait.milliseconds / 1000)
        
        # CRITICAL FOR SYNC: Capture MTC timestamp ONCE for this cue and all chained cues
        # This ensures that when post_go='go' triggers another cue, both use the same time
        if frozen_mtc_ms is None:
            frozen_mtc_ms = float(mtc.main_tc.milliseconds)
            Logger.debug(f'Captured MTC snapshot for cue {cue.id}: {frozen_mtc_ms}ms')

        if cue._local:
            # Run cue immediately - pass both live MTC (for framerate) and frozen timestamp
            run_cue(cue, mtc, frozen_mtc_ms)
            
            # Notify controller in background (fire-and-forget)
            try:
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass  # Ignore - this is just for status tracking

        if cue.postwait > 0:
            sleep(cue.postwait.milliseconds / 1000)

        if cue.post_go == 'go':
            Logger.info(f'Running post go for next cue:{cue.target}')
            # Pass the SAME frozen_mtc_ms to the chained cue for perfect sync
            post_go_thread = self.go(cue._target_object, mtc, frozen_mtc_ms)

        Logger.info(f'Going to loop for {cue.__class__.__name__}:{cue.id}')
        loop_cue(cue, mtc)

        if cue.post_go == 'go_at_end' and cue._target_object:
            Logger.info(f'Running go at end for {cue.__class__.__name__}:{cue.id}')
            go_at_end_thread = self.go(cue._target_object, mtc)

        self.disarm(cue)

        if cue.post_go == 'go_at_end':
            self.wait_for_cue(go_at_end_thread)

        if cue.post_go == 'go':
            self.wait_for_cue(post_go_thread)

    def wait_for_cue(self, thread: Thread) -> None:
        """Waits for a cue to finish."""
        Logger.info(f'Waiting for {thread.name} to finish')
        while thread.is_alive():
            sleep(1)
        thread.join()
        Logger.info(f'{thread.name} finished')

    # ---------------------------
    # OSCQuery Message Routing
    # ---------------------------

    def route_audio_message(self, path_parts: list[str], value) -> None:
        """Route audio OSCQuery message to the appropriate handler.

        Args:
            path_parts: Path parts after 'audio' (e.g., ['mixer', '0', 'master', 'volume']
                        or ['cue', '<uuid>', '0', 'volume'])
            value: The OSC value to set
        """
        if not path_parts:
            Logger.warning("Empty audio path parts")
            return

        if path_parts[0] == 'mixer':
            # Route to audio mixer: ['mixer', '<output_index>', '<channel>', 'volume']
            # → /audiomixer/0_mixer/<channel>
            if len(path_parts) >= 3:
                output_index = path_parts[1]
                channel = path_parts[2]
                mixer_cmd = f'/audiomixer/{output_index}_mixer/{channel}'
                mixer_client = PLAYER_HANDLER.get_audio_mixer_client()
                if mixer_client:
                    Logger.debug(f"Routing audio mixer: {mixer_cmd} = {value}")
                    mixer_client.set_value(mixer_cmd, float(value))
                else:
                    Logger.warning("Audio mixer client not available")
            else:
                Logger.warning(f"Invalid mixer path: {path_parts}")

        elif path_parts[0] == 'cue':
            # Route to cue player: ['cue', '<uuid>', '<channel>', 'volume']
            # → /vol<channel> on the armed cue's OSC client
            if len(path_parts) >= 3:
                cue_uuid = path_parts[1]
                channel = path_parts[2]
                audio_cmd = f'/vol{channel}'
                cue = self.get_armed_cue_by_id(cue_uuid)
                if cue and hasattr(cue, '_osc') and cue._osc:
                    Logger.debug(f"Routing audio cue {cue_uuid}: {audio_cmd} = {value}")
                    cue._osc.set_value(audio_cmd, float(value))
                else:
                    Logger.warning(f"Cue {cue_uuid} not found or has no OSC client")
            else:
                Logger.warning(f"Invalid cue audio path: {path_parts}")
        else:
            Logger.warning(f"Unknown audio path type: {path_parts[0]}")

    def route_dmx_message(self, path_parts: list[str], value) -> None:
        """Route DMX OSCQuery message to the DMX player.

        Args:
            path_parts: Path parts after 'dmx' (e.g., ['mixer', '0', 'channel', '1'])
            value: The OSC value to set
        """
        if not path_parts:
            Logger.warning("Empty DMX path parts")
            return

        # Build DMX command from path: find 'mixer' and use everything after it
        if 'mixer' in path_parts:
            mixer_index = path_parts.index('mixer') + 1  # +1 to skip 'mixer' keyword
            dmx_cmd = '/' + '/'.join(path_parts[mixer_index:])
            dmx_client = PLAYER_HANDLER.get_dmx_player_client()
            if dmx_client:
                Logger.debug(f"Routing DMX: {dmx_cmd} = {value}")
                dmx_client.set_value(dmx_cmd, value)
            else:
                Logger.warning("DMX player client not available")
        else:
            Logger.warning(f"Invalid DMX path (no 'mixer' keyword): {path_parts}")

    def get_armed_cue_by_id(self, cue_id: str) -> Cue | None:
        """Returns the armed cue with the given uuid string."""
        with self._lock:
            for cue in self._armed_cues:
                if cue.id == cue_id:
                    return cue
        return None


# ---------------------------
# Singleton
# ---------------------------

CUE_HANDLER = CueHandler()
