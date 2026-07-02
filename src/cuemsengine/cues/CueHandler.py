# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from __future__ import annotations

from threading import Event, Lock, Thread
from time import sleep

from cuemsutils.cues import ActionCue, CueList, DmxCue, VideoCue, AudioCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import logged, Logger
from cuemsutils.tools.CTimecode import CTimecode

from ..comms.NodeCommunications import NodeCommunications
from .run_cue import run_cue, reveal_cue
from .arm_cue import arm_cue
from .loop_cue import loop_cue
from ..players import VideoPlayer
from ..players.PlayerHandler import PLAYER_HANDLER
from ..tools import MtcListener
from .arm_cue import arm_cue
from .loop_cue import loop_cue
from .run_cue import run_cue, reveal_cue


class CueHandler:
    """
    Singleton class responsible for handling Cue objects.

    Holds a list of armed cues and manages video players.
    Thread-safe: internal state mutations are guarded by a Lock.
    """

    _instance: "CueHandler | None" = None

    # Instance attributes (declared for IDE/type checker support)
    _armed_cues: list[Cue]
    _armed_cues_set: set[str]
    _video_players: dict
    _front_video_player: VideoPlayer | None
    _lock: Lock
    communications_thread: NodeCommunications

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize instance attributes
            cls._instance._armed_cues = []
            cls._instance._armed_cues_set = set()
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
            self._armed_cues_set.clear()


    # ---------------------------
    # Cue Management
    # ---------------------------

    # Minimum effective duration (ms) for a cue to "count" as providing
    # enough time to arm subsequent cues during its playback.
    # Configurable per deployment. Default 1000ms covers 4K video decode.
    _ARM_WINDOW_THRESHOLD_MS = 1000

    # Maximum cues to walk ahead. Prevents runaway on pathological chains.
    _MAX_LOOKAHEAD_DEPTH = 15

    @staticmethod
    def _effective_duration_ms(cue: Cue) -> float:
        """Effective time a cue occupies: prewait + body + postwait.

        prewait/postwait are always CTimecode (format_timecode returns
        CTimecode() for None/empty). CTimecode(0) is truthy but
        .milliseconds_exact returns 0.0.
        """
        pre = cue.prewait.milliseconds_exact
        post = cue.postwait.milliseconds_exact

        if isinstance(cue, CueList):
            # container — body is intentionally 0 for chain-anchoring Σ math.
            # A CueList mid-chain therefore contributes only its own pre+post;
            # its children's duration does not push following cues' anchors.
            # (CueLists rarely appear as post_go='go' targets; revisit if that
            # changes — compute body from children then.)
            body = 0
        elif isinstance(cue, (AudioCue, VideoCue)):
            try:
                body = CTimecode(cue.media.duration).milliseconds_exact if cue.media else 0
            except Exception:
                body = 0
            if (body == 0 and getattr(cue, 'enabled', True)
                    and not getattr(cue, '_body0_logged', False)):
                # An enabled A/V cue with zero body feeds a zero-length slot into
                # the chain anchors — every following cue shifts earlier on THIS
                # node only (media missing/unreadable here but present elsewhere)
                # → silent cross-node desync. Surface it loudly (Fable 3.5).
                # Log ONCE per cue: this runs per arm pass / GO walk / chain hop,
                # so an unguarded log would flood the journal for one broken cue.
                Logger.error(
                    f'{type(cue).__name__} {cue.id} enabled but body==0 '
                    f'(media missing/unreadable?); chain anchor timing will be '
                    f'wrong on this node.')
                try:
                    cue._body0_logged = True
                except Exception:
                    pass
        elif isinstance(cue, DmxCue):
            # fadein_time/fadeout_time stored in MILLISECONDS (authoritative:
            # run_dmxCue in run_cue.py reads fadein_ms then fade_time = fadein_ms/1000).
            # fadeout_time exists in model but not yet implemented (always 0.0).
            fadein = getattr(cue, 'fadein_time', 0) or 0
            fadeout = getattr(cue, 'fadeout_time', 0) or 0
            body = fadein + fadeout  # already ms
        elif isinstance(cue, ActionCue):
            # play/stop/enable/disable/go_to = instant
            # TODO: use fade duration once fade_in/fade_out implemented
            body = 0
        else:
            body = 0

        return pre + body + post

    def _arm_ahead(self, start_cue: Cue) -> None:
        """Arm ahead in the target chain until 2 cues with meaningful
        duration are armed. Short/zero-duration cues are armed but don't
        count. CueList targets are skipped (handled by initial_cuelist_process).
        """
        target = getattr(start_cue, '_target_object', None)
        counted = 0
        walked = 0

        while (isinstance(target, Cue)
               and counted < 2
               and walked < self._MAX_LOOKAHEAD_DEPTH):
            if isinstance(target, CueList):
                # CueLists are containers — skip, don't count
                target = getattr(target, '_target_object', None)
                walked += 1
                continue
            if not target.enabled:
                target = getattr(target, '_target_object', None)
                walked += 1
                continue
            if not getattr(target, 'loaded', False):
                self.arm(target, init=True)
            if self._effective_duration_ms(target) >= self._ARM_WINDOW_THRESHOLD_MS:
                counted += 1
            target = getattr(target, '_target_object', None)
            walked += 1

        if walked >= self._MAX_LOOKAHEAD_DEPTH and counted < 2:
            Logger.warning(
                f'_arm_ahead hit depth limit ({self._MAX_LOOKAHEAD_DEPTH}) '
                f'from cue {start_cue.id} with only {counted}/2 real-duration '
                f'cues found. Remaining cues will rely on safety-net re-arm.')

    def arm(self, cue: Cue, init=False) -> bool:
        """Arms a cue by appending it to the armed_cues list."""
        if cue is None:
            return False

        needs_disarm = False
        do_arm = False
        pending_event = None

        with self._lock:
            found = cue.id in self._armed_cues_set  # O(1) set lookup
            if hasattr(cue, 'loaded') and cue.loaded:
                if not cue.enabled:
                    needs_disarm = True
            elif isinstance(getattr(cue, '_loading', None), Event):
                if init:
                    # Another thread is arming — wait for it outside the lock
                    pending_event = cue._loading
                else:
                    # Non-init callers just register; no need to wait
                    return False
            elif not init:
                if not found:
                    self._armed_cues.append(cue)
                    self._armed_cues_set.add(cue.id)
            elif cue._local and cue.enabled:
                # Mark as loading inside the lock to block concurrent arm
                # attempts. Cleared in finally below (outside lock —
                # intentional: avoids holding lock during arm_cue(). The
                # Event is set atomically here, so no other thread can
                # enter this branch for the same cue until _loading is
                # cleared. Waiting threads block on the Event.)
                cue._loading = Event()
                do_arm = True

        # Another thread is arming this cue — wait for it to finish
        if pending_event is not None:
            Logger.debug(f'Waiting for in-progress arm of {type(cue).__name__} {cue.id}')
            armed = pending_event.wait(timeout=5.0)
            if not armed:
                Logger.warning(f'Timed out waiting for arm of {cue.id}')
            return getattr(cue, 'loaded', False)

        # Disarm disabled-but-loaded cues outside lock (disarm acquires lock)
        if needs_disarm:
            self.disarm(cue)
            return False

        if not do_arm:
            return not needs_disarm

        try:
            Logger.info(f"Arming {type(cue).__name__} {cue.id}")
            arm_cue(cue)
            with self._lock:
                cue.loaded = True
                if not found:
                    self._armed_cues.append(cue)
                    self._armed_cues_set.add(cue.id)
            if isinstance(cue, AudioCue):
                try:
                    self.communications_thread.add_player(
                        f'audioplayer_{cue.id}', None, timeout=0.1)
                except Exception:
                    pass
        finally:
            loading_event = cue._loading
            cue._loading = None
            if isinstance(loading_event, Event):
                loading_event.set()

        # Recursive arms — only reached if cue was actually armed.
        # _loading sentinel prevents cycles; loaded guard prevents re-arm.
        if cue.post_go == 'go' and cue._target_object:
            if cue._target_object.enabled:
                self.arm(cue._target_object, init)

        # ActionCue(play) and FadeCue(fade_action) + target = 1 unit. Arm target
        # so it's ready when the action fires (ActionCue has zero duration; FadeCue
        # expects target_cue already armed before reading its OSC cache).
        if isinstance(cue, ActionCue) and cue._action_target_object:
            if cue.action_type in ('play', 'fade_action'):
                self.arm(cue._action_target_object, init)

        return True

    def disarm(self, cue: Cue) -> bool:
        """Disarms a cue by removing it from the armed_cues list."""
        if hasattr(cue, 'loaded') and cue.loaded:
            self.remove_armed_cue(cue)
            cue.loaded = False
            try:
                if isinstance(cue, AudioCue):
                    self.communications_thread.remove_player(f'audioplayer_{cue.id}', timeout=0.1)
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass

            if isinstance(cue, VideoCue):
                layer_ids = getattr(cue, '_layer_ids', [])
                client = getattr(cue, '_osc', None)
                if client and layer_ids:
                    for layer_id in layer_ids:
                        try:
                            client.set_value(f'/videocomposer/layer/{layer_id}/visible', 0)
                            client.set_value('/videocomposer/layer/unload', layer_id)
                            client.remove_layer_endpoints(layer_id)
                            PLAYER_HANDLER.deregister_layer(layer_id)
                        except Exception as e:
                            Logger.debug(f'Error disarming video layer {layer_id}: {e}')
                cue._layer_ids = []

            PLAYER_HANDLER.remove_cue_player(cue)
            return True

        return False

    def stop_all_cues(self) -> None:
        """Signal all armed cues to stop their playback loops.
        
        Also bumps each cue's generation counter so that any still-running
        go_threaded threads will see a mismatch and skip post-loop cleanup
        (disarm), which would otherwise undo the re-arm that follows.
        """
        with self._lock:
            for cue in self._armed_cues:
                cue._stop_requested = True
                cue._go_generation = getattr(cue, '_go_generation', 0) + 1

    def disarm_all(self) -> None:
        """Disarms all cues."""
        self.stop_all_cues()
        with self._lock:
            cues_snapshot = list(self._armed_cues)
        for cue in cues_snapshot:
            self.disarm(cue)
        self.reset_armed_cues()

    def get_next_cue(self, cue: Cue) -> Cue | None:
        """Returns the next cue to be played."""
        return cue._target_object if cue._target_object else None

    # ---------------------------
    # Cue Execution
    # ---------------------------

    @logged
    def go(self, cue: Cue, mtc: MtcListener, frozen_mtc_ms: float = None) -> Thread | None:
        """Starts a cue in a thread.

        Args:
            cue: The cue to start
            mtc: The MTC listener
            frozen_mtc_ms: Optional frozen MTC timestamp for sync with chained cues

        Returns:
            Thread running the cue, or None if the cue is disabled or not
            local to this node (the node owning the target will run it via
            its own GO/post_go dispatch).
        """
        if not cue.enabled:
            Logger.info(f'Cue {cue.id} is disabled, skipping execution')
            return None
        if not getattr(cue, '_local', True):
            # Non-local target: handled by the node where it IS local via that
            # node's own go_threaded → post_go chain. Trying to arm/run it
            # locally would fail at re-arm (no local player), raise inside the
            # caller's thread, and kill chained playback (master videocomposer
            # froze after loop 1 when post_go='go' targeted an audio cue local
            # to slave only).
            Logger.info(f'Cue {cue.id} is not local to this node, skipping execution')
            return None
        Logger.info(f'GO command received. Starting cue {cue.id}')
        if not hasattr(cue, 'loaded') or not cue.loaded:
            Logger.warning(f'Cue {cue.id} not loaded at go() time — this should not happen, '
                           f'pre-arm may have failed. Re-arming as fallback.')
            self.arm(cue, init=True)
            if not hasattr(cue, 'loaded') or not cue.loaded:
                raise Exception(f'{cue.__class__.__name__} {cue.id} not loaded to go (re-arm failed)')

        cue._stop_requested = False
        go_gen = getattr(cue, '_go_generation', 0) + 1
        cue._go_generation = go_gen

        thread = Thread(
            name=f'GO:{cue.__class__.__name__}:{cue.id}',
            target=self.go_threaded,
            args=[cue, mtc, frozen_mtc_ms, go_gen],
            daemon=True
        )
        thread.start()

        # Duration-aware lookahead: arm ahead until 2 cues with
        # meaningful playback duration are ready.
        self._arm_ahead(cue)
        return thread

    def _reveal_wait(self, cue: Cue, mtc: MtcListener, go_gen: int = 0) -> str:
        """Block until live MTC reaches cue._start_mtc; return 'reached' or 'stopped'.

        run_cue() sets a cue up HELD (video invisible / audio not-following /
        action not-yet-run). This gates the reveal on MTC so prewait/postwait
        offsets become real timeline gaps. Cues with no _start_mtc (ActionCue, or
        a CueList used as a target) reveal immediately. DmxCue DOES set _start_mtc
        but self-schedules (its reveal is a no-op), so it merely exits this wait
        once MTC passes start.

        Deliberately does NOT bail on an MTC stall: a recoverable stall
        self-recovers (reveal fires late when timecode resumes); bailing would
        leave the cue permanently held and frees nothing (loop_cue would hang on
        the same stall). STOP always exits via _stop_requested; a newer GO/reload
        exits via _go_generation.
        """
        start = getattr(cue, '_start_mtc', None)
        if start is None:
            return 'reached'
        # milliseconds_exact is wrap-accumulated by MtcListener → 24h-safe on
        # long shows (Fable 4.4); rounded would false-trip near a frame boundary.
        target = start.milliseconds_exact
        while mtc.main_tc.milliseconds_exact < target:
            if getattr(cue, '_stop_requested', False) or getattr(cue, '_go_generation', 0) != go_gen:
                return 'stopped'
            sleep(0.02)
        return 'reached'

    def _next_local_fire(self, cue: Cue, arrival_ms: float) -> tuple['Cue | None', float]:
        """From a just-played cue, walk its post_go='go' chain to THIS node's
        next local+enabled cue and return (that_cue_or_None, its_arrival_ms).

        The arrival of the immediate target is arrival_ms + eff(cue). Cues we
        skip along the way advance the accumulator: non-local ENABLED cues add
        their effective duration (so the found cue lands at its true slot — the
        A-B-A case, §3c Option 1); disabled cues add nothing (transparent). The
        walk stops at a chain break (post_go != 'go') — an explicit hand-off
        point — and is bounded against all-disabled/all-remote cycles.
        """
        acc = arrival_ms + self._effective_duration_ms(cue)
        node = getattr(cue, '_target_object', None)
        walked = 0
        while node is not None:
            if getattr(node, '_local', False) and getattr(node, 'enabled', False):
                return node, acc
            if getattr(node, 'post_go', None) != 'go':
                return None, acc
            if getattr(node, 'enabled', False):
                acc += self._effective_duration_ms(node)
            node = getattr(node, '_target_object', None)
            walked += 1
            if walked > 1024:
                Logger.error('post_go fire-walk hit safety limit; aborting')
                return None, acc
        return None, acc

    def go_threaded(self, cue: Cue, mtc: MtcListener, frozen_mtc_ms: float = None, go_gen: int = 0):
        """Runs a cue based on its properties.
        
        Args:
            cue: The cue to run
            mtc: The MTC listener (for live MTC)
            frozen_mtc_ms: Optional frozen MTC timestamp in milliseconds.
            go_gen: Generation counter captured at go() time. If the cue's
                    generation has changed by the time the loop ends, another
                    go/stop cycle occurred and this thread must not touch the cue.
        """
        # frozen_mtc_ms is this cue's ARRIVAL on the MTC timeline:
        # GO_mtc + Σ(effective durations of preceding cues in the chain).
        # None → manual GO / go_at_end: arrival = live MTC now (so those paths
        # keep their prewait — Fable 1.4).
        if frozen_mtc_ms is None:
            # Used by BaseEngine.timecode = mtc - go_offset for drift; _exact
            # preserves sub-ms precision at NTSC framerates.
            frozen_mtc_ms = mtc.main_tc.milliseconds_exact
            Logger.debug(f'Captured MTC snapshot for cue {cue.id}: {frozen_mtc_ms}ms')

        arrival_ms = frozen_mtc_ms
        # Single prewait application point (Fable 1.2): the cue's media and reveal
        # are anchored at start = arrival + prewait. prewait is NO LONGER a
        # wall-clock sleep — _reveal_wait turns it into a real MTC-timeline gap.
        start_ms = arrival_ms + cue.prewait.milliseconds_exact

        if cue._local:
            try:
                self.communications_thread.add_cue(cue.id, str(start_ms), timeout=0.1)
            except Exception:
                pass

            # Set up HELD at start_ms (video invisible / audio not-following /
            # action not-yet-run / dmx self-scheduled from absolute mtc_time).
            run_cue(cue, mtc, start_ms)

            # MTC-gated reveal: wait until live MTC reaches start_ms, then reveal
            # (video /visible; audio /mtcfollow; action EXECUTE; dmx no-op). This
            # is what makes prewait/body/postwait real timeline gaps, honored
            # identically on every node.
            if self._reveal_wait(cue, mtc, go_gen) != 'stopped':
                reveal_cue(cue, mtc, start_ms)

        # A superseding GO/reload (new _go_generation, without _stop_requested)
        # can arrive during the now-MTC-gated reveal wait — that fresh thread
        # owns the chain. This stale thread must NOT pace postwait or fire the
        # next cue, or the next cue would be go()'d twice (once here with a stale
        # arrival, once by the fresh thread). Cleanup below is already gated by
        # the generation check, so we only guard the outward actions here.
        superseded = getattr(cue, '_go_generation', 0) != go_gen

        # Postwait: DISPATCH pacing only — paces the fire of the next cue so we
        # don't arm the whole chain at once. The next cue's timeline slot is set
        # by the arrival math below, not by this sleep.
        if cue.postwait > 0 and not cue._stop_requested and not superseded:
            sleep(cue.postwait.milliseconds_rounded / 1000)

        post_go_thread = None
        if cue.post_go == 'go' and not cue._stop_requested and not superseded:
            # Walk the chain to THIS node's next local+enabled cue, accumulating
            # the timeline offset for the cues we skip (non-local: +eff so the
            # slot is right; disabled: +0). Every node walks the full chain and
            # fires its own local segments at their correct slots (§3c Opt 1).
            next_cue, next_arrival = self._next_local_fire(cue, arrival_ms)
            if next_cue is not None:
                Logger.info(f'Running post go for next local cue: {next_cue.id}')
                post_go_thread = self.go(next_cue, mtc, next_arrival)

        # Pre-arm go_at_end targets during playback. Runs after
        # run_cue() so current cue is already playing. The arm happens
        # in parallel with the media. go() also calls _arm_ahead but
        # that fires before run_cue — this call catches cues that were
        # disarmed between go() and here (loop passes).
        if cue.post_go == 'go_at_end':
            self._arm_ahead(cue)

        Logger.info(f'Going to loop for {cue.__class__.__name__}:{cue.id}')
        loop_cue(cue, mtc)

        if getattr(cue, '_go_generation', 0) != go_gen:
            Logger.info(f'Cue {cue.id} generation changed ({go_gen} → {cue._go_generation}), skipping cleanup')
            return

        # Notify the controller that the cue finished playing (status → 100).
        # Done here (after loop_cue) so the status only changes to 100 when the
        # cue has actually completed its full duration, not just when playback started.
        # Skipped if the cue was stopped (controller's stop_script already resets to 0).
        if cue._local and not getattr(cue, '_stop_requested', False):
            try:
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass

        go_at_end_thread = None
        if cue.post_go == 'go_at_end' and cue._target_object and not cue._stop_requested:
            Logger.info(f'Running go at end for {cue.__class__.__name__}:{cue.id}')
            go_at_end_thread = self.go(cue._target_object, mtc)

        self.disarm(cue)

        if cue.post_go == 'go_at_end' and go_at_end_thread:
            self.wait_for_cue(go_at_end_thread)

        if cue.post_go == 'go' and cue._target_object and not cue._stop_requested:
            if post_go_thread:
                self.wait_for_cue(post_go_thread)

    def wait_for_cue(self, thread: Thread) -> None:
        """Waits for a cue to finish."""
        Logger.info(f'Waiting for {thread.name} to finish')
        while thread.is_alive():
            sleep(1)
        thread.join()
        Logger.info(f"{thread.name} finished")

    # ---------------------------
    # ---------------------------
    # Action Cue Execution (delegates to ActionHandler)
    # ---------------------------

    def execute_action(
        self,
        cue: ActionCue,
        mtc: MtcListener,
        frozen_mtc_ms: float | None = None,
    ) -> dict:
        """Execute an ActionCue against the running show (see ActionHandler)."""
        from .ActionHandler import ACTION_HANDLER

        return ACTION_HANDLER.execute_action(cue, mtc, frozen_mtc_ms)

    def register_action_hook(
        self,
        phase: str,
        fn,
        *,
        action_types: frozenset | None = None,
    ) -> None:
        """Register a cue-layer extension hook; forwards to ``ACTION_HANDLER``."""
        from .ActionHandler import ACTION_HANDLER

        ACTION_HANDLER.register_action_hook(
            phase, fn, source="cue_layer", action_types=action_types
        )

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
                    # UI already sends 0.0-1.0 via sliderToFloat(); just clamp
                    vol_value = max(0.0, min(1.0, float(value)))
                    Logger.debug(f"Routing audio cue {cue_uuid}: {audio_cmd} = {vol_value}")
                    cue._osc.set_value(audio_cmd, vol_value)
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

from .ActionHandler import ACTION_HANDLER as _ACTION_HANDLER_SINGLETON

_ACTION_HANDLER_SINGLETON.bind_cue_handler(CUE_HANDLER)
