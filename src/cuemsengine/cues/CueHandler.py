# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import sleep
from typing import Callable

from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger, logged

from ..comms.NodeCommunications import NodeCommunications
from ..players import VideoPlayer
from ..players.PlayerHandler import PLAYER_HANDLER
from ..tools import MtcListener
from .ActionHandler import ACTION_HANDLER as _ACTION_HANDLER_SINGLETON
from .arm_cue import arm_cue
from .helpers import media_duration
from .loop_cue import loop_cue
from .run_cue import blank_cue, reveal_cue, run_cue


@dataclass
class _ArmWalk:
    """State one background arm-ahead walk carries into arm()'s own
    post_go / ActionCue-target recursion (869f79ecc).

    Without it the recursion armed cues the walk excluded (audio), ran past
    the walk's should_continue checkpoint (a reload landing mid-arm), and
    armed cues the walk could not report -- so its cleanup could not undo
    them (test2, 2026-09-25).
    """

    skip_types: tuple[type, ...] = ()
    should_continue: Callable[[], bool] | None = None
    armed: list = field(default_factory=list)


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
            hub_address=hub_address, node_id=node_id
        )
        self.communications_thread.start()

        # Wait for NNG thread to initialize (prevents race condition in
        # nni_random)
        max_wait = 5.0  # seconds
        wait_interval = 0.1
        waited = 0.0
        while waited < max_wait:
            if (
                self.communications_thread.is_alive()
                and self.communications_thread.event_loop is not None
            ):
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

    # Slack before a cue reached after its own anchor is reported as late.
    # One frame at 25 fps — below that it is dispatch jitter, not a mistimed
    # chain, and warning on it would flood the journal.
    _LATE_DISPATCH_TOLERANCE_MS = 40

    # How far ahead of its start a cue performs its HELD setup (run_cue).
    # Auto continue unrolls the whole chain from the trigger, so without this
    # every cue would run_cue at GO — for video that is N layers decoding
    # invisibly for the whole of their prewaits. Configurable per deployment;
    # 5s covers 4K decode-at-offset with room to spare.
    _RUN_AHEAD_MS = 5000

    # ---- chain epoch -----------------------------------------------------
    # Class-level DEFAULTS only: the first bump shadows them with an instance
    # attribute, so two handlers (the singleton and a test-built one) keep
    # independent counters, and a handler built via object.__new__ still reads
    # a sane value.
    #
    # _chain_epoch identifies one "pass" of a chain. It is bumped for every
    # fresh chain entry (manual GO, go_from re-entry, enable-rejoin) and
    # carried UNCHANGED through that pass's continuations, so a dispatch can
    # be told apart from a dispatch belonging to a newer pass. Per-cue
    # `_go_epoch` is the high-water mark of the newest pass that owns the cue.
    # Needed because dispatch now happens at chain entry: two cascades can
    # reach the same cue concurrently and `_go_generation` (last-writer-wins)
    # cannot order them.
    _chain_epoch = 0

    # The epoch a STOP claimed for itself. Every continuation of a pass that
    # started at or before it is refused — this is what makes a STOP landing
    # inside a cue's ~15s arm window stick (F4).
    _last_stop_chain_epoch = 0

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
                body = media_duration(cue).milliseconds_exact if cue.media else 0
            except Exception:
                body = 0
            if (
                body == 0
                and getattr(cue, "enabled", True)
                and not getattr(cue, "_body0_logged", False)
            ):
                # An enabled A/V cue with zero body feeds a zero-length slot into
                # the chain anchors — every following cue shifts earlier on THIS
                # node only (media missing/unreadable here but present elsewhere)
                # → silent cross-node desync. Surface it loudly (Fable 3.5).
                # Log ONCE per cue: this runs per arm pass / GO walk / chain hop,
                # so an unguarded log would flood the journal for one broken cue.
                Logger.error(
                    f"{type(cue).__name__} {cue.id} enabled but body==0 "
                    f"(media missing/unreadable?); chain anchor timing will be "
                    f"wrong on this node."
                )
                try:
                    cue._body0_logged = True
                except Exception:
                    pass
        elif isinstance(cue, DmxCue):
            # fadein_time/fadeout_time stored in MILLISECONDS (authoritative:
            # run_dmxCue in run_cue.py reads fadein_ms then fade_time = fadein_ms/1000).
            # fadeout_time exists in model but not yet implemented (always 0.0).
            fadein = getattr(cue, "fadein_time", 0) or 0
            fadeout = getattr(cue, "fadeout_time", 0) or 0
            body = fadein + fadeout  # already ms
        elif isinstance(cue, ActionCue):
            # play/stop/enable/disable/go_to = instant
            body = 0
        else:
            body = 0

        return pre + body + post

    @staticmethod
    def _chain_advance_ms(cue: Cue) -> float:
        """Timeline advance a cue contributes to a post_go='go' (Auto continue)
        chain: **zero**.

        Auto continue triggers the WHOLE chain at once. Every cue in it shares
        one arrival — the chain trigger — and the only thing that separates the
        cues is each cue's own prewait:

            arrival(k) = chain_trigger
            start(k)   = chain_trigger + prewait(k)

        So a cue's own waits must not push the cues after it. `prewait` is a
        per-cue offset from the common trigger, and `postwait` does not gate a
        chain whose pointer has already advanced — it stays meaningful for
        Auto follow / Auto pause (a real tail after the body) and for this
        cue's own illumination window, but it contributes nothing here.

        Previously this returned `prewait + postwait`, which made each cue's
        prewait cascade into every following cue: prewaits authored as absolute
        offsets from GO (5/35/65/95/380 s) played as 5/40/105/200/580.
        Castillo Medina del Campo, 2026-08-14 — ClickUp 869ej3cc8.

        ⚠ Returning anything non-zero here is NOT just an arithmetic change.
        The chain is now dispatched at its trigger and every cue parks on
        `arrival + prewait`, so a non-zero advance would push a cue's anchor
        past the moment its own thread already started waiting on — and it
        would put the arrival of a rejoining cue (Plans/
        prewait-dispatch-reorder-phase2.md §6) out of step with the pass that
        stamped it. Re-audit that design before changing this value.

        Auto follow (post_go='go_at_end') breaks the chain walk and fires its
        next cue from loop_cue *after* the body, so it never reaches this
        accumulator — its body wait is real, not anchored. See CLAUDE.md
        "Cue play modes & pre/post-wait semantics".
        """
        return 0.0

    def _wait_mtc(
        self, cue: Cue, mtc: MtcListener, target_ms: float, go_gen: int = 0
    ) -> str:
        """Block until live MTC reaches target_ms; return 'reached' or 'stopped'.

        Shared timeline gate used both to illuminate a cue at its arrival and to
        reveal it at its start. Exits early on STOP (`_stop_requested`) or a
        newer GO/reload (`_go_generation` changed). Deliberately does NOT bail on
        a recoverable MTC stall — it self-recovers (fires late when timecode
        resumes). milliseconds_exact is wrap-accumulated → 24h-safe.
        """
        while mtc.main_tc.milliseconds_exact < target_ms:
            if (
                getattr(cue, "_stop_requested", False)
                or getattr(cue, "_go_generation", 0) != go_gen
            ):
                return "stopped"
            sleep(0.02)
        # Final flag check AFTER the loop: a STOP landing in the last poll
        # interval (~20ms) would otherwise be reported as 'reached' and let the
        # caller proceed to reveal/fire right after the operator stopped.
        if (
            getattr(cue, "_stop_requested", False)
            or getattr(cue, "_go_generation", 0) != go_gen
        ):
            return "stopped"
        return "reached"

    def _arm_ahead(
        self,
        start_cue: Cue,
        should_continue: Callable[[], bool] | None = None,
        skip_arming_types: tuple[type, ...] = (),
    ) -> list[Cue]:
        """Arm ahead in the target chain until 2 cues with meaningful
        duration are armed. Short/zero-duration cues are armed but don't
        count. CueList targets are skipped (handled by
        initial_cuelist_process).

        Cues belonging to a DIFFERENT node (not `_local`) are also skipped,
        transparently — arm() is a no-op for them anyway, so counting them
        toward the budget (as this used to) starved THIS node's own segment
        of any lookahead at all on a mixed-node chain: node01/controller
        never pre-armed on Badajoz's actual chain shape, 2026-09-25,
        869f79ecc. Unlike the CueList/disabled skips, a non-local run does
        NOT consume `_MAX_LOOKAHEAD_DEPTH` — a whole other node's segment can
        be longer than that — so it is bounded instead by the same
        1024-step cycle guard `_next_local_fire` already uses against an
        all-remote chain.

        should_continue: an optional predicate, re-checked before each cue.
        Returning False stops the walk at that point without touching
        anything further. Used by the PreArm background thread
        (NodeEngine.set_next_cue) to abandon a stale selection or a
        reloaded project instead of racing the new state.

        skip_arming_types: cue types this call must not arm() or count —
        left armed for whichever single-threaded path reaches them later
        instead. Only AudioCue is ever passed here in production: two
        threads racing to arm the same slow audio cue is exactly the
        Badajoz-adjacent race this fix must not introduce (see
        NodeEngine.set_next_cue and AudioMixer.connect_player_to_outputs).
        Unlike the non-local skip above, this DOES consume the depth
        budget — it is still this node's own chain, just a type this call
        chooses not to arm.

        Returns the cues THIS call transitioned from unloaded to loaded —
        not merely already-armed ones, and not ones a concurrent call
        armed. The PreArm background thread uses this to undo exactly its
        own work if the project changes under it.
        """
        target = getattr(start_cue, "_target_object", None)
        counted = 0
        walked = 0
        total_steps = 0
        newly_armed: list[Cue] = []
        # Only a background walk (NodeEngine's PreArm) passes these; then its
        # rules reach arm()'s own recursion and newly_armed is the walk's
        # exact record. Every other caller keeps arm()'s original call shape.
        walk = (
            _ArmWalk(skip_arming_types, should_continue, newly_armed)
            if (should_continue is not None or skip_arming_types)
            else None
        )

        while (
            isinstance(target, Cue)
            and counted < 2
            and walked < self._MAX_LOOKAHEAD_DEPTH
        ):
            total_steps += 1
            if total_steps > 1024:
                Logger.error(
                    f"_arm_ahead from {start_cue.id} hit the cross-node "
                    "safety limit (1024 steps); aborting"
                )
                break
            if should_continue is not None and not should_continue():
                Logger.info(
                    f"_arm_ahead from {start_cue.id} stopped early — caller "
                    "asked to abort (stale selection or reloaded project)"
                )
                break
            if isinstance(target, CueList):
                # CueLists are containers — skip, don't count
                target = getattr(target, "_target_object", None)
                walked += 1
                continue
            if not target.enabled:
                target = getattr(target, "_target_object", None)
                walked += 1
                continue
            if not getattr(target, "_local", False):
                # Another node's cue — transparent, doesn't spend the depth
                # budget (see docstring).
                target = getattr(target, "_target_object", None)
                continue
            if isinstance(target, skip_arming_types):
                target = getattr(target, "_target_object", None)
                walked += 1
                continue
            already_loaded = getattr(target, "loaded", False)
            if not already_loaded:
                if walk is not None:
                    self.arm(target, init=True, walk=walk)
                else:
                    self.arm(target, init=True)
                    if getattr(target, "loaded", False):
                        newly_armed.append(target)
            if self._effective_duration_ms(target) >= self._ARM_WINDOW_THRESHOLD_MS:
                counted += 1
            target = getattr(target, "_target_object", None)
            walked += 1

        if walked >= self._MAX_LOOKAHEAD_DEPTH and counted < 2:
            Logger.warning(
                f"_arm_ahead hit depth limit ({self._MAX_LOOKAHEAD_DEPTH}) "
                f"from cue {start_cue.id} with only {counted}/2 real-duration "
                f"cues found. Remaining cues will rely on safety-net re-arm."
            )

        return newly_armed

    def arm(self, cue: Cue, init=False, walk: _ArmWalk | None = None) -> bool:
        """Arms a cue by appending it to the armed_cues list.

        walk: set only by a background _arm_ahead walk (NodeEngine's PreArm).
        Its excluded types and should_continue checkpoint also govern this
        call's own post_go / ActionCue-target recursion, and every cue this
        call chain actually arms is recorded in walk.armed (869f79ecc).
        """
        if cue is None:
            return False
        if walk is not None:
            if walk.skip_types and isinstance(cue, walk.skip_types):
                return False
            if walk.should_continue is not None and not walk.should_continue():
                return False

        needs_disarm = False
        do_arm = False
        pending_event = None

        with self._lock:
            found = cue.id in self._armed_cues_set  # O(1) set lookup
            if hasattr(cue, "loaded") and cue.loaded:
                if not cue.enabled:
                    needs_disarm = True
            elif isinstance(getattr(cue, "_loading", None), Event):
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
            Logger.debug(
                f"Waiting for in-progress arm of {type(cue).__name__} {cue.id}"
            )
            armed = pending_event.wait(timeout=5.0)
            if not armed:
                Logger.warning(f"Timed out waiting for arm of {cue.id}")
            return getattr(cue, "loaded", False)

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
            if walk is not None:
                walk.armed.append(cue)
            if isinstance(cue, AudioCue):
                try:
                    self.communications_thread.add_player(
                        f"audioplayer_{cue.id}", None, timeout=0.1
                    )
                except Exception:
                    pass
        except Exception as e:
            # Fail loud, fail local. _arm_ahead() runs on the GO daemon
            # thread, so letting this propagate would kill a *playing* cue's
            # thread before loop_cue() and skip its generation-tracked
            # cleanup — far worse than one broken cue. Leave the cue
            # unloaded and let go()'s fallback re-arm retry it; if that also
            # fails, go() raises where an operator can see it.
            Logger.error(f"Failed to arm {type(cue).__name__} {cue.id}: {e}")
            Logger.exception(e)
            cue.loaded = False
            return False
        finally:
            loading_event = cue._loading
            cue._loading = None
            if isinstance(loading_event, Event):
                loading_event.set()

        # Recursive arms — only reached if cue was actually armed.
        # _loading sentinel prevents cycles; loaded guard prevents re-arm.
        if cue.post_go == "go" and cue._target_object:
            if cue._target_object.enabled:
                if walk is not None:
                    self.arm(cue._target_object, init, walk=walk)
                else:
                    self.arm(cue._target_object, init)

        # ActionCue(play) and FadeCue(fade_action) + target = 1 unit. Arm
        # target
        # so it's ready when the action fires (ActionCue has zero duration;
        # FadeCue
        # expects target_cue already armed before reading its OSC cache).
        if isinstance(cue, ActionCue) and cue._action_target_object:
            if cue.action_type in ("play", "fade_action"):
                if walk is not None:
                    self.arm(cue._action_target_object, init, walk=walk)
                else:
                    self.arm(cue._action_target_object, init)

        return True

    def disarm(self, cue: Cue) -> bool:
        """Disarms a cue by removing it from the armed_cues list."""
        cue._playing = False
        if hasattr(cue, "loaded") and cue.loaded:
            self.remove_armed_cue(cue)
            cue.loaded = False
            try:
                if isinstance(cue, AudioCue):
                    self.communications_thread.remove_player(
                        f"audioplayer_{cue.id}", timeout=0.1
                    )
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass

            if isinstance(cue, VideoCue):
                layer_ids = getattr(cue, "_layer_ids", [])
                client = getattr(cue, "_osc", None)
                if client and layer_ids:
                    for layer_id in layer_ids:
                        try:
                            client.set_value(
                                f"/videocomposer/layer/{layer_id}/visible", 0
                            )
                            client.set_value("/videocomposer/layer/unload", layer_id)
                            client.remove_layer_endpoints(layer_id)
                            PLAYER_HANDLER.deregister_layer(layer_id)
                        except Exception as e:
                            Logger.debug(f"Error disarming video layer {layer_id}: {e}")
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
            # Claim an epoch for this STOP and record it: every continuation
            # of a pass that started at or before it is now refused, including
            # one currently blocked inside go()'s re-arm fallback whose cue is
            # not in _armed_cues yet (F4).
            self._chain_epoch = self._chain_epoch + 1
            self._last_stop_chain_epoch = self._chain_epoch
            for cue in self._armed_cues:
                cue._stop_requested = True
                cue._go_generation = getattr(cue, "_go_generation", 0) + 1
                cue._go_epoch = self._chain_epoch
                cue._playing = False

    def cancel_pending_descendants(self, cue: Cue) -> int:
        """Cancel the cues an Auto-continue chain dispatched behind `cue`.

        A chained cue only exists because its predecessor ran, so stopping a
        cue must stop everything scheduled behind it. Under Phase 2 the whole
        chain is dispatched at the trigger, so by now those cues are parked on
        their own anchors and nothing else would hold them back — the
        `_stop_requested` guard that used to sit in front of the dispatch has
        moved to chain entry.

        Never touches a cue that has already produced output (`_revealed`):
        that one is on stage and stays there. The walk continues PAST it,
        because the cues behind it still depend on the cue being stopped.
        Non-local cues are skipped too — the node that owns them runs this same
        walk on its own graph (ActionCues are local everywhere), so the union
        covers the cluster.

        Returns how many cues were cancelled.
        """
        cancelled = []
        with self._lock:
            # The pass this cue belongs to. Cues that a NEWER pass has since
            # claimed are not ours to cancel — a loop-back can already have
            # re-scheduled them against a fresh trigger.
            target_epoch = getattr(cue, "_go_epoch", 0)
            self._chain_epoch = self._chain_epoch + 1
            epoch = self._chain_epoch
            # Mark the target too: a dispatch of it currently blocked in its
            # own arm must not come back to life after this.
            cue._go_epoch = epoch

            node = (
                getattr(cue, "_target_object", None)
                if getattr(cue, "post_go", None) == "go"
                else None
            )
            # A circular project (A→B→C→A) would otherwise re-mark the same
            # cues on every revolution until the safety limit, reporting ~1024
            # cancellations and firing that many remove_cue sends.
            seen = set()
            while node is not None and id(node) not in seen:
                seen.add(id(node))
                is_local = getattr(node, "_local", False)
                owned = getattr(node, "_go_epoch", 0) <= target_epoch
                if is_local and owned and getattr(node, "enabled", False):
                    if not getattr(node, "_revealed", False):
                        node._stop_requested = True
                        node._go_generation = getattr(node, "_go_generation", 0) + 1
                        node._go_epoch = epoch
                        node._playing = False
                        cancelled.append(node)
                elif is_local and owned:
                    # Disabled: nothing to cancel, but claim it so enabling it
                    # later cannot rejoin a chain that was stopped.
                    node._go_epoch = epoch
                if getattr(node, "post_go", None) != "go":
                    # A chain break is a hand-off point, not a descendant.
                    break
                node = getattr(node, "_target_object", None)
                if len(seen) > 1024:
                    Logger.error(
                        "cancel_pending_descendants hit safety limit; aborting"
                    )
                    break

        # Outside the lock: a cancelled cue's thread leaves through the
        # generation guard, which sits upstream of the usual remove_cue, and
        # the whole chain has been lit since the trigger — so the highlight
        # has to be dropped here or the UI keeps showing dead cues as running.
        for node in cancelled:
            self._end_illumination(node)
        if cancelled:
            # str(): a cue's id is a Uuid, not a str, and join() would raise —
            # inside the one log line that tells an operator this happened.
            Logger.info(
                f"Stop of cue {cue.id} cancelled {len(cancelled)} scheduled "
                f"cue(s) behind it: {', '.join(str(n.id) for n in cancelled)}"
            )
        return len(cancelled)

    def cancel_parked(self, cue: Cue) -> bool:
        """Cancel a cue that was dispatched but has not produced output yet.

        Used when a cue is DISABLED after its chain was dispatched. Without
        this the cue would still fire: the whole chain leaves at the trigger
        and nothing downstream re-reads `enabled`. A cue that already
        revealed is left alone — disabling never cuts live playback.

        The cue keeps a stamp of the pass it was cancelled out of, so
        re-enabling it before its slot puts it back (rejoin_chain).
        """
        if getattr(cue, "_revealed", False) or not getattr(cue, "_playing", False):
            return False
        with self._lock:
            self._chain_epoch = self._chain_epoch + 1
            epoch = self._chain_epoch
            cue._stop_requested = True
            cue._go_generation = getattr(cue, "_go_generation", 0) + 1
            cue._go_epoch = epoch
            cue._playing = False
            # Remember where it would have played, so a re-enable can put it
            # back at the same anchor instead of losing the slot.
            arrival = getattr(cue, "_dispatch_arrival_ms", None)
            if arrival is not None:
                cue._chain_pass = (epoch, arrival)
        self._end_illumination(cue)
        Logger.info(f"Cue {cue.id} disabled before its slot — cancelled")
        return True

    def rejoin_chain(self, cue: Cue, mtc: MtcListener) -> bool:
        """Put a cue enabled mid-pass back into its running chain.

        The chain walk stamped this cue with the pass that would have
        dispatched it while it was disabled. If that pass is still alive and
        the cue's slot has not gone by, dispatch it at its original anchor so
        it plays exactly when it was always going to.

        Dispatched with unroll=False: the rest of the chain is already
        running, and re-dispatching it would churn cues that are on stage.

        Returns True if the cue was put back.
        """
        if not getattr(cue, "enabled", False) or not getattr(cue, "_local", False):
            return False
        stamp = getattr(cue, "_chain_pass", None)
        if not stamp:
            return False
        epoch, arrival_ms = stamp
        if arrival_ms is None:
            return False

        with self._lock:
            barrier = self._last_stop_chain_epoch
            if epoch <= self._last_stop_chain_epoch:
                Logger.info(
                    f"Cue {cue.id} enabled, but the chain it belonged to was "
                    f"stopped — it will play on the next GO"
                )
                return False
            if getattr(cue, "_go_epoch", 0) > epoch:
                # A stop action (or a newer pass) claimed this cue after the
                # stamp: a stop takes its scheduled descendants with it, and
                # that outranks re-enabling one of them.
                Logger.info(
                    f"Cue {cue.id} enabled, but a stop already cancelled this "
                    f"part of the chain — it will play on the next GO"
                )
                return False

        start_ms = arrival_ms + cue.prewait.milliseconds_exact
        now_ms = mtc.main_tc.milliseconds_exact
        if start_ms < now_ms - self._LATE_DISPATCH_TOLERANCE_MS:
            # Firing it now would put it on stage at the wrong moment, which
            # mid-show is worse than not playing it at all.
            Logger.warning(
                f"Cue {cue.id} enabled after its slot (start={start_ms:.0f}ms, "
                f"mtc={now_ms:.0f}ms) — NOT firing it late; it will play on "
                f"the next GO"
            )
            return False

        Logger.info(
            f"Cue {cue.id} enabled before its slot — rejoining the running "
            f"chain at {start_ms:.0f}ms"
        )
        # require_stop_epoch closes the window between the check above and the
        # dispatch: the lock is dropped in between, and a STOP landing there
        # must not be overridden by the fresh epoch this go() mints.
        return (
            self.go(cue, mtc, arrival_ms, unroll=False, require_stop_epoch=barrier)
            is not None
        )

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

    def _warn_if_late(self, cue: Cue, mtc: MtcListener, start_ms: float) -> None:
        """Say it out loud when a cue is reached after its own anchor.

        Firing late is recoverable; firing late silently mistimes a show and
        nobody knows why. Tolerance is one frame — below that it is jitter.
        """
        now_ms = mtc.main_tc.milliseconds_exact
        if start_ms < now_ms - self._LATE_DISPATCH_TOLERANCE_MS:
            Logger.warning(
                f"Cue {cue.id} reached after its anchor — firing LATE by "
                f"{now_ms - start_ms:.0f}ms (start={start_ms:.0f}ms, "
                f"mtc={now_ms:.0f}ms). Its slot had already passed when the "
                f"cue got here (seed in the past, a re-arm that overran its "
                f"prewait, or an MTC jump)."
            )

    def _end_illumination(self, cue: Cue) -> None:
        """Drop the sequence-view highlight for a cue that will not play.

        Under Auto continue a cue is lit from the trigger, so any path that
        abandons it before its normal end must clear the highlight or the UI
        shows a dead cue as running.
        """
        try:
            self.communications_thread.remove_cue(cue.id, timeout=0.1)
        except Exception:
            pass

    def stamp_pass(self, skipped: list, arrival_ms: float) -> int:
        """Mint a chain epoch and stamp `skipped` with it, dispatching nothing.

        For the case where a chain walk finds NO local+enabled cue on this
        node (every local cue in the chain is currently disabled): go() is
        never called, so nothing would mint an epoch, and enabling one of
        those cues later could not rejoin the pass. Returns the epoch.
        """
        with self._lock:
            self._chain_epoch = self._chain_epoch + 1
            epoch = self._chain_epoch
            self._stamp_skipped_locked(skipped, epoch, arrival_ms)
        return epoch

    def _stamp_skipped_locked(
        self, skipped: list | None, epoch: int, arrival_ms: float
    ) -> None:
        """Record the pass that would have dispatched each skipped-disabled
        cue, so enabling it later can rejoin at its own slot.

        Caller must hold self._lock. A None arrival is not an anchor a rejoin
        could be pinned to (the thread derives its own from live MTC), so it is
        not stamped at all rather than stamped with something unusable.
        """
        if arrival_ms is None:
            return
        for cue in skipped or ():
            try:
                cue._chain_pass = (epoch, arrival_ms)
            except Exception:
                pass

    @logged
    def go(
        self,
        cue: Cue,
        mtc: MtcListener,
        frozen_mtc_ms: float = None,
        chain_epoch: int = None,
        unroll: bool = True,
        stamp_skipped: list = None,
        require_stop_epoch: int = None,
    ) -> Thread | None:
        """Starts a cue in a thread.

        Args:
            cue: The cue to start
            mtc: The MTC listener
            frozen_mtc_ms: Optional frozen MTC timestamp for sync with chained
            cues
            chain_epoch: None for a FRESH chain entry (manual GO, go_from
            re-entry, enable-rejoin) — mints a new epoch. Otherwise the epoch
            of the pass this dispatch belongs to, which is validated against
            the cue's own high-water mark and the STOP barrier.
            unroll: False stops go_threaded from dispatching the rest of the
            chain — used by the enable-rejoin, where the chain is already
            unrolled and re-dispatching it would churn live cues.
            stamp_skipped: cues the caller's chain walk skipped because they
            are disabled; stamped with this pass so a later enable can rejoin.

        Returns:
            Thread running the cue, or None if the cue is disabled, not local
            to this node (the node owning the target will run it via its own
            GO/post_go dispatch), or the dispatch was refused as stale/after a
            STOP.
        """
        if not cue.enabled:
            Logger.info(f"Cue {cue.id} is disabled, skipping execution")
            return None
        if not getattr(cue, "_local", True):
            # Non-local target: handled by the node where it IS local via that
            # node's own go_threaded → post_go chain. Trying to arm/run it
            # locally would fail at re-arm (no local player), raise inside the
            # caller's thread, and kill chained playback (master videocomposer
            # froze after loop 1 when post_go='go' targeted an audio cue local
            # to slave only).
            Logger.info(f"Cue {cue.id} is not local to this node, skipping execution")
            return None
        Logger.info(f"GO command received. Starting cue {cue.id}")

        is_continuation = chain_epoch is not None
        if not is_continuation:
            # Fresh entry: claim the next epoch. It is greater than every
            # recorded stop and every cue mark at this instant, so the checks
            # below can only refuse it if a STOP arrives LATER — while this
            # call is blocked in the re-arm fallback. That is the right
            # outcome: the operator's STOP came after their GO.
            with self._lock:
                self._chain_epoch = self._chain_epoch + 1
                chain_epoch = self._chain_epoch

        if not hasattr(cue, "loaded") or not cue.loaded:
            Logger.warning(
                f"Cue {cue.id} not loaded at go() time — this should not"
                f"happen, "
                f"pre-arm may have failed. Re-arming as fallback."
            )
            # A continuation does NOT arm here: dispatch now happens at chain
            # entry, so this call runs on the PREVIOUS cue's thread, and an
            # audio arm can block ~15s on its JACK ports — delaying or killing
            # that cue's own reveal. go_threaded arms the cue on its own
            # thread instead, overlapping its own prewait.
            if not is_continuation:
                self.arm(cue, init=True)
                if not hasattr(cue, "loaded") or not cue.loaded:
                    raise Exception(
                        f"{cue.__class__.__name__} {cue.id} not loaded to go"
                        f"(re-arm failed)"
                    )

        with self._lock:
            # Validate + commit atomically. Both checks are deliberately made
            # AFTER any arm above: that is what lets a STOP which landed
            # during a long arm window survive instead of being wiped by the
            # _stop_requested reset below (F4).
            if (
                require_stop_epoch is not None
                and self._last_stop_chain_epoch != require_stop_epoch
            ):
                # The caller validated something against the STOP barrier and
                # then had to drop the lock (the enable-rejoin does). A STOP
                # landing in that window must win — otherwise the cue plays
                # after the operator stopped the show.
                Logger.warning(
                    f"Refusing dispatch of cue {cue.id}: a STOP arrived while "
                    f"it was being put back into its chain"
                )
                return None
            if chain_epoch <= self._last_stop_chain_epoch:
                # For a continuation: the chain was stopped. For a fresh
                # entry: a STOP landed while we were arming — it is newer than
                # this GO, so it wins (the caller must tolerate None).
                Logger.warning(
                    f"Refusing dispatch of cue {cue.id}: a STOP ended this "
                    f"chain (pass {chain_epoch} <= stop "
                    f"{self._last_stop_chain_epoch})"
                )
                return None
            if is_continuation:
                if getattr(cue, "_go_epoch", 0) >= chain_epoch:
                    # Either a newer pass already owns the cue (loop-back
                    # racing the original unroll), or this same pass already
                    # dispatched it — a post_go='go' cycle, which entry-time
                    # dispatch would otherwise spin at thread-spawn rate.
                    Logger.warning(
                        f"Refusing stale/duplicate chain dispatch of cue "
                        f"{cue.id} (cue pass {getattr(cue, '_go_epoch', 0)} >= "
                        f"dispatch pass {chain_epoch})"
                    )
                    return None

            cue._go_epoch = chain_epoch
            # Recorded here, not in the spawned thread: a disable arriving in
            # between has to find this cue's anchor to stamp a rejoin with, and
            # in a loop project it would otherwise read the PREVIOUS cycle's.
            # None (manual GO / go_at_end) means "derived from live MTC by the
            # thread", which is not an anchor a rejoin can be pinned to.
            cue._dispatch_arrival_ms = frozen_mtc_ms
            cue._stop_requested = False
            go_gen = getattr(cue, "_go_generation", 0) + 1
            cue._go_generation = go_gen
            # Output-commit flag: True once this cue has produced output
            # (reveal, or the DMX scene send). The stop walk cancels only
            # cues that have NOT committed — a playing cue is never cut.
            cue._revealed = False
            # Lifecycle flag: True while a GO owns this cue; cleared by
            # disarm() and stop_all_cues(). Unlike _go_generation
            # (increment-only), this is a sound "currently playing" signal —
            # the disable-action path uses it to decide whether disarming
            # would cut live playback.
            cue._playing = True
            # Stamped with the epoch minted in THIS lock section: reading it
            # back off the cue afterwards could capture a newer unrelated
            # dispatch's epoch and mis-anchor the rejoin.
            self._stamp_skipped_locked(stamp_skipped, chain_epoch, frozen_mtc_ms)

        thread = Thread(
            name=f"GO:{cue.__class__.__name__}:{cue.id}",
            target=self.go_threaded,
            args=[cue, mtc, frozen_mtc_ms, go_gen, chain_epoch, unroll],
            daemon=True,
        )
        thread.start()

        # Duration-aware lookahead: arm ahead until 2 cues with meaningful
        # playback duration are ready. SYNCHRONOUS on the caller's thread, and
        # arm() can block ~15s per audio cue — so it must not run where the
        # caller is something that cannot afford to wait:
        #   - a continuation's caller is the PREVIOUS cue's thread (dispatch
        #     happens at chain entry now), and blocking it would delay that
        #     cue's own reveal. Chain cues are armed by arm()'s recursion at
        #     load and, failing that, by their own thread in go_threaded.
        #   - a rejoin (unroll=False) is called from the command thread and
        #     the cue is already armed by definition.
        if not is_continuation and unroll:
            self._arm_ahead(cue)
        return thread

    def go_from(
        self, start_cue: Cue, mtc: MtcListener, seed_ms: float = None
    ) -> Thread | None:
        """Re-enter a post_go='go' chain from start_cue (inclusive), firing THIS
        node's first local+enabled cue at seed_ms + Σ(chain advance of the
        enabled cues skipped on the way). Returns the Thread, or None if no
        local+enabled cue is reachable before a chain break.

        Mirrors NodeEngine.go_script's cross-node walk, but for an IN-CHAIN
        re-entry — specifically an ActionCue 'play' that restarts a sequence
        (e.g. a circular project's loop-back). Plain go() bails on a non-local
        target (returns None), which drops every cue local to a DIFFERENT node
        than the play target: a loop-back 'play' aimed at node01's cue would
        never re-fire the controller's own cues. Walking here makes each engine
        re-enter its own local segment, exactly as it does on a GO.
        """
        if seed_ms is None:
            seed_ms = mtc.main_tc.milliseconds_exact
        cue = start_cue
        sigma_ms = 0.0
        walked = 0
        skipped_disabled = []
        while cue is not None and not (
            getattr(cue, "_local", False) and getattr(cue, "enabled", False)
        ):
            if not getattr(cue, "enabled", False):
                # Remember it: enabling it before its slot rejoins this pass.
                skipped_disabled.append(cue)
            if getattr(cue, "post_go", None) != "go":
                # chain break before any local cue — nothing for this node to do
                cue = None
                break
            if getattr(cue, "enabled", False):
                sigma_ms += self._chain_advance_ms(cue)
            cue = getattr(cue, "_target_object", None)
            walked += 1
            if walked > 1024:
                Logger.error("go_from walk hit safety limit; aborting")
                return None
        if cue is None:
            # No local cue to fire, but the disabled ones still get a pass to
            # rejoin, or enabling one mid-show would do nothing at all.
            if skipped_disabled:
                self.stamp_pass(skipped_disabled, seed_ms)
            return None
        if skipped_disabled:
            return self.go(cue, mtc, seed_ms + sigma_ms, stamp_skipped=skipped_disabled)
        return self.go(cue, mtc, seed_ms + sigma_ms)

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
        start = getattr(cue, "_start_mtc", None)
        if start is None:
            return "reached"
        # milliseconds_exact is wrap-accumulated by MtcListener → 24h-safe on
        # long shows (Fable 4.4); rounded would false-trip near a frame boundary.
        return self._wait_mtc(cue, mtc, start.milliseconds_exact, go_gen)

    def _next_local_fire(
        self, cue: Cue, arrival_ms: float, stamp_epoch: int = None
    ) -> tuple["Cue | None", float]:
        """From a just-played cue, walk its post_go='go' chain to THIS node's
        next local+enabled cue and return (that_cue_or_None, its_arrival_ms).

        Under Auto continue the chain advance is zero, so every cue in the
        chain arrives at the same trigger; the accumulator is kept because the
        helper is the one documented place expressing the rule. Cues we skip
        are transparent, and the walk stops at a chain break (post_go != 'go')
        — an explicit hand-off point — bounded against all-disabled/all-remote
        cycles.

        stamp_epoch: when given, disabled cues found on the way are stamped
        with the pass that would have dispatched them, so enabling one later
        can rejoin it at its own slot. Left None (the default) the walk touches
        nothing — callers that only ask "who is next" must stay side-effect
        free.
        """
        acc = arrival_ms + self._chain_advance_ms(cue)
        node = getattr(cue, "_target_object", None)
        walked = 0
        while node is not None:
            if getattr(node, "_local", False) and getattr(node, "enabled", False):
                return node, acc
            if stamp_epoch is not None and not getattr(node, "enabled", False):
                # Disabled: transparent to the timeline, but remember the pass
                # so a re-enable before its slot can still rejoin. Stamped here
                # too when the disabled cue is itself the chain break, which
                # the walk reaches but does not walk past. Guarded so that a
                # caller only asking "who is next" touches nothing at all —
                # including this handler's own attributes, since the walk is
                # also driven with a bare class or a stub as `self`.
                self._stamp_one(node, stamp_epoch, acc)
            if getattr(node, "post_go", None) != "go":
                return None, acc
            if getattr(node, "enabled", False):
                acc += self._chain_advance_ms(node)
            node = getattr(node, "_target_object", None)
            walked += 1
            if walked > 1024:
                Logger.error("post_go fire-walk hit safety limit; aborting")
                return None, acc
        return None, acc

    def _stamp_one(self, cue: Cue, epoch: int | None, arrival_ms: float) -> None:
        """Stamp a single skipped-disabled cue, if stamping was asked for.

        Gated on `epoch is not None` in full — including the lock — because the
        walk is also called with a bare class or a stub as `self`.
        """
        if epoch is None:
            return
        with self._lock:
            self._stamp_skipped_locked([cue], epoch, arrival_ms)

    def go_threaded(
        self,
        cue: Cue,
        mtc: MtcListener,
        frozen_mtc_ms: float = None,
        go_gen: int = 0,
        chain_epoch: int = 0,
        unroll: bool = True,
    ):
        """Runs a cue based on its properties.

        Args:
            cue: The cue to run
            mtc: The MTC listener (for live MTC)
            frozen_mtc_ms: Optional frozen MTC timestamp in milliseconds.
            go_gen: Generation counter captured at go() time. If the cue's
                    generation has changed by the time the loop ends, another
                    go/stop cycle occurred and this thread must not touch the
                    cue.
            chain_epoch: the pass this cue belongs to, carried unchanged into
                    the continuation dispatch so the whole chain shares it.
            unroll: False suppresses the continuation dispatch (enable-rejoin
                    of a chain that is already unrolled).
        """
        # frozen_mtc_ms is this cue's ARRIVAL on the MTC timeline:
        # GO_mtc + Σ(effective durations of preceding cues in the chain).
        # None → manual GO / go_at_end: arrival = live MTC now (so those paths
        # keep their prewait — Fable 1.4).
        if frozen_mtc_ms is None:
            # Used by BaseEngine.timecode = mtc - go_offset for drift; _exact
            # preserves sub-ms precision at NTSC framerates.
            frozen_mtc_ms = mtc.main_tc.milliseconds_exact
            Logger.debug(f"Captured MTC snapshot for cue {cue.id}: {frozen_mtc_ms}ms")

        arrival_ms = frozen_mtc_ms
        if getattr(cue, "_dispatch_arrival_ms", None) is None:
            # go() records this under its accept lock; only the manual-GO /
            # go_at_end paths (no seed) resolve their anchor here.
            cue._dispatch_arrival_ms = arrival_ms
        # Single prewait application point (Fable 1.2): the cue's media and reveal
        # are anchored at start = arrival + prewait. prewait is NO LONGER a
        # wall-clock sleep — _reveal_wait turns it into a real MTC-timeline gap.
        # Under Auto continue every cue in the chain shares `arrival` (the
        # trigger), so this is the ONLY term that separates them.
        start_ms = arrival_ms + cue.prewait.milliseconds_exact

        # Safety net. Auto continue dispatches the whole chain from the trigger
        # and every prewait is >= 0, so a chain cue cannot be reached after its
        # own anchor any more; what can still land here is a go_at_end/manual
        # seed already in the past, or an MTC jump. Silence would mistime a show
        # quietly. Plans/prewait-dispatch-reorder-phase2.md §4.
        self._warn_if_late(cue, mtc, start_ms)

        # Dispatch the rest of the chain NOW, at this cue's arrival — not after
        # its reveal and postwait. Auto continue triggers the whole chain at
        # once, so every cue must be free to park on its own anchor; dispatching
        # at start(k)+postwait(k) reached a cue with a smaller prewait than its
        # predecessor's after its anchor had already passed, and fired it late.
        # Every cue of the pass carries the same chain_epoch, so a stale cascade
        # (loop-back) and a cycle are both refused in go().
        post_go_thread = None
        if (
            unroll
            and cue.post_go == "go"
            and not cue._stop_requested
            and getattr(cue, "_go_generation", 0) == go_gen
        ):
            try:
                # Walk to THIS node's next local+enabled cue; cues we skip are
                # transparent (the advance is zero), and disabled ones are
                # stamped with this pass so enabling one later can rejoin it.
                next_cue, next_arrival = self._next_local_fire(
                    cue, arrival_ms, stamp_epoch=chain_epoch
                )
                if next_cue is not None:
                    Logger.info(
                        f"Unrolling post_go chain: dispatching {next_cue.id} "
                        f"at the trigger"
                    )
                    post_go_thread = self.go(
                        next_cue, mtc, next_arrival, chain_epoch=chain_epoch
                    )
            except Exception as e:
                # The chain is downstream work; losing it must not cost THIS
                # cue its own reveal.
                Logger.error(f"Chain dispatch from cue {cue.id} failed: {e}")

        if cue._local:
            # A continuation does not arm on the dispatching thread (that is the
            # PREVIOUS cue's thread — a ~15s audio arm there would delay or kill
            # its reveal). It arms here instead, on its own thread, overlapping
            # its own prewait.
            if not getattr(cue, "loaded", False):
                Logger.warning(
                    f"Cue {cue.id} not loaded at dispatch — arming on its own "
                    f"thread before its slot."
                )
                self.arm(cue, init=True)
                if not getattr(cue, "loaded", False):
                    # The rest of the chain went out at entry, so this failure
                    # costs this cue only.
                    Logger.error(
                        f"{cue.__class__.__name__} {cue.id} could not be armed; "
                        f"it will not play. The rest of the chain is unaffected."
                    )
                    return
                # The check above ran before the arm; an arm longer than this
                # cue's runway makes it late, and that must not be silent.
                self._warn_if_late(cue, mtc, start_ms)

            # Illuminate (sequence-view highlight) at the cue's ARRIVAL — the
            # start of its prewait — NOT at dispatch. Under Auto continue every
            # cue arrives at the trigger, so the whole chain lights together and
            # each cue stays lit for prewait + max(body, postwait).
            if self._wait_mtc(cue, mtc, arrival_ms, go_gen) != "stopped":
                try:
                    self.communications_thread.add_cue(
                        cue.id, str(start_ms), timeout=0.1
                    )
                except Exception:
                    pass

            # Park until the held setup is actually needed. Unrolling the chain
            # at the trigger would otherwise run every cue's run_cue at GO —
            # for video that is N layers decoding invisibly for the whole of
            # their prewaits. A start already inside the window returns at once.
            parked = self._wait_mtc(cue, mtc, start_ms - self._RUN_AHEAD_MS, go_gen)

            if parked != "stopped":
                # Set up HELD at start_ms (video invisible / audio not-following
                # / action not-yet-run / dmx self-scheduled from absolute
                # mtc_time), close enough to the slot that the frame is ready.
                try:
                    run_cue(cue, mtc, start_ms)
                except Exception as e:
                    # Illumination happens above, so a failure here would leave
                    # the cue lit forever with a dead thread behind it.
                    Logger.error(
                        f"run_cue failed for {cue.__class__.__name__} "
                        f"{cue.id}: {e}. The cue will not play."
                    )
                    self._end_illumination(cue)
                    return
                if isinstance(cue, DmxCue):
                    # DMX has no reveal: the scene is already on its way with an
                    # absolute mtc_time and the player self-schedules it. From
                    # here it is committed and the stop walk must not treat it
                    # as still cancellable.
                    with self._lock:
                        cue._revealed = True

            # MTC-gated reveal: wait until live MTC reaches start_ms, then reveal
            # (video /visible; audio /mtcfollow; action EXECUTE; dmx no-op). This
            # is what makes prewait/body/postwait real timeline gaps, honored
            # identically on every node. Skipped when the park was cancelled —
            # run_cue never ran, so _start_mtc holds no anchor to wait on.
            if parked != "stopped" and self._reveal_wait(cue, mtc, go_gen) != "stopped":
                # Commit under the same lock the stop walk takes, so a cancel
                # landing inside the 20ms poll gap cannot leak a reveal past it.
                with self._lock:
                    do_reveal = not cue._stop_requested and (
                        getattr(cue, "_go_generation", 0) == go_gen
                    )
                    if do_reveal:
                        cue._revealed = True
                if do_reveal:
                    reveal_cue(cue, mtc, start_ms)

        # A superseding GO/reload (new _go_generation, without _stop_requested)
        # can arrive during the now-MTC-gated reveal wait — that fresh thread
        # owns the chain. This stale thread must NOT pace postwait or fire the
        # next cue, or the next cue would be go()'d twice (once here with a stale
        # arrival, once by the fresh thread). Cleanup below is already gated by
        # the generation check, so we only guard the outward actions here.
        superseded = getattr(cue, "_go_generation", 0) != go_gen

        # Postwait for AUTO-CONTINUE only: ILLUMINATION hold. It no longer
        # paces anything — the chain left at this cue's arrival, above — but it
        # still holds this thread past the body when post > body, and that is
        # the ONLY thing producing continue's `pre + max(body, post)` highlight
        # (loop_cue never reads postwait, and remove_cue fires after it
        # returns). Removing it would silently shorten the highlight to
        # pre + body. For pause/go_at_end the postwait is a REAL gap AFTER the
        # body — handled by the MTC-gated tail below loop_cue, not by this
        # sleep.
        if (
            cue.post_go == "go"
            and cue.postwait > 0
            and not cue._stop_requested
            and not superseded
        ):
            sleep(cue.postwait.milliseconds_rounded / 1000)

        # Pre-arm go_at_end targets during playback. Runs after
        # run_cue() so current cue is already playing. The arm happens
        # in parallel with the media. go() also calls _arm_ahead but
        # that fires before run_cue — this call catches cues that were
        # disarmed between go() and here (loop passes).
        if cue.post_go == "go_at_end":
            self._arm_ahead(cue)

        Logger.info(f"Going to loop for {cue.__class__.__name__}:{cue.id}")
        loop_cue(cue, mtc)

        if getattr(cue, "_go_generation", 0) != go_gen:
            Logger.info(
                f"Cue {cue.id} generation changed ({go_gen} →"
                f"{cue._go_generation}), skipping cleanup"
            )
            return

        # ---- pause/go_at_end postwait tail -------------------------------
        # Spec: postwait is a real gap AFTER the body (follow: pre→body→post→
        # next; pause: pre→body→post→standby), and the cue stays illuminated
        # through it. Base end of the body on the MTC timeline; fallbacks for
        # cues that never set _end_mtc (plain ActionCue body=0; aborted A/V
        # setup; CueList) — and guard against a stale _end_mtc left by a
        # previous GO of this object. (FadeCue DOES set a real _end_mtc via
        # _handle_fade_action — used as-is.)
        end_attr = getattr(cue, "_end_mtc", None)
        base_end_ms = end_attr.milliseconds_exact if end_attr is not None else start_ms
        if base_end_ms < start_ms:
            base_end_ms = start_ms  # stale from a previous run
        fire_seed_ms = base_end_ms + cue.postwait.milliseconds_exact

        tail = (
            cue.post_go in ("pause", "go_at_end")
            and cue.postwait > 0
            and not cue._stop_requested
        )
        # Snapshot the follow target's generation BEFORE the tail, so the
        # auto-fire below can YIELD if a newer GO starts the target during the
        # tail — otherwise it would run twice. Only an EXPLICIT selection of the
        # target (setnextcue + GO) does that: a plain GO does not, because
        # Cue.get_next_cue() skips go/go_at_end targets, so next_cue_pointer
        # already points past the whole chain and a plain GO in the tail fires
        # the cue after it while the target still auto-follows. QLab-like; kept
        # deliberately (Ion, 2026-09-26; verified on test2, ClickUp 869ej4x38).
        target_gen0 = (
            getattr(cue._target_object, "_go_generation", 0)
            if cue._target_object
            else 0
        )
        if tail:
            # Hide output at body end WITHOUT disarming (cue must stay in
            # _armed_cues so STOP can reach this wait — disarming here would
            # let the tail expire and ghost-fire after an operator STOP).
            blank_cue(cue, mtc)
            self._wait_mtc(cue, mtc, fire_seed_ms, go_gen)
            if getattr(cue, "_go_generation", 0) != go_gen:
                # Real STOP (stop_all_cues bumps gen) / newer GO owns the cue:
                # no remove_cue (controller's stop already reset status), no
                # fire, no disarm (mirrors the post-loop generation guard).
                Logger.info(
                    f"Cue {cue.id} postwait tail cancelled (stop/newer GO),"
                    " skipping cleanup"
                )
                return
            # A pure _stop_requested exit (action-pause: sets the flag WITHOUT a
            # gen bump) falls through: remove_cue and the follow fire are already
            # guarded on _stop_requested below, and disarm still runs — exactly
            # today's behavior for an action-pause landing mid-body.

        # Notify the controller that the cue finished playing (status → 100).
        # Done here (after loop_cue) so the status only changes to 100 when the
        # cue has actually completed its full duration, not just when playback
        # started.
        # Skipped if the cue was stopped (controller's stop_script already
        # resets to 0).
        if cue._local and not getattr(cue, "_stop_requested", False):
            try:
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass

        go_at_end_thread = None
        if (
            cue.post_go == "go_at_end"
            and cue._target_object
            and not cue._stop_requested
            and getattr(cue._target_object, "_go_generation", 0) == target_gen0
        ):
            Logger.info(f"Running go at end for {cue.__class__.__name__}:{cue.id}")
            # go_from (not go): a non-local follow target is walked past to THIS
            # node's next local cue (go() would bail — same defect class as the
            # play-action loop-back). Explicit seed = body_end + postwait: exact
            # arrival on the shared timeline; go_threaded adds the target's own
            # prewait on top. The target_gen0 compare makes this auto-fire YIELD
            # if a manual GO already started the target during the tail.
            go_at_end_thread = self.go_from(cue._target_object, mtc, fire_seed_ms)
        elif (
            cue.post_go == "go_at_end"
            and cue._target_object
            and not cue._stop_requested
        ):
            Logger.info(
                f"go_at_end fire for {cue.id} yielded: "
                "target already started by a newer GO"
            )

        self.disarm(cue)

        if cue.post_go == "go_at_end" and go_at_end_thread:
            self.wait_for_cue(go_at_end_thread)

        if cue.post_go == "go" and cue._target_object and not cue._stop_requested:
            if post_go_thread:
                self.wait_for_cue(post_go_thread)

    def wait_for_cue(self, thread: Thread) -> None:
        """Waits for a cue to finish."""
        Logger.info(f"Waiting for {thread.name} to finish")
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
        """
        Execute an ActionCue against the running show (see ActionHandler).
        """
        from .ActionHandler import ACTION_HANDLER

        return ACTION_HANDLER.execute_action(cue, mtc, frozen_mtc_ms)

    def register_action_hook(
        self,
        phase: str,
        fn,
        *,
        action_types: frozenset | None = None,
    ) -> None:
        """
        Register a cue-layer extension hook; forwards to ``ACTION_HANDLER``.
        """
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
            path_parts: Path parts after 'audio' (e.g., ['mixer', '0',
            'master', 'volume']
                        or ['cue', '<uuid>', '0', 'volume'])
            value: The OSC value to set
        """
        if not path_parts:
            Logger.warning("Empty audio path parts")
            return

        if path_parts[0] == "mixer":
            # Route to audio mixer: ['mixer', '<output_index>', '<channel>',
            # 'volume']
            # → /audiomixer/0_mixer/<channel>
            if len(path_parts) >= 3:
                output_index = path_parts[1]
                channel = path_parts[2]
                mixer_cmd = f"/audiomixer/{output_index}_mixer/{channel}"
                mixer_client = PLAYER_HANDLER.get_audio_mixer_client()
                if mixer_client:
                    Logger.debug(f"Routing audio mixer: {mixer_cmd} = {value}")
                    mixer_client.set_value(mixer_cmd, float(value))
                else:
                    Logger.warning("Audio mixer client not available")
            else:
                Logger.warning(f"Invalid mixer path: {path_parts}")

        elif path_parts[0] == "cue":
            # Route to cue player: ['cue', '<uuid>', '<channel>', 'volume']
            # → /vol<channel> on the armed cue's OSC client
            if len(path_parts) >= 3:
                cue_uuid = path_parts[1]
                channel = path_parts[2]
                audio_cmd = f"/vol{channel}"
                cue = self.get_armed_cue_by_id(cue_uuid)
                if cue and hasattr(cue, "_osc") and cue._osc:
                    # UI already sends 0.0-1.0 via sliderToFloat(); just clamp
                    vol_value = max(0.0, min(1.0, float(value)))
                    Logger.debug(
                        f"Routing audio cue {cue_uuid}: {audio_cmd} = {vol_value}"
                    )
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
            path_parts: Path parts after 'dmx' (e.g., ['mixer', '0', 'channel',
            '1'])
            value: The OSC value to set
        """
        if not path_parts:
            Logger.warning("Empty DMX path parts, skipping routing")
            return
        if "mixer" not in path_parts:
            Logger.warning(
                f'Invalid DMX path (no "mixer" keyword): {path_parts}, skipping routing'
            )
            return

        # Build DMX command from path: find 'mixer' and use everything after it
        # +1 to skip 'mixer' keyword
        mixer_index = path_parts.index("mixer") + 1
        dmx_cmd = "/" + "/".join(path_parts[mixer_index:])
        dmx_client = PLAYER_HANDLER.get_dmx_player_client()
        if dmx_client:
            Logger.debug(f"Routing DMX: {dmx_cmd} = {value}")
            dmx_client.set_value(dmx_cmd, value)
        else:
            Logger.warning("DMX player client not available")

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

_ACTION_HANDLER_SINGLETON.bind_cue_handler(CUE_HANDLER)
