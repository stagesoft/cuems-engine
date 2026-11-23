# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
from threading import Event, Lock, Thread, current_thread, local
from time import monotonic, sleep
from typing import Callable

from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger, logged
from cuemsutils.tools.CTimecode import CTimecode

from ..comms.NodeCommunications import NodeCommunications
from ..players.PlayerHandler import PLAYER_HANDLER
from ..players.StartGate import START_GATE
from ..tools import MtcListener
from ..tools.engine_version import engine_version
from . import chain_pass, go_lead, loop_mode
from .ActionHandler import ACTION_HANDLER as _ACTION_HANDLER_SINGLETON
from .arm_cue import arm_cue
from .loop_cue import loop_cue
from .loop_mode import wrap_active
from .run_cue import (
    blank_cue,
    current_pass,
    installed_guard,
    installed_pass,
    picked_child,
    reveal_cue,
    run_cue,
)


@dataclass
class _ArmWalk:
    """State one background arm-ahead walk carries into arm()'s own
    post_go / ActionCue-target recursion (869f79ecc).

    Without it the recursion armed cues the walk excluded (audio), ran past
    the walk's should_continue checkpoint (a reload landing mid-arm), and
    armed cues the walk could not report (test2, 2026-09-25).

    epoch: the STOP/load epoch (CueHandler._disarm_epoch) in which the walk
    was REQUESTED, captured by whoever spawned it. Every arm the walk makes,
    recursion included, belongs to that epoch: see CueHandler.arm().
    """

    skip_types: tuple[type, ...] = ()
    should_continue: Callable[[], bool] | None = None
    armed: list = field(default_factory=list)
    epoch: int | None = None


@dataclass
class _ArmClaim:
    """One arm in flight for a cue id (CueHandler._arming).

    `event` wakes the threads waiting for it; `holder` / `started` exist so a
    timed-out wait can say who held the cue and for how long; `waiters`
    counts the threads parked on it.
    """

    event: Event = field(default_factory=Event)
    holder: str = ""
    started: float = 0.0
    waiters: int = 0


@dataclass
class _FollowOut:
    """What one cue thread did about its cross-node Auto follow (869fc8ytz).

    `record` is the (instant_ms, run_seq) it announced; the cue carries the
    same tuple as `_follow_out` until whoever takes it (the fire, the thread
    leaving, or go() starting the cue again) compare-and-clears it, so one
    announcement is followed by at most one cancel.
    """

    revealed: bool = False
    record: tuple | None = None
    fired: bool = False
    yielded: bool = False
    error: bool = False


# 869feynrj §4.5e: whether the pass a go() starts was SEEDED (go_at_end,
# ActionCue play / fade_in, a cross-node follow: anchors already past when the
# target is set up, Phase B's) or not (an operator GO, a chain cue, a rejoin).
# A late START of a seeded pass is INFO plus one WARNING per cue per load; of
# any other, a WARNING. Thread-local, set around the go() call by go_from and by
# a cue's thread around its continuation dispatch, so go()'s signature (and
# every caller's) is unchanged.
_DISPATCH = local()


@contextmanager
def _dispatch_tag(seeded: bool):
    previous = getattr(_DISPATCH, "seeded", False)
    _DISPATCH.seeded = bool(seeded)
    try:
        yield
    finally:
        _DISPATCH.seeded = previous


def _root_seq_value(root: int):
    """The root of the pass a go() on this thread mints (D31 d, addition 3):
    the UI toggles the node had received when the GO it descends from
    arrived."""
    return chain_pass.entry(root=int(root or 0))


def _root_seq(pass_):
    """A pass a follow or a loop-back starts inherits the root of the pass
    that starts it."""
    return _root_seq_value(getattr(pass_, "root_seq", 0) or 0)


class _SetupGuard:
    """The held setup's re-check (869feynrj S0-2): run_cue's sends happen in
    section(), under CueHandler._lock, and only while the pass that set the
    cue up is still its owner (not stopped, generation unchanged). A stale
    thread never sends anything to a player. Installed per thread by
    run_cue.installed_guard; a CueList's child is set up under its parent's."""

    def __init__(self, lock, cue: Cue, go_gen: int):
        self._lock = lock
        self._cue = cue
        self._gen = go_gen
        self.entered = False
        self.refused = False

    @contextmanager
    def section(self, setup_cue: Cue | None = None):
        """Yields whether the setup may send; holds the lock meanwhile. A
        setup that ran logs its hold (869feynrj step 3, plan §13): ``setup
        under lock: <t> ms (<type>, cue <id8>[, <n> layers])``, naming
        ``setup_cue`` (a CueList's child) or the pass's own cue."""
        held_ms = None
        ok = False
        try:
            with self._lock:
                t0 = monotonic()
                self.entered = True
                ok = not getattr(self._cue, "_stop_requested", False) and (
                    getattr(self._cue, "_go_generation", 0) == self._gen
                )
                if not ok:
                    self.refused = True
                try:
                    yield ok
                finally:
                    held_ms = (monotonic() - t0) * 1000
        finally:
            if ok and held_ms is not None:
                what = setup_cue if setup_cue is not None else self._cue
                layers = ""
                if isinstance(what, VideoCue):
                    layers = f", {len(getattr(what, '_layer_ids', None) or [])} layers"
                Logger.info(
                    f"setup under lock: {held_ms:.1f} ms ({type(what).__name__}, "
                    f"cue {str(what.id)[:8]}{layers})"
                )


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
    _lock: Lock
    communications_thread: NodeCommunications

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize instance attributes
            cls._instance._armed_cues = []
            cls._instance._armed_cues_set = set()
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

    # ---------------------------
    # Cue Management
    # ---------------------------

    # Minimum effective duration (ms) for a cue to "count" as providing
    # enough time to arm subsequent cues during its playback.
    # Configurable per deployment. Default 1000ms covers 4K video decode.
    _ARM_WINDOW_THRESHOLD_MS = 1000

    # Maximum cues to walk ahead. Prevents runaway on pathological chains.
    _MAX_LOOKAHEAD_DEPTH = 15

    # Total time one arm() call may spend waiting for an arm of the same cue
    # that another thread holds. A ceiling on the WAIT only: a waiter that
    # wakes inside it and finds the cue still unarmed arms it itself.
    _ARM_WAIT_TIMEOUT_S = 5.0

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

    # ---- self-gated audio start (869feynrj, CAPS selfgate) ---------------
    # The follow commit goes out at start - F, F per node (go_lead.
    # follow_lead_ms): max(_FOLLOW_LEAD_MS, this node's out_latency_ms + 2
    # polls + 5 + margin), due from the ROUNDED start label the player gets.
    # The GO lead L (go_lead.go_lead_ms) is the controller's; its floor and
    # cap are here too for the node's fallback. delta and the floor were
    # measured in step 3 and fixed by Ion (go_lead.py).
    _FOLLOW_LEAD_MS = go_lead.FOLLOW_LEAD_MS
    _GO_LEAD_FLOOR_MS = go_lead.GO_LEAD_FLOOR_MS
    _GO_LEAD_MAX_MS = go_lead.GO_LEAD_MAX_MS
    # This node's output latency + one JACK period (ms), set by NodeEngine
    # from settings / a JACK query / the players' LATENCY lines (§4.5d).
    # None: unknown (F is then _FOLLOW_LEAD_MS).
    out_latency_ms: float | None = None

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

    # ---- disarm epoch ----------------------------------------------------
    # Class-level default, like the two above. Bumped whenever everything a
    # cue was armed with is about to be torn down: in stop_all_cues() -- the
    # first step of a STOP and of a load, BEFORE the DMX/video reset and the
    # audio-player kill -- and again in disarm_all(), together with its
    # snapshot. An arm belongs to the epoch in which it was requested; one
    # whose epoch has moved is never published (see arm()).
    _disarm_epoch = 0

    # Cross-node Auto follow relay (cues.FollowRelay), attached by NodeEngine.
    # None (unit tests, an engine without comms): nothing is announced.
    _follow = None

    def arm_epoch(self) -> int:
        """The current STOP/load epoch. Whoever requests an arm on one thread
        and performs it on another captures this at request time and passes
        it along (arm(epoch=), _ArmWalk.epoch, _arm_ahead(arm_epoch=))."""
        return self._disarm_epoch

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
                body = (
                    CTimecode(cue.media.duration).milliseconds_exact if cue.media else 0
                )
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
            # TODO: use fade duration once fade_in/fade_out implemented
            body = 0
        else:
            body = 0

        return pre + body + post

    @staticmethod
    def _advance_mode(cue: Cue) -> str:
        """The advance mode of the chain a cue is in (1amfwm7jnqf, D11):
        ``sequential`` ("en serie") for every cue. ``parallel`` ("en
        paralelo", the 2026-08-14 rule) is kept for part 2's CueList mode and
        passed by no production call."""
        return chain_pass.SEQUENTIAL

    @staticmethod
    def _chain_advance_ms(cue: Cue, mode: str | None = None) -> float:
        """What a cue adds to the arrival of the cue after it in a
        post_go='go' (Auto continue) chain (1amfwm7jnqf, D1, D26):

            start(k)     = arrival(k) + prewait(k)
            arrival(k+1) = start(k) + postwait(k)      "en serie"

        so a cue's prewait and postwait push the cues after it, enabled or
        not; the body never advances a chain. ``parallel`` ("en paralelo")
        returns 0: every cue arrives at the trigger, the rule of 2026-08-14
        (869ej3cc8, Castillo Medina del Campo). An unknown mode raises.
        The arithmetic is chain_pass.advance_ms; a pass is laid out once by
        chain_pass.layout (Design §1)."""
        if mode is None:
            mode = CueHandler._advance_mode(cue)
        return chain_pass.advance_ms(cue, mode)

    #: An audio player in wrap mode ends its last pass by itself, a few ms
    #: after the engine's _end_mtc at most; its disarm (the kill) waits this
    #: many frames past _end_mtc so it never cuts the tail (869ejxng3 §4.5, H17).
    WRAP_END_MARGIN_FRAMES = 2

    def _wait_wrap_player_end(self, cue: Cue, mtc: MtcListener, go_gen: int) -> None:
        """Delay only an audio wrap-mode cue's end-of-cue disarm by 2 frames.

        loop_cue already returned at _end_mtc (the follow seeds from it, F8);
        the video layer of a VideoCue is hidden at _end_mtc as today."""
        if not isinstance(cue, AudioCue) or getattr(cue, "_stop_requested", False):
            return
        end = getattr(cue, "_end_mtc", None)
        if not wrap_active(cue) or end is None:
            return
        try:
            frame_ms = 1000.0 / float(end.framerate)
        except (TypeError, ValueError, ZeroDivisionError):
            frame_ms = 40.0
        self._wait_mtc(
            cue,
            mtc,
            end.milliseconds_exact + self.WRAP_END_MARGIN_FRAMES * frame_ms,
            go_gen,
        )

    def _wait_mtc(
        self,
        cue: Cue,
        mtc: MtcListener,
        target_ms: float,
        go_gen: int = 0,
        clock: Callable[[], float] | None = None,
    ) -> str:
        """Block until live MTC reaches target_ms; return 'reached' or 'stopped'.

        Shared timeline gate used both to illuminate a cue at its arrival and to
        reveal it at its start. Exits early on STOP (`_stop_requested`) or a
        newer GO/reload (`_go_generation` changed). Deliberately does NOT bail on
        a recoverable MTC stall — it self-recovers (fires late when timecode
        resumes). milliseconds_exact is wrap-accumulated → 24h-safe.

        clock: reads the MTC position; the whole-frame main_tc when None. The
        follow commit passes the interpolated reading (869feynrj §4.5b).
        """
        if clock is None:

            def clock():
                return mtc.main_tc.milliseconds_exact

        while clock() < target_ms:
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

    @staticmethod
    def _interpolated_clock(mtc: MtcListener) -> Callable[[], float]:
        """The interpolated MTC reading (MtcListener.interpolated_ms, 869feynrj
        §4.5b) as a clock for _wait_mtc; the whole-frame main_tc for an MTC
        object without one (test doubles)."""
        fn = getattr(mtc, "interpolated_ms", None)

        def read() -> float:
            if callable(fn):
                try:
                    value = fn()
                except Exception:
                    value = None
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value)
            return mtc.main_tc.milliseconds_exact

        return read

    def _follow_lead_ms(self) -> float:
        """F on this node (869feynrj §4.2 step 2, review 4 M2)."""
        return go_lead.follow_lead_ms(self.out_latency_ms)

    @staticmethod
    def _selfgate_target(cue: Cue):
        """(the AudioCue a stop of ``cue`` reaches, its player) when that
        player is selfgate, else (None, None). A CueList reaches its first
        enabled child (S0-11)."""
        target = picked_child(cue) if isinstance(cue, CueList) else cue
        if not isinstance(target, AudioCue):
            return None, None
        player = PLAYER_HANDLER.audio_player(target)
        if not loop_mode.player_selfgate(player):
            return None, None
        return target, player

    def cancel_start_locked(self, cue: Cue, kind: str) -> bool:
        """``/cancelstart`` to the selfgate player of ``cue`` if it may
        follow (869feynrj §4.3). The caller holds self._lock, in the section
        that sets the cue's stop flags, so the decision and the datagram are
        one step and a stale thread never sends.

        kind: "cancel" for a pass the engine has not revealed (its START, if
        the player began, is a WARNING); "stop_of_playing" for STOP (always,
        D10) and for the stops of a playing cue (D12): no WARNING, the player
        fades over fade_ms and the disconnect waits for it. Nothing is sent
        to an older player. Never raises; True if one went out.

        A VideoCue (or a CueList's video child) whose ``visible_at`` gate this
        pass armed and the engine has not revealed gets ``visible_at 0`` in
        the same section, whatever the kind (§4.6, D5)."""
        sent = False
        try:
            target, player = self._selfgate_target(cue)
            if target is not None:
                client = getattr(target, "_osc", None)
                sent = START_GATE.cancel(target, player, client, kind) is not None
        except Exception as e:
            Logger.error(f"Cue {cue.id}: /cancelstart not sent: {e}")
        return self._cancel_visible_at_locked(cue) or sent

    @staticmethod
    def _visible_at_target(cue: Cue) -> Cue | None:
        """The VideoCue whose ``visible_at`` gate a stop of ``cue`` reaches
        (the cue, or the child a CueList's pass committed), while that gate
        is an open account: armed by a follow commit, neither cancelled nor
        revealed by the engine since. None otherwise.

        A CueList reaches its child's gate only while that gate is the one
        ITS pass armed (review C3): the child's ``_visible_at_pass`` must be
        (the parent, the parent's committing generation). A newer pass of
        the child on its own is not the parent's to cancel."""
        if isinstance(cue, CueList):
            target = getattr(cue, "_visible_at_child", None)
            owner = (id(cue), getattr(cue, "_visible_at_child_gen", None))
            if target is None or getattr(target, "_visible_at_pass", None) != owner:
                return None
        else:
            target = cue
        if not isinstance(target, VideoCue):
            return None
        if getattr(target, "_visible_at_gen", None) is None:
            return None
        return target

    @staticmethod
    def _close_visible_at(target: Cue, parent: Cue | None = None) -> None:
        """Close a gate's account (cancel, the engine's reveal, the layers'
        release): the cue's record and, for a CueList's child, the parent's
        reference to it (review C3). Call with self._lock held."""
        target._visible_at_gen = None
        target._visible_at_layers = None
        target._visible_at_pass = None
        if parent is not None:
            parent._visible_at_child = None
            parent._visible_at_child_gen = None

    def _cancel_visible_at_locked(self, cue: Cue) -> bool:
        """``visible_at 0`` to the layers of a pending (or just gate-revealed)
        pass of ``cue`` (869feynrj §4.3, §4.6): the videocomposer drops the
        gate, or hides a layer it revealed a few ms before this cancel, with
        its WARNING ``visible_at cancelled after <ms> ms visible``
        (cuems-videocomposer VideoLayer.cpp:558-567). The caller holds
        self._lock, in the section that sets the stop flags. Sent once: the
        account is closed here. Never raises; True if one went out."""
        try:
            target = self._visible_at_target(cue)
            if target is None:
                return False
            layers = list(getattr(target, "_visible_at_layers", None) or [])
            self._close_visible_at(target, cue if cue is not target else None)
            client = getattr(target, "_osc", None)
            if client is None or not layers:
                return False
            sent = 0
            for layer_id in layers:
                try:
                    client.set_value(f"/videocomposer/layer/{layer_id}/visible_at", 0)
                    sent += 1
                except Exception as e:
                    Logger.error(
                        f"Video cue {target.id}: visible_at 0 not sent to layer "
                        f"{layer_id}: {e}"
                    )
            Logger.info(
                f"Video cue {target.id}: visible_at 0 to {sent} layer(s) "
                "(pass cancelled before its reveal)"
            )
            return sent > 0
        except Exception as e:
            Logger.error(f"Cue {cue.id}: visible_at 0 not sent: {e}")
            return False

    def _follow_commit_target(self, cue: Cue) -> Cue | None:
        """The AudioCue whose selfgate player this pass commits a follow to:
        the cue itself, or a CueList's first enabled child, played at the
        parent's start (S0-11). None for any other cue or an older player."""
        target = cue
        if isinstance(cue, CueList):
            target = picked_child(cue)
            if target is None or not getattr(target, "_local", False):
                return None
        if getattr(target, "_start_mtc", None) is None:
            return None
        if isinstance(target, VideoCue):
            # 869feynrj §4.6: the commit is visible_at 1 to every layer, on a
            # videocomposer that takes it; a dark cue (no layer on this
            # node) has nothing to gate.
            if (
                not getattr(target, "_layer_ids", None)
                or getattr(target, "_osc", None) is None
                or not loop_mode.vc_visible_at(PLAYER_HANDLER.video_caps)
            ):
                return None
            return target
        if not isinstance(target, AudioCue):
            return None
        if not loop_mode.player_selfgate(PLAYER_HANDLER.audio_player(target)):
            return None
        return target

    def _commit_follow(
        self, cue: Cue, target: Cue, go_gen: int, mtc: MtcListener | None = None
    ) -> bool:
        """The follow commit (869feynrj §4.2 step 2): ``/mtcfollow 1`` to a
        selfgate player at start - F, decided AND sent under _lock (S0-3), so
        a cancel deciding in the same lock either precedes it (and the commit
        is refused) or follows it (and its /cancelstart goes out after the
        follow). Refused when the pass was stopped, superseded, or its start
        was never sent (`_reveal_ready`, review 2 F11: a follow without its
        start would play from offset 0). A VideoCue target goes to
        _commit_visible_at (§4.6)."""
        if isinstance(target, VideoCue):
            return self._commit_visible_at(cue, target, go_gen, mtc)
        with self._lock:
            if getattr(cue, "_stop_requested", False) or (
                getattr(cue, "_go_generation", 0) != go_gen
            ):
                Logger.info(
                    f"Cue {cue.id}: follow commit refused, the pass was stopped "
                    "or superseded"
                )
                return False
            if not self._child_current_locked(cue, target, go_gen):
                # Review C2, the audio side of S0-11.
                Logger.info(
                    f"Audio cue {target.id}: follow commit refused, the CueList "
                    "child was disabled, stopped or replaced since the setup"
                )
                return False
            if not getattr(target, "_reveal_ready", False):
                Logger.info(
                    f"Audio cue {target.id}: follow commit refused, its start "
                    "was never sent (setup aborted)"
                )
                return False
            player = PLAYER_HANDLER.audio_player(target)
            client = getattr(target, "_osc", None)
            if client is None or not loop_mode.player_selfgate(player):
                return False
            sent_at = self._interpolated_clock(mtc)() if mtc is not None else None
            if not START_GATE.commit_follow(target, player, client, go_gen):
                return False
            cue._follow_gen = go_gen
            target._follow_committed = True
        # 869feynrj step 3: m = this node's interpolated MTC at the send.
        start = target._start_mtc.milliseconds_exact
        at = f"{sent_at:.1f}" if sent_at is not None else "?"
        Logger.info(
            f"follow commit: cue {str(target.id)[:8]} at mtc {at} ms, start "
            f"{start:.1f} ms, F {self._follow_lead_ms():.1f} ms"
        )
        return True

    def _commit_visible_at(
        self, cue: Cue, target: VideoCue, go_gen: int, mtc: MtcListener | None
    ) -> bool:
        """The follow commit of a VideoCue (869feynrj §4.6): ``visible_at 1``
        to every layer, at start - F, decided AND sent under _lock like the
        audio cues' ``/mtcfollow 1`` (S0-3), so a cancel deciding in the same
        lock either precedes it (no gate) or follows it (its ``visible_at 0``
        goes out after the gate). The videocomposer then reveals each layer on
        the first presented frame with content time >= 0
        (RemoteCommandRouter.cpp:134-136, VideoLayer.cpp:548-557). Refused
        when the pass was stopped, superseded, or its setup never reached the
        layers (`_visible_at_ready`). The gate is recorded on the cue
        (`_visible_at_gen`, `_visible_at_layers`; a CueList parent keeps
        `_visible_at_child`) until a cancel, the engine's reveal or the
        layers' release closes it.

        A GO-again of a cue whose layer the gate already revealed opens a
        new account too, although the VC leaves a visible layer as it is
        (`VideoLayer.cpp:551-552`): a cancel of the new pass before its
        reveal then sends ``visible_at 0`` and the VC hides the layer, which
        by then holds the new pass's frame 0. Intended (review C1, Ion
        2026-11-10 = (a); D5: the cancel is final, a cancelled cue leaves
        nothing frozen on screen)."""
        with self._lock:
            if getattr(cue, "_stop_requested", False) or (
                getattr(cue, "_go_generation", 0) != go_gen
            ):
                Logger.info(
                    f"Cue {cue.id}: follow commit refused, the pass was stopped "
                    "or superseded"
                )
                return False
            if not self._child_current_locked(cue, target, go_gen):
                Logger.info(
                    f"Video cue {target.id}: follow commit refused, the CueList "
                    "child was disabled, stopped or replaced since the setup"
                )
                return False
            if not getattr(target, "_visible_at_ready", False):
                Logger.info(
                    f"Video cue {target.id}: follow commit refused, its setup "
                    "never reached the layers"
                )
                return False
            client = getattr(target, "_osc", None)
            layer_ids = list(getattr(target, "_layer_ids", None) or [])
            if client is None or not layer_ids:
                return False
            sent_at = self._interpolated_clock(mtc)() if mtc is not None else None
            sent = []
            for layer_id in layer_ids:
                try:
                    client.set_value(f"/videocomposer/layer/{layer_id}/visible_at", 1)
                    sent.append(layer_id)
                except Exception as e:
                    # The reveal's /visible 1 heals this layer.
                    Logger.warning(
                        f"Video cue {target.id}: visible_at 1 not sent to layer "
                        f"{layer_id}: {e}"
                    )
            if not sent:
                return False
            target._visible_at_gen = go_gen
            target._visible_at_layers = sent
            # Whose pass armed it (review C3): a CueList parent reaches it
            # only while this stays (the parent, this generation).
            target._visible_at_pass = (id(cue), go_gen)
            if cue is not target:
                cue._visible_at_child = target
                cue._visible_at_child_gen = go_gen
        start = target._start_mtc.milliseconds_exact
        at = f"{sent_at:.1f}" if sent_at is not None else "?"
        Logger.info(
            f"follow commit: video cue {str(target.id)[:8]} visible_at 1 on "
            f"{len(sent)} layer(s) at mtc {at} ms, start {start:.1f} ms, "
            f"F {self._follow_lead_ms():.1f} ms"
        )
        return True

    def _run_timeline(
        self,
        cue: Cue,
        mtc: MtcListener,
        arrival_ms: float,
        start_ms: float,
        go_gen: int,
        pass_=None,
    ) -> tuple[str, Cue | None]:
        """Setup, illumination and the follow commit of one pass, as three
        events taken in due-time order (869feynrj §4.2, review 4 M3):

        - setup at max(now, start - _RUN_AHEAD_MS), NOT gated on the arrival
          (review #1: a led operator GO's arrival is the start itself);
        - illumination at the arrival (a cue lights when it arrives);
        - the follow commit at start label - F, for a selfgate AudioCue (or a
          CueList's selfgate child) only, always after the setup (it needs
          the start sent).

        Ties: setup, then commit, then illumination. Returns ("ready",
        follow target or None), ("stopped", None) or ("failed", None) when
        run_cue raised (logged, illumination ended)."""
        pending = {"setup": start_ms - self._RUN_AHEAD_MS, "illum": arrival_ms}
        rank = {"setup": 0, "decide": 1, "commit": 2, "illum": 3}
        target = None
        # A cue with outputs on several nodes (1amfwm7jnqf Design §2): every
        # owner decides its output at the same instant, start - W (or the
        # pass's anchor if later), from the flag as every node sees it.
        several = self._several_owners(cue)
        decided = None
        if pass_ is None:
            pass_ = getattr(cue, "_pass", None)
        if several:
            pending["decide"] = self._decide_instant(cue, start_ms)
        while pending:
            name = min(pending, key=lambda n: (pending[n], rank[n]))
            due = pending.pop(name)
            if name == "decide":
                if self._wait_mtc(cue, mtc, due, go_gen) == "stopped":
                    return "stopped", None
                self._step_wait(cue, "decide", go_gen, pass_)
                decided = self._common(cue, due)
                self._step_done(cue, "decide", pass_)
                if not decided:
                    with self._lock:
                        if getattr(cue, "_go_generation", 0) == go_gen:
                            # Its held setup, if any, is dropped.
                            self.cancel_start_locked(cue, "cancel")
                    Logger.info(
                        f"Cue {cue.id}: off as every node sees it at {due:.0f} "
                        "ms; silent in this pass on every owner"
                    )
                    return "silent", None
                if getattr(cue, "_setup_skipped", False):
                    # Off on this node when its setup was due, on for every
                    # owner now: armed and set up now, late if it must.
                    cue._setup_skipped = False
                    if not getattr(cue, "loaded", False):
                        self.arm(cue, init=True)
                    pending["setup"] = due
                continue
            if name == "illum":
                if self._wait_mtc(cue, mtc, due, go_gen) == "stopped":
                    return "stopped", None
                # Illuminate (sequence-view highlight) at the cue's ARRIVAL —
                # the start of its prewait — NOT at dispatch: each cue lights
                # at its own place in the pass's layout (1amfwm7jnqf) and
                # stays lit for prewait + max(body, postwait).
                try:
                    self.communications_thread.add_cue(
                        cue.id, str(start_ms), timeout=0.1
                    )
                except Exception:
                    pass
            elif name == "setup":
                # Park until the held setup is actually needed. Unrolling the
                # chain at the trigger would otherwise run every cue's run_cue
                # at GO — for video that is N layers decoding invisibly for
                # the whole of their prewaits. A start already inside the
                # window returns at once.
                if self._wait_mtc(cue, mtc, due, go_gen) == "stopped":
                    return "stopped", None
                if isinstance(cue, (DmxCue, CueList)):
                    self._step_wait(cue, "setup", go_gen, pass_)
                if several and decided is None and not getattr(cue, "enabled", True):
                    # Several owners, off on this node: set up only if every
                    # owner decides it on.
                    cue._setup_skipped = True
                    continue
                if isinstance(cue, DmxCue) and not self._common(
                    cue, self._scene_instant(cue, start_ms)
                ):
                    # D25: a DMX cue off as every node sees it when its scene
                    # is due sends none; enabled by its start, it sends it
                    # late, at the start.
                    cue._scene_withheld = True
                    Logger.info(f"{cue.id}: DMX scene not sent, the cue is disabled")
                    self._step_done(cue, "setup", pass_)
                    continue
                if isinstance(cue, CueList):
                    # One pick per pass, before the setup sends anything
                    # (Design §2).
                    self._mark_cuelist_child(cue, go_gen, start_ms)
                # Set up HELD at start_ms (video invisible / audio
                # not-following / action not-yet-run / dmx self-scheduled from
                # absolute mtc_time), close enough to the slot that the frame
                # is ready. Its sends re-check the pass under _lock (S0-2).
                guard = _SetupGuard(self._lock, cue, go_gen)
                try:
                    with installed_guard(guard):
                        run_cue(cue, mtc, start_ms)
                except Exception as e:
                    # Illumination may have happened above, so a failure here
                    # would leave the cue lit forever with a dead thread.
                    Logger.error(
                        f"run_cue failed for {cue.__class__.__name__} "
                        f"{cue.id}: {e}. The cue will not play."
                    )
                    self._end_illumination(cue)
                    return "failed", None
                if guard.refused:
                    return "stopped", None
                if isinstance(cue, DmxCue):
                    # DMX has no reveal: the scene is already on its way with
                    # an absolute mtc_time and the player self-schedules it.
                    # From here it is committed and the stop walk must not
                    # treat it as still cancellable.
                    with self._lock:
                        cue._revealed = True
                        cue._revealed_at = monotonic()
                        cue._scene_out = go_gen
                    Logger.info(f"DMX scene sent to local player for cue {cue.id}")
                self._step_done(cue, "setup", pass_)
                target = self._follow_commit_target(cue)
                if target is not None:
                    pending["commit"] = (
                        target._start_mtc.milliseconds_exact - self._follow_lead_ms()
                    )
            elif name == "commit":
                if (
                    self._wait_mtc(
                        cue, mtc, due, go_gen, clock=self._interpolated_clock(mtc)
                    )
                    == "stopped"
                ):
                    return "stopped", None
                if not self._commit_follow(cue, target, go_gen, mtc):
                    target = None
        return "ready", target

    def _arm_ahead(
        self,
        start_cue: Cue,
        should_continue: Callable[[], bool] | None = None,
        skip_arming_types: tuple[type, ...] = (),
        arm_epoch: int | None = None,
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

        arm_epoch: the STOP/load epoch this walk was requested in (see
        arm_epoch()). Once it has moved the walk stops, and arm() refuses or
        abandons whatever it was still arming -- nothing is armed for a
        request that predates a STOP or a load.

        Returns the cues THIS call transitioned from unloaded to loaded —
        not merely already-armed ones, and not ones a concurrent call
        armed.
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
            _ArmWalk(skip_arming_types, should_continue, newly_armed, arm_epoch)
            if (
                should_continue is not None
                or skip_arming_types
                or arm_epoch is not None
            )
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
            if arm_epoch is not None and arm_epoch != self._disarm_epoch:
                Logger.info(
                    f"_arm_ahead from {start_cue.id} stopped early — a STOP "
                    "or a load happened since it was requested"
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

    def _arming_registry(self) -> dict:
        """Arms in flight, keyed by cue id. Call with self._lock held.

        Keyed by ID, not held on the cue object: what an arm creates is keyed
        by id (the tracked player, the JACK client name Audio_Player-<uuid>,
        the video layer ids) and Cue.__eq__/__hash__ are by id, so the old and
        the new object of one cue -- a project loaded twice -- must exclude
        each other. Created lazily: handlers built with object.__new__ (tests)
        never ran __new__.
        """
        registry = self.__dict__.get("_arming")
        if registry is None:
            registry = self.__dict__.setdefault("_arming", {})
        return registry

    def arm(
        self,
        cue: Cue,
        init=False,
        walk: _ArmWalk | None = None,
        epoch: int | None = None,
        wait_report: dict | None = None,
    ) -> bool:
        """Arms a cue by appending it to the armed_cues list.

        wait_report: optional dict. When this call waits for another thread's
        arm of the same cue, it sets wait_report["waited_s"] (total seconds
        waited) and wait_report["holder"] (that thread's name), so a caller
        can say what really happened instead of guessing from a check made
        before the call (869fbyjzx).

        walk: set only by a background _arm_ahead walk (NodeEngine's PreArm).
        Its excluded types and should_continue checkpoint also govern this
        call's own post_go / ActionCue-target recursion, and every cue this
        call chain actually arms is recorded in walk.armed (869f79ecc).

        One arm is in flight per cue id (_arming_registry). An init caller
        that finds one waits for it, up to _ARM_WAIT_TIMEOUT_S in total, and
        then re-evaluates: if the cue is still unarmed (the arm it waited on
        failed or was abandoned) it arms the cue itself instead of giving up.

        PUBLISH OR ABANDON. An arm belongs to the STOP/load epoch in which it
        was REQUESTED: `epoch` if given, else the walk's, else _disarm_epoch
        as read here at entry. It is never re-read. If it has moved:
        - before the cue is claimed (entry, or waking from a wait): return
          False and arm nothing -- even if the cue is loaded by now, because
          then the NEW epoch loaded it and a stale caller must not adopt it;
        - while arm_cue() was running: the arm is ABANDONED at the publish
          gate. The cue is never marked loaded and never enters the armed
          list, so no GO can pick it up; what this arm built (a player the
          STOP may already have killed, video layers) is released here,
          while this thread still holds the cue's claim.
        The gate also abandons a cue that was disabled while it was arming.
        So no thread ever has to disarm a cue after the fact, which is what
        used to cut a cue the next run was already playing (869f9wqpn).
        """
        if cue is None:
            return False
        if epoch is None:
            epoch = (
                walk.epoch
                if walk is not None and walk.epoch is not None
                else self._disarm_epoch
            )
        if walk is not None:
            if walk.skip_types and isinstance(cue, walk.skip_types):
                return False
            if walk.should_continue is not None and not walk.should_continue():
                return False

        wait_deadline = None
        waited_total = 0.0
        while True:
            needs_disarm = False
            claim = None
            pending = None
            stale = False

            with self._lock:
                registry = self._arming_registry()
                in_flight = registry.get(cue.id)
                if epoch != self._disarm_epoch:
                    # Checked FIRST, on entry and on every wake.
                    stale = True
                elif hasattr(cue, "loaded") and cue.loaded:
                    # A disabled cue takes effect from the next round (Q-S0-A
                    # = (A), S0-21): a cue still playing is never disarmed
                    # here; disarm() / STOP clear _playing when it ends.
                    if not cue.enabled and not getattr(cue, "_playing", False):
                        needs_disarm = True
                elif in_flight is not None:
                    if not init:
                        # Non-init callers just register; no need to wait
                        return False
                    # Another thread is arming — wait for it outside the lock
                    pending = in_flight
                    pending.waiters += 1
                elif not init:
                    if cue.id not in self._armed_cues_set:
                        self._armed_cues.append(cue)
                        self._armed_cues_set.add(cue.id)
                elif cue._local and cue.enabled:
                    # Claim the cue inside the lock to block concurrent arm
                    # attempts; released in the finally below (outside the
                    # lock — intentional: avoids holding it during arm_cue()).
                    claim = _ArmClaim(holder=current_thread().name, started=monotonic())
                    registry[cue.id] = claim

            if stale:
                Logger.info(
                    f"Not arming {type(cue).__name__} {cue.id}: a STOP or a "
                    "load happened since this arm was requested"
                )
                return False

            if pending is None:
                break

            if wait_deadline is None:
                wait_deadline = monotonic() + self._ARM_WAIT_TIMEOUT_S
            remaining = wait_deadline - monotonic()
            Logger.debug(
                f"Waiting for in-progress arm of {type(cue).__name__} {cue.id}"
            )
            wait_started = monotonic()
            woke = remaining > 0 and pending.event.wait(timeout=remaining)
            waited_total += monotonic() - wait_started
            if wait_report is not None:
                wait_report["waited_s"] = waited_total
                wait_report["holder"] = pending.holder
            with self._lock:
                pending.waiters -= 1
            if not woke:
                Logger.warning(
                    f"Timed out waiting for arm of {cue.id} (held by "
                    f"{pending.holder} for {monotonic() - pending.started:.1f}s)"
                )
                return (
                    bool(getattr(cue, "loaded", False)) and epoch == self._disarm_epoch
                )
            # Woken: loop and look again. Epoch moved -> give up; loaded ->
            # done; still unarmed -> this thread claims it and arms it itself.

        # Disarm disabled-but-loaded cues outside lock (disarm acquires lock)
        if needs_disarm:
            self.disarm(cue, reason="disabled")
            return False

        if claim is None:
            return not needs_disarm

        abandoned = None
        try:
            Logger.info(f"Arming {type(cue).__name__} {cue.id}")
            arm_started = monotonic()
            arm_cue(cue)
            # The publish gate. Same lock as the epoch bumps (stop_all_cues,
            # disarm_all): either this section comes first and the STOP finds
            # the cue in the armed list and disarms it itself, or the bump
            # comes first and the cue is never published.
            with self._lock:
                if epoch != self._disarm_epoch:
                    abandoned = "a STOP or a load happened while it was arming"
                elif not cue.enabled:
                    abandoned = "it was disabled while it was arming"
                else:
                    cue.loaded = True
                    # Measurement only (the armed-to-start and never-played
                    # lines): set at every publish, so a cue object reused
                    # across runs never carries the previous arm's stamps.
                    cue._armed_at = monotonic()
                    cue._ever_played = False
                    if cue.id not in self._armed_cues_set:
                        self._armed_cues.append(cue)
                        self._armed_cues_set.add(cue.id)
            if abandoned is not None:
                Logger.info(
                    f"Abandoned arm of {type(cue).__name__} {cue.id}: {abandoned}"
                )
                self._release_unpublished(cue, "abandoned_arm")
                return False
            # Engine side only: for audio that is the spawn and the JACK port
            # wait; for video it is the OSC sends, and the file open is the
            # videocomposer's own "AsyncVideoLoader: Loaded ... in Nms".
            Logger.info(
                f"Armed {type(cue).__name__} {cue.id} in "
                f"{cue._armed_at - arm_started:.3f} s"
            )
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
            # ...and give back whatever it got as far as building (a spawned
            # player, registered layers), still under this cue's claim.
            self._release_unpublished(cue, "arm_failed")
            return False
        finally:
            # Always, and before the recursion below: a leaked claim would
            # block every later arm of this cue id, across reloads too, and a
            # claim held through the recursion would deadlock a go-chain cycle.
            with self._lock:
                registry = self._arming_registry()
                if registry.get(cue.id) is claim:
                    del registry[cue.id]
            claim.event.set()

        # Recursive arms — only reached if cue was actually armed.
        # The claim is released by now; the loaded guard prevents re-arm.
        # Through a disabled cue, as the lookahead does (1amfwm7jnqf §1): it
        # keeps its place in the chain; it is never armed itself.
        nxt = self._next_enabled_in_chain(cue) if cue.post_go == "go" else None
        if nxt is not None:
            if walk is not None:
                self.arm(nxt, init, walk=walk, epoch=epoch)
            else:
                self.arm(nxt, init, epoch=epoch)

        # ActionCue(play) and FadeCue(fade_action) + target = 1 unit. Arm
        # target
        # so it's ready when the action fires (ActionCue has zero duration;
        # FadeCue
        # expects target_cue already armed before reading its OSC cache).
        if isinstance(cue, ActionCue) and cue._action_target_object:
            if cue.action_type in ("play", "fade_action"):
                if walk is not None:
                    self.arm(cue._action_target_object, init, walk=walk, epoch=epoch)
                else:
                    self.arm(cue._action_target_object, init, epoch=epoch)

        return True

    @staticmethod
    def _next_enabled_in_chain(cue: Cue) -> Cue | None:
        """The first enabled cue behind ``cue`` along post_go='go' links,
        walking through disabled ones (a disabled cue that is not 'go' ends
        the chain), or None."""
        nxt, seen = getattr(cue, "_target_object", None), {id(cue)}
        while nxt is not None and not getattr(nxt, "enabled", True):
            if id(nxt) in seen or getattr(nxt, "post_go", None) != "go":
                return None
            seen.add(id(nxt))
            nxt = getattr(nxt, "_target_object", None)
        return nxt if nxt is not None and id(nxt) not in seen else None

    def armed_inventory(self) -> dict:
        """What this node holds armed right now: published (loaded) cues by
        type, the video layers they hold, and how many of them a GO owns
        (playing) versus are only held (idle). CueLists are left out: they
        hold nothing. Measurement only."""
        with self._lock:
            held = [
                c
                for c in self._armed_cues
                if getattr(c, "loaded", False) and not isinstance(c, CueList)
            ]
        inv = {
            "cues": len(held),
            "video": 0,
            "layers": 0,
            "audio": 0,
            "dmx": 0,
            "other": 0,
            "playing": 0,
            "idle": 0,
        }
        for cue in held:
            if isinstance(cue, VideoCue):
                inv["video"] += 1
                inv["layers"] += len(getattr(cue, "_layer_ids", None) or [])
            elif isinstance(cue, AudioCue):
                inv["audio"] += 1
            elif isinstance(cue, DmxCue):
                inv["dmx"] += 1
            else:
                inv["other"] += 1
            inv["playing" if getattr(cue, "_playing", False) else "idle"] += 1
        return inv

    def log_armed_inventory(self, where: str) -> None:
        """One INFO line with armed_inventory(). Never raises: it is called
        at the end of a GO and of a PreArm thread, which must not fail on a
        log line."""
        try:
            inv = self.armed_inventory()
            Logger.info(
                f"Armed inventory after {where}: {inv['cues']} cues "
                f"(video {inv['video']} cues / {inv['layers']} layers, "
                f"audio {inv['audio']} players, dmx {inv['dmx']}, "
                f"other {inv['other']}); playing {inv['playing']}; "
                f"idle {inv['idle']}"
            )
        except Exception as e:
            Logger.warning(f"Could not count the armed inventory ({where}): {e}")

    @staticmethod
    def _log_arm_wait(
        cue: Cue, where: str, in_flight: str | None, wait_report: dict
    ) -> None:
        """Report what arm() did about an arm in flight (869fbyjzx)."""
        waited = wait_report.get("waited_s")
        if waited is not None:
            Logger.info(
                f"Cue {cue.id} waited {waited:.2f}s at {where} for the arm in "
                f"progress (held by {wait_report.get('holder')})"
            )
        elif in_flight is not None:
            Logger.info(
                f"Cue {cue.id}: the arm in progress at {where} had finished "
                f"before this call looked; no wait"
            )

    def describe_arm_in_flight(self, cue: Cue) -> str | None:
        """Who is arming this cue right now and for how long, as text for a
        log line; None when no arm of it is in flight."""
        with self._lock:
            claim = self._arming_registry().get(cue.id)
        if claim is None:
            return None
        return f"held by {claim.holder} for {monotonic() - claim.started:.1f}s"

    def _release_unpublished(self, cue: Cue, reason: str) -> None:
        """Give back what an arm built for a cue it is not going to publish.

        Only ever called by the thread that holds the cue's arm claim, so
        nobody else can have created resources for that cue id meanwhile.
        Never raises: the caller is about to release the claim, and a claim
        that leaked here would block every later arm of this cue.
        """
        try:
            self._release_cue_resources(cue, reason, what="Released")
        except Exception as e:
            Logger.error(
                f"Could not release what the unpublished arm of {cue.id} built "
                f"({reason}): {e}"
            )

    def disarm(self, cue: Cue, reason: str = "unspecified") -> bool:
        """Disarms a cue by removing it from the armed_cues list.

        ``reason`` names why (``cue_end``, ``stop_action``, ``disabled``,
        ``project_changed``, ``load``, ``ready_script``, ``shutdown``) and is
        logged: a disarm, the automatic one at cue end included, must never
        be silent.

        A selfgate player that may still follow gets ``/cancelstart`` first
        (869feynrj §4.3 "any disarm", D12), so a disarm of a playing cue fades
        instead of clicking; the disconnect waits for the fade
        (PlayerHandler). Not at a natural end (``cue_end``): the pass is over.
        """
        if reason != "cue_end" and (
            self._selfgate_target(cue)[0] is not None
            or self._visible_at_target(cue) is not None
        ):
            with self._lock:
                self.cancel_start_locked(
                    cue,
                    (
                        "stop_of_playing"
                        if getattr(cue, "_revealed", False)
                        else "cancel"
                    ),
                )
        cue._playing = False
        if hasattr(cue, "loaded") and cue.loaded:
            self.remove_armed_cue(cue)
            cue.loaded = False
            armed_at = getattr(cue, "_armed_at", None)
            if (
                armed_at is not None
                and not getattr(cue, "_ever_played", False)
                and reason != "cue_end"
                and not isinstance(cue, CueList)
            ):
                # An arm that bought nothing: what a pre-arm policy costs.
                # Not a CueList: go() never dispatches one (the project's
                # root is armed at every load and STOP) and it holds nothing.
                Logger.info(
                    f"Cue {cue.id} disarmed after {monotonic() - armed_at:.1f} s "
                    f"armed, never played ({reason})"
                )
            try:
                if isinstance(cue, AudioCue):
                    self.communications_thread.remove_player(
                        f"audioplayer_{cue.id}", timeout=0.1
                    )
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass

            self._release_cue_resources(cue, reason)
            return True

        return False

    def _release_cue_resources(
        self, cue: Cue, reason: str, what: str = "Disarmed"
    ) -> None:
        """Release what arm_cue() built for a cue: its video layers and its
        player. The resource half of disarm(), also used for an arm that is
        abandoned or fails before the cue is ever published (arm()).

        Deliberately touches neither `_playing`, nor the armed list, nor the
        controller's cue status: an unpublished cue has none of them.
        """
        if isinstance(cue, VideoCue):
            layer_ids = getattr(cue, "_layer_ids", [])
            client = getattr(cue, "_osc", None)
            unloaded, skipped = [], []
            if client and layer_ids:
                for layer_id in layer_ids:
                    # /videocomposer/reset (STOP, load, ready_script) runs
                    # before disarm_all on purpose (instant blackout) and
                    # already removed this layer and its endpoints.
                    if not PLAYER_HANDLER.is_layer_registered(layer_id):
                        skipped.append(layer_id)
                        continue
                    # Hiding is cosmetic (unload removes the layer anyway):
                    # a failure here must not skip the unload.
                    try:
                        client.set_value(f"/videocomposer/layer/{layer_id}/visible", 0)
                    except Exception as e:
                        Logger.warning(
                            f"Could not hide video layer {layer_id} (visible 0)"
                            f" of cue {cue.id} ({reason}): {e}"
                        )
                    try:
                        client.set_value("/videocomposer/layer/unload", layer_id)
                        client.remove_layer_endpoints(layer_id)
                        PLAYER_HANDLER.deregister_layer(layer_id)
                        unloaded.append(layer_id)
                    except Exception as e:
                        # Left registered: the next /reset still cleans it up.
                        Logger.warning(
                            f"Could not unload video layer {layer_id} of cue"
                            f" {cue.id} ({reason}): {e}"
                        )
            cue._layer_ids = []
            # 869feynrj §4.6: the layers are gone, and so is any gate on them
            # (a CueList parent's reference fails its ownership check now).
            self._close_visible_at(cue)
            Logger.debug(
                f"{what} video cue {cue.id} ({reason}): unloaded {unloaded};"
                f" skipped {skipped} (no longer tracked: removed by reset or quit)"
                + ("" if client else "; no video client")
            )
        else:
            Logger.debug(f"{what} {type(cue).__name__} {cue.id} ({reason})")

        PLAYER_HANDLER.remove_cue_player(cue)

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
            # The teardown starts HERE: between this call and disarm_all()
            # the engine resets DMX and video and kills every audio player.
            # Moving the epoch in this same section means an arm publishes
            # either before it (then it is in _armed_cues, flagged just
            # below and disarmed later) or after it (then it is abandoned).
            self._disarm_epoch = self._disarm_epoch + 1
            # Every pass ends: every toggle record is folded (Design §3), and
            # nothing waits for a step of it.
            chain_pass.forget()
            self._live_passes().clear()
            self._awaiting_passes().clear()
            self.__dict__.pop("_entered", None)
            self._step_order().clear()
            for cue in self._armed_cues:
                cue._stop_requested = True
                cue._go_generation = getattr(cue, "_go_generation", 0) + 1
                cue._go_epoch = self._chain_epoch
                cue._playing = False
            # 869feynrj D10: every selfgate player that may follow gets
            # /cancelstart (kind stop_of_playing: STOP never warns), playing
            # ones included, so STOP fades in ~5 ms instead of the disconnect's
            # click. Walked over the PLAYER table, not _armed_cues (S0-4): the
            # kill goes player by player. The second stop_all_cues of a STOP
            # or a load (ready_script -> disarm_all) finds the players killed
            # and may_follow cleared, and sends nothing.
            self._stop_cancel_all_locked()
            # 869feynrj §4.6: a video gate still pending (a pass the engine
            # has not revealed) is dropped here, before the reset/unload, so
            # frame 0 cannot flash between the flags and the blackout. Sent
            # once: the second stop_all_cues finds the account closed.
            for cue in list(self._armed_cues):
                self._cancel_visible_at_locked(cue)

    def _stop_cancel_all_locked(self) -> None:
        """D10's sends; the caller holds self._lock. Never raises."""
        try:
            players = PLAYER_HANDLER.live_audio_players()
        except Exception as e:
            Logger.error(f"STOP: could not list the audio players: {e}")
            return
        for cue, player, client in players:
            if not loop_mode.player_selfgate(player):
                continue
            try:
                START_GATE.cancel(cue, player, client, "stop_of_playing")
            except Exception as e:
                Logger.error(f"STOP: /cancelstart to cue {cue.id} failed: {e}")

    @staticmethod
    def _start_in_pass(cue: Cue, p) -> float | None:
        arrival = p.arrival_of(cue) if p is not None else None
        if arrival is None:
            return None
        try:
            return arrival + cue.prewait.milliseconds_exact
        except Exception:
            return arrival

    def cancel_pending_descendants(self, cue: Cue, until: Cue | None = None) -> int:
        """Cancel the cues of the target's pass a stop takes with it
        (1amfwm7jnqf D9, X1, Design §5).

        The walk is the target's pass's layout behind the target, up to
        ``until`` (the stop action's own cue: "A, Stop A, Z": Z plays), over
        the cues due AFTER the stop action's own start (a cue due at its
        instant stays, S41). A cue belongs to the walk while its ``_pass`` is
        still the target's: a remote target is no longer a blind spot (S45),
        a cue retaken in the pass is reached (S47), a disabled target is
        treated like any other (S48), and a cue a newer pass owns is left
        alone.

        Never touches a cue that has already produced output (`_revealed`):
        that one is on stage and stays there; the walk goes on past it.
        Other nodes' cues are skipped: the node that owns them runs this same
        walk (ActionCues are local everywhere). A DMX cue whose scene is
        already in the player fires (D25, today's dmxplayer).

        Returns how many cues were cancelled.
        """
        cancelled = []
        p = getattr(cue, "_pass", None)
        t_stop = None
        if until is not None:
            t_stop = self._start_in_pass(until, getattr(until, "_pass", None))
        with self._lock:
            self._chain_epoch = self._chain_epoch + 1
            epoch = self._chain_epoch
            # Mark the target too: a dispatch of it in flight must not come
            # back to life after this.
            cue._go_epoch = epoch
            # A stopped remote Auto-follow cue does not hand over: its pass
            # no longer holds the floor for it.
            self._drop_awaiting_locked(cue, p)
            layout = getattr(p, "layout", None) or []
            pos = next((k for k, (c, _) in enumerate(layout) if c is cue), None)
            behind = layout[pos + 1 :] if pos is not None else []
            previous = cue
            for node, arrival in behind:
                if getattr(previous, "post_go", None) != "go":
                    break  # a chain break is a hand-off, not a descendant
                previous = node
                if until is not None and node is until:
                    break  # D9: nothing at or after the stop action
                np = getattr(node, "_pass", None)
                if np is not p:
                    if np is not None and np.epoch < p.epoch:
                        break  # the target's pass never reached this cue
                    continue  # a newer pass owns it
                if not getattr(node, "_local", False):
                    self._drop_awaiting_locked(node, p)
                    continue
                start = arrival + node.prewait.milliseconds_exact
                if t_stop is not None and start <= t_stop:
                    continue  # due at or before the stop's own instant
                if isinstance(node, DmxCue) and getattr(node, "_scene_out", None):
                    self._dmx_scene_out_locked(node, start, "a stop does not recall it")
                    continue
                if getattr(node, "_revealed", False):
                    continue  # on stage: never cut
                node._stop_requested = True
                node._go_generation = getattr(node, "_go_generation", 0) + 1
                node._go_epoch = epoch
                node._playing = False
                # 869feynrj §4.3: its player may already follow.
                self.cancel_start_locked(node, "cancel")
                cancelled.append(node)

        # Outside the lock: a cancelled cue's thread leaves through the
        # generation guard, upstream of the usual remove_cue, so the
        # highlight is dropped here.
        for node in cancelled:
            self._end_illumination(node)
            self._steps_done_for(node, p)
        if cancelled:
            Logger.info(
                f"Stop of cue {cue.id} cancelled {len(cancelled)} scheduled "
                f"cue(s) behind it: {', '.join(str(n.id) for n in cancelled)}"
            )
        return len(cancelled)

    def cancel_child(self, cue: Cue) -> bool:
        """Cancel a CueList's child its pass set up and has not committed:
        the child disabled before its commit (Design §2, S89). It stays
        silent in that pass even if it is enabled again: a child is in no
        layout and is never retaken. From its commit on a toggle changes
        nothing (D31 c), and a child on stage is never cut (A3)."""
        with self._lock:
            # Tested in the same section that sets the flags (869feynrj S0-1).
            if (
                getattr(cue, "_revealed", False)
                or not getattr(cue, "_playing", False)
                or self._decided_locked(cue) is not None
            ):
                return False
            cue._stop_requested = True
            cue._go_generation = getattr(cue, "_go_generation", 0) + 1
            cue._playing = False
            # 869feynrj §4.3: its player may already follow.
            self.cancel_start_locked(cue, "cancel")
        self._end_illumination(cue)
        Logger.info(f"Cue {cue.id} disabled before its commit — cancelled")
        return True

    def _decided_locked(self, cue: Cue, now_ms: float | None = None) -> str | None:
        """Why a toggle can no longer change a cue's output in its pass
        (D31 c), or None. Call with self._lock held."""
        if getattr(cue, "_revealed", False):
            return "on stage"
        if getattr(cue, "_follow_committed", False) is True:
            return "committed already"
        if getattr(cue, "_visible_at_gen", None) is not None:
            return "committed already"
        if now_ms is not None:
            arrival = getattr(cue, "_dispatch_arrival_ms", None)
            if arrival is not None:
                start = arrival + cue.prewait.milliseconds_exact
                if now_ms >= start - self._follow_lead_ms():
                    return "committed already"
        return None

    def retake(self, cue: Cue, mtc: MtcListener) -> Thread | None:
        """All a toggle does to a running pass (Design §2): an audio or video
        cue with one owner that a pass holds, not decided yet, whose thread
        is not of the kind its flag now asks for (silent or not), is
        dispatched again for itself alone: same arrival, same pass,
        ``unroll=False``. go() refuses it, in its commit section, if it is
        decided by then. Returns the new thread, or None."""
        p = getattr(cue, "_pass", None)
        if p is None or not getattr(cue, "_local", False):
            return None
        if self._runs_everywhere(cue) or self._several_owners(cue):
            return None
        if (
            not getattr(cue, "_playing", False)
            and getattr(cue, "_dispatch_arrival_ms", None) is None
        ):
            return None
        if getattr(cue, "_thread_silent", None) == (not getattr(cue, "enabled", True)):
            return None
        with self._lock:
            why = self._decided_locked(cue, self._now_ms(mtc))
        if why is not None:
            return None
        return self.go(
            cue,
            mtc,
            getattr(cue, "_dispatch_arrival_ms", None),
            pass_=p,
            unroll=False,
            retake=True,
        )

    def log_toggle(self, cue: Cue, value: bool, taken) -> None:
        """The journal line of a toggle of a cue a running pass holds
        (Design §6). Never raises."""
        try:
            p = getattr(cue, "_pass", None)
            arrival = getattr(cue, "_dispatch_arrival_ms", None)
            if p is None or arrival is None or not getattr(cue, "_playing", False):
                return
            word = "enabled" if value else "disabled"
            start = arrival + cue.prewait.milliseconds_exact
            n = getattr(p, "no", p.epoch)
            if self._runs_everywhere(cue) or self._several_owners(cue):
                instant = (
                    start
                    if self._runs_everywhere(cue)
                    else self._decide_instant(cue, start)
                )
                if self._common(cue, instant) == bool(value):
                    Logger.info(
                        f"Cue {cue.id} {word}: counts in pass {n} "
                        f"(start {start:.0f} ms)"
                    )
                else:
                    limit = chain_pass.W_MS + (start - instant)
                    Logger.info(
                        f"Cue {cue.id} {word}: sent less than {limit:.0f} ms before "
                        f"its start in pass {n} ({start:.0f} ms); from the next pass"
                    )
                return
            if taken:
                if value:
                    Logger.info(
                        f"Cue {cue.id} enabled: plays in pass {n} at {start:.0f} ms"
                    )
                else:
                    Logger.info(
                        f"Cue {cue.id} disabled: silent in pass {n} "
                        f"(start {start:.0f} ms)"
                    )
                return
            with self._lock:
                why = self._decided_locked(cue)
            if why == "on stage" and not value:
                Logger.info(f"Cue {cue.id} disabled: on stage, it plays to its end")
            elif why is not None and not value:
                Logger.info(
                    f"Cue {cue.id} disabled: committed already in pass {n}; silent "
                    "from the next pass"
                )
            elif why is not None:
                Logger.info(
                    f"Cue {cue.id} enabled: silent already in pass {n}; it plays "
                    "from the next pass"
                )
        except Exception as e:
            Logger.debug(f"toggle line for {getattr(cue, 'id', cue)} not written: {e}")

    @staticmethod
    def _several_owners(cue: Cue) -> bool:
        """An audio or video cue with outputs on more than one node (cuems-
        utils MediaCue.get_all_output_names): its owners decide together."""
        if not isinstance(cue, (AudioCue, VideoCue)):
            return False
        try:
            names = cue.get_all_output_names()
        except Exception:
            return False
        try:
            nodes = {n[0] if isinstance(n, (tuple, list)) else n for n in (names or ())}
        except TypeError:
            return False
        return len(nodes) > 1

    def disarm_all(self, reason: str = "unspecified") -> None:
        """Disarms all cues.

        Epoch bump, snapshot and clearing the armed list are ONE lock
        section. Clearing the list after the loop (as this used to) wiped
        any cue a current-epoch arm published while the loop was killing
        players: loaded but not in the list, so arm() said "already armed",
        find_armed_cue() said no, and the cue was unplayable until a reload.
        """
        self.stop_all_cues()
        with self._lock:
            self._disarm_epoch = self._disarm_epoch + 1
            cues_snapshot = list(self._armed_cues)
            self._armed_cues = []
            self._armed_cues_set.clear()
        for cue in cues_snapshot:
            self.disarm(cue, reason=reason)

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

    # ---- the pass (1amfwm7jnqf, Design §1) ---------------------------------
    # Class-level default: a handler built with object.__new__ (tests) counts
    # from 0 too. The node's pass number, for the journal only.
    _pass_count = 0

    @staticmethod
    def _anchor_of(mtc: MtcListener, frozen_mtc_ms: float | None) -> float | None:
        if frozen_mtc_ms is not None:
            return float(frozen_mtc_ms)
        try:
            value = mtc.main_tc.milliseconds_exact
        except Exception:
            return None
        return float(value) if isinstance(value, (int, float)) else None

    def _mint_pass_locked(
        self, layout: list, anchor_ms: float | None, root_seq: int = 0
    ) -> chain_pass.Pass:
        """Mint one pass: a new chain epoch, written with the layout on every
        cue of it, local or not. Call with self._lock held."""
        self._chain_epoch = self._chain_epoch + 1
        if anchor_ms is None and layout:
            anchor_ms = layout[0][1]
        p = chain_pass.Pass(
            epoch=self._chain_epoch,
            anchor_ms=anchor_ms,
            layout=layout,
            root_seq=root_seq,
            mode=(
                self._advance_mode(layout[0][0]) if layout else chain_pass.SEQUENTIAL
            ),
        )
        self._pass_count = self._pass_count + 1
        p.no = self._pass_count
        p.steps = {}
        for c, _ in p.layout:
            try:
                c._pass = p
            except Exception:
                pass
        self._add_steps(p)
        self._await_remote_follows_locked(p)
        return p

    # ---- the floor's remote Auto-follow term (Design §3, model S102) --------

    def _awaiting_passes(self) -> dict:
        """epoch -> pass holding another node's Auto-follow cue whose owner has
        not announced its hand-over yet. Call with self._lock held."""
        found = self.__dict__.get("_awaiting")
        if found is None:
            found = self.__dict__.setdefault("_awaiting", {})
        return found

    def _await_remote_follows_locked(self, p) -> None:
        """A pass holding another node's audio or video Auto-follow cue: the
        hand-over it will announce may come late and start a pass that reads
        flags from its instant on, so this pass's anchor holds the floor until
        the announcement comes (S102; without it: S103). Call with self._lock
        held."""
        awaiting = {}
        for c, arrival in p.layout:
            if (
                not getattr(c, "_local", False)
                and isinstance(c, (AudioCue, VideoCue))
                and getattr(c, "post_go", None) == "go_at_end"
                and getattr(c, "_target_object", None) is not None
            ):
                awaiting[id(c)] = (c, arrival + c.prewait.milliseconds_exact)
        found = self._awaiting_passes()
        for other in list(found.values()):
            for key in [k for k in other.awaiting if k in awaiting]:
                del other.awaiting[key]  # a newer pass holds the cue now
            if not other.awaiting:
                found.pop(other.epoch, None)
        p.awaiting = awaiting
        if awaiting:
            found[p.epoch] = p

    def _drop_awaiting_locked(self, cue: Cue, p) -> None:
        awaiting = getattr(p, "awaiting", None)
        if awaiting and awaiting.pop(id(cue), None) is not None and not awaiting:
            self._awaiting_passes().pop(p.epoch, None)

    def follow_heard(self, source_id: str, instant_ms: float) -> None:
        """The relay received the hand-over of another node's Auto-follow cue
        (FollowRelay): the passes waiting for it release the floor. Never
        raises."""
        try:
            with self._lock:
                found = self._awaiting_passes()
                for p in list(found.values()):
                    for key, (c, start) in list(p.awaiting.items()):
                        if str(c.id) == str(source_id) and start <= instant_ms:
                            del p.awaiting[key]
                    if not p.awaiting:
                        found.pop(p.epoch, None)
        except Exception as e:
            Logger.error(f"follow_heard for {source_id} failed: {e}")

    # ---- the order of instants on this node (Design §5) ------------------

    def _step_order(self) -> chain_pass.StepOrder:
        order = self.__dict__.get("_steps")
        if order is None:
            order = self.__dict__.setdefault("_steps", chain_pass.StepOrder())
        return order

    def _add_steps(self, p, start_pos: int = 0) -> None:
        """The steps of a pass on this node: for each local cue more than one
        node runs, what it does and when (an ActionCue's or a fade's start; a
        DMX cue's scene and start; a CueList's setup and start; the decision
        of a cue with several owners), keyed (instant, anchor, entry,
        position, sub): the same on every node."""
        steps = getattr(p, "steps", None)
        if steps is None:
            return
        order = self._step_order()
        anchor = p.anchor_ms if p.anchor_ms is not None else 0.0
        entry = str(getattr(p.entry, "id", p.entry))
        for pos, (c, arrival) in enumerate(p.layout):
            if pos < start_pos or not getattr(c, "_local", False):
                continue
            everywhere = self._runs_everywhere(c)
            several = not everywhere and self._several_owners(c)
            if not (everywhere or several):
                continue
            try:
                start = arrival + c.prewait.milliseconds_exact
            except Exception:
                start = arrival
            mine = {}
            if isinstance(c, (DmxCue, CueList)):
                mine["setup"] = (
                    max(start - self._RUN_AHEAD_MS, anchor),
                    anchor,
                    entry,
                    pos,
                    0,
                )
            if several:
                mine["decide"] = (start - chain_pass.W_MS, anchor, entry, pos, 0)
            if everywhere:
                mine["start"] = (start, anchor, entry, pos, 1)
            for key in mine.values():
                order.add(key, str(c.id))
            steps[id(c)] = mine

    @staticmethod
    def _step_key(cue: Cue, kind: str, p=None):
        steps = getattr(p, "steps", None)
        return (steps or {}).get(id(cue), {}).get(kind)

    def _step_wait(self, cue: Cue, kind: str, go_gen: int, p=None) -> None:
        """Do this cue's ``kind`` step only when no pending step of this node
        has a smaller key (Design §5)."""
        key = self._step_key(cue, kind, p)
        if key is None:
            return
        self._step_order().wait_turn(
            key,
            name=str(cue.id),
            abort=lambda: getattr(cue, "_go_generation", 0) != go_gen
            or getattr(cue, "_stop_requested", False),
        )

    def _step_done(self, cue: Cue, kind: str, p=None) -> None:
        steps = getattr(p, "steps", None)
        if not steps:
            return
        mine = steps.get(id(cue))
        if not mine:
            return
        key = mine.pop(kind, None)
        if key is not None:
            self._step_order().done(key)

    def _steps_done_for(self, cue: Cue, p) -> None:
        """Whatever ends a cue's part in a pass releases its steps: nothing
        waits for a step that is silent, cut, held, replaced or refused."""
        steps = getattr(p, "steps", None)
        if not steps:
            return
        for key in (steps.pop(id(cue), None) or {}).values():
            self._step_order().done(key)

    def _log_pass(self, p: chain_pass.Pass) -> None:
        """``Chain pass <n> (<mode>, engine <v>) from <id>, anchor <ms> ms:
        <id> +<offset>[ off][ held][ remote], …`` (Design §6): once per pass
        and node. Never raises."""
        try:
            version = engine_version().split(" (")[0]
            anchor = p.anchor_ms if p.anchor_ms is not None else 0.0
            held = getattr(p, "held", None) or ()
            parts = []
            for c, arrival in p.layout:
                flags = ""
                if not getattr(c, "enabled", True):
                    flags += " off"
                if id(c) in held:
                    flags += " held"
                if not getattr(c, "_local", False):
                    flags += " remote"
                parts.append(f"{c.id} +{max(arrival - anchor, 0.0):.0f}{flags}")
            entry = p.entry
            Logger.info(
                f"Chain pass {p.no} ({p.mode}, engine {version}) from "
                f"{getattr(entry, 'id', entry)}, anchor {anchor:.0f} ms: "
                + ", ".join(parts)
            )
        except Exception as e:
            Logger.error(f"Chain pass line not written: {e}")

    def mint_pass(
        self, layout: list, anchor_ms: float | None = None, root_seq: int = 0
    ) -> chain_pass.Pass:
        """A pass with no local cue to dispatch on this node (every local
        cue's is minted by go()): it still has its place, its number and its
        line, the same on every node."""
        with self._lock:
            p = self._mint_pass_locked(layout, anchor_ms, root_seq)
        self._log_pass(p)
        return p

    def _live_passes(self) -> dict:
        """epoch -> [pass, threads alive]: the passes that still have a local
        cue to start or a hand-over to fire. Call with self._lock held."""
        live = self.__dict__.get("_live")
        if live is None:
            live = self.__dict__.setdefault("_live", {})
        return live

    def _live_enter_locked(self, p) -> None:
        epoch = getattr(p, "epoch", None)
        if epoch is None:
            return
        slot = self._live_passes().setdefault(epoch, [p, 0])
        slot[1] += 1

    def _live_leave(self, p) -> None:
        epoch = getattr(p, "epoch", None)
        if epoch is None:
            return
        with self._lock:
            live = self._live_passes()
            slot = live.get(epoch)
            if slot is not None:
                slot[1] -= 1
                if slot[1] <= 0:
                    del live[epoch]

    def retire_records(self, now_ms: float | None) -> int:
        """Fold the toggle records nothing on this node can still read
        (Design §3): older than the MTC minus W, than the anchor of every
        pass with a cue to start or a hand-over to fire, and than the
        instant of every relayed follow that waits. Never raises."""
        if now_ms is None:
            return 0
        try:
            floor = float(now_ms) - chain_pass.W_MS
            with self._lock:
                anchors = [
                    p.anchor_ms
                    for p, _ in self._live_passes().values()
                    if getattr(p, "anchor_ms", None) is not None
                ] + [
                    p.anchor_ms
                    for p in self._awaiting_passes().values()
                    if getattr(p, "anchor_ms", None) is not None
                ]
            if anchors:
                floor = min(floor, min(anchors))
            relay = self._follow
            if relay is not None:
                waiting = relay.pending_instants()
                if waiting:
                    floor = min(floor, min(waiting))
            return chain_pass.retire(floor)
        except Exception as e:
            Logger.error(f"Toggle records not retired: {e}")
            return 0

    def _first_entry_at(self, cue: Cue, seed_ms: float) -> bool:
        """The loop guard (Design §5): False for an automatic entry into a cue
        at an instant at which it was already entered (one number per cue);
        a loop paced only by a cue that has no body any more would go round
        for ever. Nothing on stage is stopped."""
        with self._lock:
            entered = self.__dict__.setdefault("_entered", {})
            key = id(cue)
            if entered.get(key) == round(float(seed_ms), 3):
                return False
            entered[key] = round(float(seed_ms), 3)
            return True

    @staticmethod
    def _first_local_in(layout: list) -> tuple["Cue | None", float]:
        """The first cue of a layout this node runs, enabled or not (a
        disabled one gets a silent thread, D26), with its arrival."""
        for c, arrival in layout:
            if getattr(c, "_local", False):
                return c, arrival
        return None, 0.0

    @logged
    def go(
        self,
        cue: Cue,
        mtc: MtcListener,
        frozen_mtc_ms: float = None,
        pass_: chain_pass.Pass | None = None,
        unroll: bool = True,
        require_stop_epoch: int = None,
        arm_epoch: int = None,
        commit_gate: Callable[[Cue, int], bool] | None = None,
        layout: list | None = None,
        retake: bool = False,
    ) -> Thread | None:
        """Starts a cue in a thread.

        Args:
            cue: The cue to start (this node's; enabled or not: a disabled
            cue gets a silent thread, D26).
            mtc: The MTC listener
            frozen_mtc_ms: the cue's arrival on the MTC axis (its place in
            the pass's layout); None: live MTC, read by the thread.
            pass_: None for a FRESH chain entry (operator GO, go_from) --
            go() mints the pass, with ``layout`` (default: laid out from
            ``cue`` at its arrival) and a new chain epoch, in its commit
            section, and writes it on every cue of the layout. Otherwise the
            pass this dispatch belongs to, validated against the cue's own
            high-water mark and the STOP barrier.
            unroll: False stops go_threaded from dispatching the rest of the
            chain (a retake: the chain is already unrolled).
            retake: re-dispatch of a cue its pass holds (a toggle, Design
            §2): same arrival, same pass, not refused as a duplicate.
            arm_epoch: the STOP/load epoch this dispatch belongs to (see
            arm_epoch()). None: read here. Every arm this dispatch causes
            belongs to it, and a dispatch whose epoch has moved is refused.
            commit_gate: called inside the commit section, after every other
            refusal, with the cue and the generation about to be assigned;
            False (or an exception) refuses the dispatch (a cross-node
            follow, 869fc8ytz).

        go() arms nothing (D32, Design §4): the cue's own thread arms it, or
        waits for the arm in flight, so a slow arm makes the cue late and
        never holds the caller.

        Returns:
            Thread running the cue, or None if the cue is not local to this
            node, or the dispatch was refused as stale / after a STOP.
        """
        if not getattr(cue, "_local", True):
            # Non-local: the node owning it runs it from its own layout.
            Logger.info(f"Cue {cue.id} is not local to this node, skipping execution")
            return None
        Logger.info(f"GO command received. Starting cue {cue.id}")

        if arm_epoch is None:
            arm_epoch = self._disarm_epoch
        is_continuation = pass_ is not None and not retake
        if not getattr(cue, "loaded", False) and getattr(cue, "enabled", True):
            Logger.info(
                f"Cue {cue.id} not armed yet"
                + (" at go() time" if is_continuation else "")
                + " — dispatching; its own thread arms it or waits for the arm "
                "in progress"
            )

        minted = None
        with self._lock:
            # Validate + commit atomically.
            if arm_epoch != self._disarm_epoch:
                Logger.warning(
                    f"Refusing dispatch of cue {cue.id}: a STOP or a load "
                    "arrived while it was being started"
                )
                return None
            if (
                require_stop_epoch is not None
                and self._last_stop_chain_epoch != require_stop_epoch
            ):
                Logger.warning(
                    f"Refusing dispatch of cue {cue.id}: a STOP arrived while "
                    f"it was being put back into its chain"
                )
                return None
            if pass_ is not None and pass_.epoch <= self._last_stop_chain_epoch:
                Logger.warning(
                    f"Refusing dispatch of cue {cue.id}: a STOP ended this "
                    f"chain (pass {pass_.epoch} <= stop "
                    f"{self._last_stop_chain_epoch})"
                )
                return None
            if is_continuation and getattr(cue, "_go_epoch", 0) >= pass_.epoch:
                # A newer pass already owns the cue (a loop-back racing the
                # original unroll), or this pass already dispatched it.
                if getattr(cue, "_pass", None) is not pass_:
                    self._steps_done_for(cue, pass_)
                Logger.warning(
                    f"Refusing stale/duplicate chain dispatch of cue "
                    f"{cue.id} (cue pass {getattr(cue, '_go_epoch', 0)} >= "
                    f"dispatch pass {pass_.epoch})"
                )
                return None
            if retake and (
                getattr(cue, "_pass", None) is not pass_
                or getattr(cue, "_go_epoch", 0) > pass_.epoch
                or self._decided_locked(cue) is not None
            ):
                Logger.info(f"Cue {cue.id}: not retaken, a newer pass or a stop has it")
                return None

            go_gen = getattr(cue, "_go_generation", 0) + 1
            if commit_gate is not None:
                try:
                    allowed = commit_gate(cue, go_gen)
                except Exception as e:
                    Logger.error(f"Commit gate for cue {cue.id} failed: {e}")
                    allowed = False
                if not allowed:
                    Logger.info(
                        f"Refusing dispatch of cue {cue.id}: its cross-node "
                        "follow was cancelled or replaced"
                    )
                    return None
            if pass_ is None:
                # Fresh entry: claim the next epoch and mint the pass. Greater
                # than every recorded stop and every cue mark at this instant.
                if layout is None:
                    anchor = self._anchor_of(mtc, frozen_mtc_ms)
                    layout = chain_pass.layout(
                        cue, anchor if anchor is not None else 0.0
                    )
                    anchor_ms = anchor
                else:
                    anchor_ms = layout[0][1] if layout else frozen_mtc_ms
                root = chain_pass.current_root()
                pass_ = minted = self._mint_pass_locked(layout, anchor_ms, root)
            # Only past every refusal: a dispatch that is refused must not
            # cancel the follow of the pass still playing.
            self._take_follow_on_restart_locked(cue)
            cue._superseded_playing = bool(
                getattr(cue, "_revealed", False) and getattr(cue, "_playing", False)
            )
            if not getattr(cue, "_revealed", False):
                # §4.3 row 1: the pass this dispatch supersedes produced no
                # output, but its player may already follow it.
                self.cancel_start_locked(cue, "cancel")
            elif isinstance(cue, DmxCue) and getattr(cue, "_scene_out", None):
                old_arrival = getattr(cue, "_dispatch_arrival_ms", None)
                if old_arrival is not None:
                    self._dmx_scene_out_locked(
                        cue,
                        old_arrival + cue.prewait.milliseconds_exact,
                        "a newer pass replaces it",
                    )

            cue._go_epoch = pass_.epoch
            cue._pass = pass_
            cue._pass_seeded = bool(getattr(_DISPATCH, "seeded", False))
            # Recorded here, not in the spawned thread: a retake re-dispatches
            # at this arrival. None (an entry with no seed) is derived from
            # live MTC by the thread.
            cue._dispatch_arrival_ms = frozen_mtc_ms
            cue._stop_requested = False
            cue._go_generation = go_gen
            cue._revealed = False
            cue._revealed_at = None
            cue._follow_committed = False
            cue._scene_withheld = False
            cue._setup_skipped = False
            # Its thread's kind, decided here (Design §2): a retake compares
            # it with the flag.
            cue._thread_silent = self._silent_at_dispatch(cue)
            cue._playing = True
            cue._ever_played = True
            self._live_enter_locked(pass_)

        if minted is not None:
            self._log_pass(minted)
            # A play / fade_in reaches its deciding point here (Design §5).
            chain_pass.release_step()

        thread = Thread(
            name=f"GO:{cue.__class__.__name__}:{cue.id}",
            target=self.go_threaded,
            args=[cue, mtc, frozen_mtc_ms, go_gen, pass_, unroll],
            kwargs={"arm_epoch": arm_epoch},
            daemon=True,
        )
        thread.start()

        # Duration-aware lookahead, synchronous on the caller's thread: only
        # for a fresh entry (a continuation's caller is the previous cue's
        # thread, a retake's the command thread).
        if minted is not None and unroll:
            self._arm_ahead(cue, arm_epoch=arm_epoch)
        return thread

    def go_from(
        self,
        start_cue: Cue,
        mtc: MtcListener,
        seed_ms: float = None,
        arm_epoch: int = None,
        require_stop_epoch: int = None,
        commit_gate: Callable[[Cue, int], bool] | None = None,
        why: str | None = None,
    ) -> Thread | None:
        """Enter a post_go='go' chain at start_cue (inclusive), the pass
        anchored at seed_ms (an ActionCue play / fade_in at its start, an Auto
        follow at body end + postwait, a relayed follow): the pass is laid
        out from the script alone (chain_pass.layout), the same on every
        node, and THIS node's first local cue of it is dispatched at its
        arrival. With no local cue the pass is still minted and logged.
        Returns the Thread, or None.

        arm_epoch / require_stop_epoch / commit_gate are passed to go() when
        set: a cross-node follow dispatches on another thread than the one
        that received it, and a STOP or a cancel in between must win.
        """
        guards = {
            k: v
            for k, v in (
                ("arm_epoch", arm_epoch),
                ("require_stop_epoch", require_stop_epoch),
                ("commit_gate", commit_gate),
            )
            if v is not None
        }
        if seed_ms is None:
            seed_ms = mtc.main_tc.milliseconds_exact
        why = why or chain_pass.current_why()
        if why not in (None, "go") and not self._first_entry_at(start_cue, seed_ms):
            Logger.error(
                f"zero-length loop: {why} into {start_cue.id} at {seed_ms:.0f} ms "
                "a second time, refused"
            )
            chain_pass.release_step()
            return None
        if why == "follow":
            # A hand-over enters its pass after everything this node still
            # has to do that is due at or before its instant (Design §5).
            self._step_order().wait_turn(
                (float(seed_ms), float("inf")), name=f"follow into {start_cue.id}"
            )
        lay = chain_pass.layout(start_cue, seed_ms, self._advance_mode(start_cue))
        cue, arrival = self._first_local_in(lay)
        if cue is None:
            self.mint_pass(lay, seed_ms, chain_pass.current_root())
            chain_pass.release_step()
            return None
        # A seeded dispatch (869feynrj §4.5e), never led (S0-13: L per hop
        # would drift every go_at_end chain by L per cue).
        with _dispatch_tag(True):
            return self.go(cue, mtc, arrival, layout=lay, **guards)

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
        self, cue: Cue, pass_: chain_pass.Pass | None
    ) -> tuple["Cue | None", float]:
        """The next cue of ``pass_``'s layout after ``cue`` that THIS node
        runs, enabled or not (a disabled one keeps its place and its waits
        and gets a silent thread, D26), with its arrival in the layout. The
        arrivals are the layout's: nothing is added on the way. (None, 0.0)
        at the end of the layout, or when ``cue`` is not in it."""
        if pass_ is None:
            return None, 0.0
        found = False
        for c, arrival in pass_.layout:
            if found and getattr(c, "_local", False):
                return c, arrival
            if c is cue:
                found = True
        return None, 0.0

    def go_threaded(
        self,
        cue: Cue,
        mtc: MtcListener,
        frozen_mtc_ms: float = None,
        go_gen: int = 0,
        pass_: chain_pass.Pass | None = None,
        unroll: bool = True,
        arm_epoch: int = None,
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
            pass_: the pass this cue belongs to (chain_pass.Pass), carried
                    unchanged into the continuation dispatch so the whole
                    chain shares it; its layout gives every arrival.
            unroll: False suppresses the continuation dispatch (enable-rejoin
                    of a chain that is already unrolled).
            arm_epoch: the STOP/load epoch of the go() that dispatched this
                    cue; every arm this thread makes (its own cue, the
                    go_at_end lookahead) and the continuation it dispatches
                    belong to it, so none of them survives a STOP.
        """
        follow = _FollowOut()
        try:
            # The pass context (run_cue.installed_pass): the readers on this
            # thread compare against this pass, not the cue's attributes.
            with installed_pass(go_gen, cue):
                self._run_cue_pass(
                    cue,
                    mtc,
                    frozen_mtc_ms,
                    go_gen,
                    pass_,
                    unroll,
                    arm_epoch,
                    follow,
                )
        except Exception:
            follow.error = True
            raise
        finally:
            self._leave_follow(cue, follow, arm_epoch)
            self._steps_done_for(cue, pass_)
            self._live_leave(pass_)
            self.retire_records(self._now_ms(mtc) if pass_ is not None else None)

    def _run_cue_pass(
        self,
        cue: Cue,
        mtc: MtcListener,
        frozen_mtc_ms: float,
        go_gen: int,
        pass_: chain_pass.Pass | None,
        unroll: bool,
        arm_epoch: int | None,
        follow: _FollowOut,
    ):
        """The body of go_threaded; `follow` records what this pass did about
        its cross-node Auto follow, for go_threaded's exit (869fc8ytz)."""
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
        # The arrival is the cue's place in its pass's layout (1amfwm7jnqf,
        # "en serie": the waits of the cues before it count).
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
        holds = cue.post_go == "go" and not self._chain_continues(cue)
        if (
            isinstance(cue, ActionCue)
            and getattr(cue, "action_type", None) == "stop_project"
        ):
            cue._held_back = holds
        if unroll and holds:
            Logger.info(
                f"stop_project cue {cue.id}: chain break, the cues after it "
                "are not dispatched"
            )
            self._release_held_steps(cue, pass_)
        elif (
            unroll
            and pass_ is not None
            and cue.post_go == "go"
            and not cue._stop_requested
            and getattr(cue, "_go_generation", 0) == go_gen
        ):
            try:
                # THIS node's next cue of the pass's layout, enabled or not,
                # at its own arrival (Design §1).
                next_cue, next_arrival = self._next_local_fire(cue, pass_)
                if next_cue is not None:
                    Logger.info(
                        f"Unrolling post_go chain: dispatching {next_cue.id} "
                        f"at {next_arrival:.0f} ms"
                    )
                    # A chain cue's pass is seeded iff its head's is (§4.5e).
                    with _dispatch_tag(getattr(cue, "_pass_seeded", False) is True):
                        post_go_thread = self.go(
                            next_cue,
                            mtc,
                            next_arrival,
                            pass_=pass_,
                            arm_epoch=arm_epoch,
                        )
            except Exception as e:
                # The chain is downstream work; losing it must not cost THIS
                # cue its own reveal.
                Logger.error(f"Chain dispatch from cue {cue.id} failed: {e}")

        # A silent thread (Design §2): an audio or video cue disabled at its
        # dispatch. It keeps its place, its waits and its post_go; it sets
        # nothing up, lights nothing, reveals nothing, and has no body.
        silent = getattr(cue, "_thread_silent", None)
        if silent is None or getattr(cue, "_go_generation", 0) != go_gen:
            silent = self._silent_at_dispatch(cue)
        # Its arm failed (D32): silent on this node, but it keeps its body
        # and its hand-over: the cue is enabled.
        failed_arm = False
        if cue._local and silent:
            cue._end_mtc = None
            if self._follows_out(cue):
                # Its hand-over, start + postwait, told at its dispatch, so
                # the other nodes pre-arm and wait as for any follow.
                self._announce_follow(cue, go_gen, start_ms, follow)
            if self._wait_mtc(cue, mtc, start_ms, go_gen) != "stopped":
                self._log_silent(cue, mtc)
        elif cue._local:
            # A cue arms on its own thread, overlapping its own prewait: a
            # fresh entry's too (D32, Design §4), so a slow arm makes it late
            # and never holds the GO or the other cues of the pass.
            if not getattr(cue, "loaded", False):
                # 869fbyjzx: an arm in flight is waited for, not a fallback.
                in_flight = self.describe_arm_in_flight(cue)
                if in_flight is not None:
                    Logger.info(
                        f"Cue {cue.id} is still being armed ({in_flight}) at "
                        f"dispatch — waiting for the arm in progress"
                    )
                else:
                    Logger.warning(
                        f"Cue {cue.id} not loaded at dispatch — no arm in "
                        f"flight; arming on its own thread before its slot. "
                        f"Re-arming as fallback."
                    )
                wait_report = {}
                self.arm(cue, init=True, epoch=arm_epoch, wait_report=wait_report)
                self._log_arm_wait(cue, "dispatch", in_flight, wait_report)
                if arm_epoch is not None and arm_epoch != self._disarm_epoch:
                    # arm() refused or abandoned the arm: a STOP or a load
                    # landed since this cue was dispatched.
                    Logger.info(
                        f"Cue {cue.id} was dispatched before a STOP or a "
                        "load; it will not play"
                    )
                    return
                if getattr(cue, "_go_generation", 0) != go_gen or getattr(
                    cue, "_stop_requested", False
                ):
                    return
                if not getattr(cue, "loaded", False) and getattr(cue, "enabled", True):
                    # The rest of the chain went out at entry, so this failure
                    # costs this cue only, on this node (D32, S100).
                    failed_arm = True
                    Logger.error(
                        f"{cue.id} could not be armed; it does not play in pass "
                        f"{getattr(pass_, 'no', '?')}"
                    )
                else:
                    # The check above ran before the arm; an arm longer than
                    # this cue's runway makes it late, and that must not be
                    # silent.
                    self._warn_if_late(cue, mtc, start_ms)
            elif arm_epoch is not None and arm_epoch != self._disarm_epoch:
                # Loaded, but not for this dispatch: the STOP's own re-arm
                # loaded it for the NEXT run while this thread was on its way.
                Logger.info(
                    f"Cue {cue.id} was dispatched before a STOP or a load; "
                    "it will not play"
                )
                return

        if cue._local and failed_arm:
            silent = True
            # Nothing of this pass waits for a cue that does nothing here.
            self._steps_done_for(cue, pass_)
            body = self._body_ms(cue)
            cue._end_mtc = CTimecode(start_seconds=max(start_ms + body, 0.0) / 1000.0)
            if self._wait_mtc(cue, mtc, start_ms, go_gen) != "stopped":
                self._log_silent(cue, mtc)
            if self._follows_out(cue):
                self._announce_follow(cue, go_gen, start_ms, follow)
        elif cue._local and not silent:
            # Setup, illumination and the follow commit, in due-time order
            # (869feynrj §4.2).
            phase, follow_target = self._run_timeline(
                cue, mtc, arrival_ms, start_ms, go_gen, pass_=pass_
            )
            if phase == "failed":
                return
            if phase == "silent":
                # Several owners, decided off: silent on every owner, each
                # announcing the same hand-over, start + postwait.
                silent = True
                cue._end_mtc = None
                if self._follows_out(cue):
                    self._announce_follow(cue, go_gen, start_ms, follow)
                if self._wait_mtc(cue, mtc, start_ms, go_gen) != "stopped":
                    self._log_silent(cue, mtc)
                phase = "stopped"

            # MTC-gated reveal: wait until live MTC reaches start_ms, then reveal
            # (video /visible; audio /mtcfollow, or nothing more for a
            # follow-committed selfgate player; action EXECUTE; dmx no-op).
            # Skipped when the pass was stopped before its setup.
            # A CueList whose child committed its follow reveals at the
            # child's start, not at once (review 4 m9).
            gate = "stopped"
            if phase == "ready":
                if isinstance(cue, CueList) and follow_target is not None:
                    gate = self._wait_mtc(
                        cue, mtc, follow_target._start_mtc.milliseconds_exact, go_gen
                    )
                else:
                    gate = self._reveal_wait(cue, mtc, go_gen)
            if phase == "ready" and getattr(cue, "_scene_withheld", False):
                gate = self._wait_mtc(cue, mtc, start_ms, go_gen)
            if gate != "stopped":
                # What more than one node does happens in the order of its
                # instants on every node (Design §5).
                self._step_wait(cue, "start", go_gen, pass_)
                if getattr(cue, "_go_generation", 0) != go_gen or getattr(
                    cue, "_stop_requested", False
                ):
                    gate = "stopped"
            plays = gate != "stopped" and self._plays_at_start(cue, start_ms)
            if gate != "stopped" and not plays:
                # A cue every node runs, off as every node sees it at its
                # start: no output in this pass, and no body (D27 point 2).
                silent = True
                cue._end_mtc = None
                self._log_silent(cue, mtc)
                if isinstance(cue, DmxCue):
                    with self._lock:
                        self._dmx_scene_out_locked(cue, start_ms, "silenced")
                gate = "silent"
            elif plays and getattr(cue, "_scene_withheld", False):
                # Enabled since its scene was due: the scene goes late, now.
                cue._scene_withheld = False
                guard = _SetupGuard(self._lock, cue, go_gen)
                try:
                    with installed_guard(guard):
                        run_cue(cue, mtc, start_ms)
                    Logger.info(
                        f"DMX scene sent to local player for cue {cue.id} (late, "
                        "at its start)"
                    )
                except Exception as e:
                    Logger.error(f"run_cue failed for DmxCue {cue.id}: {e}")
            if gate not in ("stopped", "silent"):
                skip_child = None
                # Commit under the same lock the stop walk takes, so a cancel
                # landing inside the 20ms poll gap cannot leak a reveal past it.
                with self._lock:
                    do_reveal = not cue._stop_requested and (
                        getattr(cue, "_go_generation", 0) == go_gen
                    )
                    if do_reveal:
                        cue._revealed = True
                        # Same section: a cross-node follow cancel deciding
                        # "not started yet" must never see _revealed set
                        # without its stamp.
                        cue._revealed_at = monotonic()
                        child = self._owned_cuelist_child(cue, go_gen)
                        if child is not None and not self._child_current_locked(
                            cue, child, go_gen, at_reveal=True
                        ):
                            # Review C2: the child was disabled, stopped,
                            # paused or GO'd on its own since the setup; the
                            # reveal must neither reach it nor fall through to
                            # the next enabled child, which was never set up.
                            skip_child = child
                            child = None
                        if child is not None:
                            # S0-21: its child is on stage from here on.
                            child._revealed = True
                            child._revealed_at = cue._revealed_at
                        if isinstance(follow_target, VideoCue):
                            # 869feynrj §4.6: on stage from here on.
                            self._close_visible_at(
                                follow_target,
                                cue if cue is not follow_target else None,
                            )
                        # Committed or legacy reveal, decided here under the
                        # lock and handed to reveal_audioCue (review fix 7).
                        ctx = current_pass()
                        if ctx is not None:
                            ctx.follow_committed = (
                                follow_target is not None
                                and getattr(follow_target, "_follow_committed", False)
                                is True
                                and getattr(cue, "_follow_gen", None) == go_gen
                            )
                if do_reveal:
                    cue._scene_out = None  # a DMX scene fires now, as sent
                    revealed_at = cue._revealed_at
                    follow.revealed = True
                    self._log_revealed(cue, mtc, start_ms, child)
                    if skip_child is None:
                        with chain_pass.entry(
                            root=getattr(pass_, "root_seq", 0) or 0,
                            release=partial(self._step_done, cue, "start", pass_),
                        ):
                            reveal_cue(cue, mtc, start_ms)
                    else:
                        Logger.info(
                            f"CueList {cue.id}: child {skip_child.id} was "
                            "disabled, stopped or replaced since the setup; "
                            "not revealed"
                        )
                    silent_child = self._silent_picked_child(cue, child, skip_child)
                    if silent_child is not None:
                        self._log_silent(silent_child, mtc)
                    if isinstance(follow_target, AudioCue):
                        self._expect_start(cue, follow_target)
                    armed_at = getattr(cue, "_armed_at", None)
                    if armed_at is not None:
                        Logger.info(
                            f"Cue {cue.id} started {revealed_at - armed_at:.3f} s "
                            "after it was armed"
                        )

        if pass_ is not None:
            self._step_done(cue, "start", pass_)

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
        # Cross-node Auto follow (869fc8ytz): tell the other nodes the follow
        # instant as soon as it is final -- now, or at the start of the last
        # loop -- and before the lookahead below, which can take seconds.
        on_last_loop = None
        if follow.revealed and self._follows_out(cue):
            if cue.loop == 1:
                self._announce_follow(cue, go_gen, start_ms, follow)
            elif cue.loop > 1:
                on_last_loop = partial(
                    self._announce_follow, cue, go_gen, start_ms, follow
                )

        if cue.post_go == "go_at_end" and not silent:
            self._arm_ahead(cue, arm_epoch=arm_epoch)

        if failed_arm:
            # No player, but the cue keeps its body (D32): its end and its
            # hand-over stay where they were.
            self._wait_mtc(cue, mtc, cue._end_mtc.milliseconds_exact, go_gen)
        elif not silent:
            Logger.info(f"Going to loop for {cue.__class__.__name__}:{cue.id}")
            if on_last_loop is None:
                loop_cue(cue, mtc)
            else:
                loop_cue(cue, mtc, on_last_loop=on_last_loop)

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
        fire_seed_ms = self._follow_instant_ms(cue, start_ms)

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
            # Decided and sent under the lock, against this pass (869feynrj
            # §4.6): a /visible 0 drops a pending visible_at gate in the VC,
            # so a re-GO landing since the check above must not be blanked.
            if not silent:
                with self._lock:
                    if getattr(cue, "_go_generation", 0) == go_gen:
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
        if cue.post_go == "go_at_end" and not self._chain_continues(cue):
            Logger.info(
                f"stop_project cue {cue.id}: chain break, its go_at_end follow "
                "is not fired"
            )
        elif (
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
            # The hand-over waits for the steps due by its instant; none of
            # them is this cue's own.
            self._steps_done_for(cue, pass_)
            if self._follow_fired(cue, follow, fire_seed_ms, go_gen):
                with _root_seq(pass_):
                    go_at_end_thread = self.go_from(
                        cue._target_object, mtc, fire_seed_ms, why="follow"
                    )
        elif (
            cue.post_go == "go_at_end"
            and cue._target_object
            and not cue._stop_requested
        ):
            follow.yielded = True
            Logger.info(
                f"go_at_end fire for {cue.id} yielded: "
                "target already started by a newer GO"
            )

        self._wait_wrap_player_end(cue, mtc, go_gen)
        self._end_cuelist_child(cue, mtc, go_gen)
        self.disarm(cue, reason="cue_end")

        if cue.post_go == "go_at_end" and go_at_end_thread:
            self.wait_for_cue(go_at_end_thread)

        if cue.post_go == "go" and cue._target_object and not cue._stop_requested:
            if post_go_thread:
                self.wait_for_cue(post_go_thread)

    # ---- silent threads and the journal (1amfwm7jnqf, Design §2, §6) ------

    @staticmethod
    def _runs_everywhere(cue: Cue) -> bool:
        """A cue every node runs (ActionCue, FadeCue, DmxCue, CueList:
        cuems-utils Cue.localize_cue): it decides its output at its own
        instants, not at its dispatch."""
        return isinstance(cue, (ActionCue, DmxCue, CueList))

    def _silent_at_dispatch(self, cue: Cue) -> bool:
        """An audio or video cue with one owner whose flag is off when its
        thread starts: its thread is a silent one (Design §2). A cue with
        several owners decides at start - W."""
        return (
            getattr(cue, "_local", False)
            and not self._runs_everywhere(cue)
            and not getattr(cue, "enabled", True)
            and not self._several_owners(cue)
        )

    def _plays_at_start(self, cue: Cue, start_ms: float) -> bool:
        """Whether a cue every node runs has output at its start, from the
        flag as every node sees it there (D31 d; an audio or video cue was
        decided before)."""
        if not self._runs_everywhere(cue):
            return True
        if isinstance(cue, CueList) and hasattr(cue, "_list_on"):
            return bool(cue._list_on)  # decided at its setup (Design §2)
        return self._common(cue, start_ms)

    def _decide_instant(self, cue: Cue, start_ms: float) -> float:
        """When the owners of a cue with several decide: start - W, or the
        pass's anchor if that is later."""
        anchor = getattr(getattr(cue, "_pass", None), "anchor_ms", None)
        due = start_ms - chain_pass.W_MS
        return max(due, anchor) if anchor is not None else due

    @staticmethod
    def _common(cue: Cue, instant_ms: float) -> bool:
        """The flag as every node sees it at ``instant_ms``, for the pass the
        cue is in (chain_pass.common_enabled)."""
        root = getattr(getattr(cue, "_pass", None), "root_seq", 0) or 0
        return chain_pass.common_enabled(cue, instant_ms, root)

    def _scene_instant(self, cue: Cue, start_ms: float) -> float:
        """When a DMX cue's scene is due: _RUN_AHEAD_MS before its start, or
        its pass's anchor if that is later."""
        anchor = getattr(getattr(cue, "_pass", None), "anchor_ms", None)
        due = start_ms - self._RUN_AHEAD_MS
        return max(due, anchor) if anchor is not None else due

    def _dmx_scene_out_locked(self, cue: Cue, start_ms: float, why: str) -> bool:
        """D25: a DMX cue silenced, stopped or replaced whose scene is already
        in the player. A player that can cancel a scene gets the cancel;
        today's dmxplayer cannot (ClickUp 1amfwm7jwnf): the scene fires at
        the start, with a WARNING. Returns True when it fires. Call with
        self._lock held."""
        if not isinstance(cue, DmxCue) or getattr(cue, "_scene_out", None) is None:
            return False
        cue._scene_out = None
        try:
            capable = bool(PLAYER_HANDLER.dmx_can_cancel())
        except Exception:
            capable = False
        if capable:
            try:
                PLAYER_HANDLER.cancel_dmx_scene(cue)
            except Exception as e:
                Logger.error(f"{cue.id}: DMX scene cancel failed: {e}")
            Logger.info(f"{cue.id}: DMX scene cancelled in the player ({why})")
            return False
        Logger.warning(
            f"{cue.id}: DMX scene already sent; it fires at {start_ms:.0f} ms ({why})"
        )
        return True

    @staticmethod
    def _silent_picked_child(cue: Cue, revealed: Cue | None, skipped: Cue | None):
        """The local child a CueList's pass picked and does not reveal (off
        on this node at the setup, or cancelled before its commit)."""
        if not isinstance(cue, CueList) or revealed is not None:
            return None
        if skipped is not None:
            return skipped
        child = getattr(cue, "_marked_child", None)
        if child is not None and getattr(child, "_local", False):
            return child
        return None

    @staticmethod
    def _body_ms(cue: Cue) -> float:
        """The cue's body (media length or authored time), in ms."""
        try:
            return max(
                CueHandler._effective_duration_ms(cue)
                - cue.prewait.milliseconds_exact
                - cue.postwait.milliseconds_exact,
                0.0,
            )
        except Exception:
            return 0.0

    @staticmethod
    def _now_ms(mtc: MtcListener) -> float:
        try:
            return float(mtc.main_tc.milliseconds_exact)
        except Exception:
            return 0.0

    def _log_silent(self, cue: Cue, mtc: MtcListener) -> None:
        Logger.info(f"Cue {cue.id} passed silent at mtc {self._now_ms(mtc):.0f} ms")

    def _log_revealed(
        self, cue: Cue, mtc: MtcListener, start_ms: float, child: Cue | None = None
    ) -> None:
        now = self._now_ms(mtc)
        Logger.info(
            f"Cue {cue.id} revealed at mtc {now:.0f} ms (start {start_ms:.0f} ms)"
        )
        if child is not None:
            Logger.info(
                f"Cue {child.id} revealed at mtc {now:.0f} ms (start {start_ms:.0f} ms)"
            )

    def _mark_cuelist_child(
        self, cue: Cue, go_gen: int, start_ms: float | None = None
    ) -> None:
        """A CueList's setup (1amfwm7jnqf Design §2): its own flag and which
        child is the first enabled one, read ONCE per pass from the flag as
        every node sees them at the setup's instant; the child is recorded
        in ``_marked_child``, local or not, and commit, reveal and end take
        it from there (S85, S87). A local child off on this node at the
        setup is not set up and is silent in this pass.

        A CueList's child bypasses go(), so its pass marks it here: playing
        (the disable guard reads it) and not yet revealed (a cancel still
        reaches a pending child); the parent's reveal sets the child's
        _revealed, and the parent's pass clears both at the child's end
        (_end_cuelist_child). Also cleared, like any cue's, by disarm() and
        STOP."""
        instant = (
            self._scene_instant(cue, start_ms)
            if start_ms is not None
            else self._now_ms(None)
        )
        on = self._common(cue, instant) if start_ms is not None else cue.enabled
        child = None
        if on:
            child = next(
                (
                    c
                    for c in (getattr(cue, "contents", None) or [])
                    if (self._common(c, instant) if start_ms is not None else c.enabled)
                ),
                None,
            )
        with self._lock:
            if getattr(cue, "_stop_requested", False) or (
                getattr(cue, "_go_generation", 0) != go_gen
            ):
                return
            cue._list_on = bool(on)
            cue._marked_child = child
            cue._marked_child_set_up = True
            if child is None or not getattr(child, "_local", False):
                return
            if not getattr(child, "enabled", True):
                # Off on its owner already: not set up, silent in this pass.
                cue._marked_child_set_up = False
                return
            child._playing = True
            child._revealed = False
            child._ever_played = True
            child._cuelist_pass = (id(cue), go_gen)
            # Review C2: this pass takes the child over, as go() does for a
            # top-level pass: a stop flag left by an earlier pass of its own
            # is cleared, and its generation recorded, so a disable, stop,
            # pause or own GO from here on is seen by _child_current_locked.
            child._stop_requested = False
            child._follow_committed = False
            child._cuelist_child_gen = getattr(child, "_go_generation", 0)

    def _child_current_locked(
        self, cue: Cue, target: Cue, go_gen: int, at_reveal: bool = False
    ) -> bool:
        """Review C2: may this pass of ``cue`` still commit to / reveal
        ``target``? Always for the cue's own pass. For a CueList's child: it
        is the child this pass marked at its setup, still enabled, not
        stopped or paused since (``_stop_requested``: the setup cleared it),
        and not taken by a pass of its own (its generation is the one the
        setup recorded; a disable's cancel_parked bumps it too). The parent's
        own flags are the caller's check. Call with self._lock held."""
        if cue is target:
            return True
        if self._owned_cuelist_child(cue, go_gen) is not target:
            return False
        # Its flag is read at the commit, not again at the reveal (Design §2):
        # from its commit on a toggle changes nothing.
        if not at_reveal and getattr(target, "enabled", True) is False:
            return False
        return not getattr(target, "_stop_requested", False) and getattr(
            target, "_go_generation", 0
        ) == getattr(target, "_cuelist_child_gen", None)

    @staticmethod
    def _owned_cuelist_child(cue: Cue, go_gen: int) -> Cue | None:
        """The child this pass of a CueList marked, while the mark is still
        this pass's (a newer pass of the CueList re-marks it). Call with
        self._lock held."""
        if not isinstance(cue, CueList):
            return None
        child = getattr(cue, "_marked_child", None)
        if child is None or getattr(child, "_cuelist_pass", None) != (id(cue), go_gen):
            return None
        return child

    def _end_cuelist_child(self, cue: Cue, mtc: MtcListener, go_gen: int) -> None:
        """The end of a CueList child's pass (S0-21). loop_cueList is a no-op,
        so the parent's thread reaches its end right after the reveal while
        the child still plays: it waits here for the child's body end
        (_end_mtc, set at its setup), then clears the child's playing and
        revealed marks -- only while this pass still owns them (a re-GO of
        the CueList re-marks the child and its own end clears it). A STOP
        clears them itself; a pause (its /cancelstart already silenced the
        child) ends the wait at once. Without this a later disable never
        disarmed the child: its player and JACK client stayed until STOP,
        and a cross-node follow read it as still on stage."""
        if not isinstance(cue, CueList):
            return
        with self._lock:
            child = self._owned_cuelist_child(cue, go_gen)
        if child is None:
            return
        start = getattr(child, "_start_mtc", None)
        end = getattr(child, "_end_mtc", None)
        try:
            start_ms = start.milliseconds_exact if start is not None else None
            end_ms = end.milliseconds_exact if end is not None else None
        except AttributeError:
            start_ms = end_ms = None
        if end_ms is not None and (start_ms is None or end_ms > start_ms):
            self._wait_mtc(cue, mtc, end_ms, go_gen)
        with self._lock:
            if getattr(cue, "_go_generation", 0) != go_gen:
                return
            if self._owned_cuelist_child(cue, go_gen) is not child:
                return
            child._playing = False
            child._revealed = False
            child._cuelist_pass = None

    def _expect_start(self, cue: Cue, target: Cue) -> None:
        """At the reveal of a follow-committed pass (869feynrj §8): the
        player's START line is due by start + one period + latency; the
        start gate re-sends /mtcfollow 1 once if it never comes (a lost
        follow). Not when this pass superseded one still on stage: a
        /mtcfollow 1 in PLAY prints no START."""
        if getattr(cue, "_superseded_playing", False):
            return
        try:
            START_GATE.expect_start(
                target,
                PLAYER_HANDLER.audio_player(target),
                getattr(target, "_osc", None),
            )
        except Exception as e:
            Logger.warning(f"Audio cue {target.id}: START check not armed: {e}")

    # ---------------------------
    # Cross-node Auto follow (869fc8ytz)
    # ---------------------------

    @staticmethod
    def _follow_instant_ms(cue: Cue, start_ms: float) -> float:
        """When an Auto follow fires its target: the body's end on the MTC
        timeline plus the postwait. The one expression both the fire and the
        announcement use. Fallbacks for cues that never set _end_mtc (plain
        ActionCue body=0; aborted A/V setup; CueList) and a stale _end_mtc
        left by a previous GO of this object. (FadeCue DOES set a real
        _end_mtc via _handle_fade_action -- used as-is.)"""
        end_attr = getattr(cue, "_end_mtc", None)
        base_end_ms = end_attr.milliseconds_exact if end_attr is not None else start_ms
        if base_end_ms < start_ms:
            base_end_ms = start_ms  # stale from a previous run
        return base_end_ms + cue.postwait.milliseconds_exact

    @staticmethod
    def _chain_continues(cue: Cue) -> bool:
        """False for a stop_project ActionCue that is going to execute
        (ClickUp 869fhjdq5; 1amfwm7jnqf D28): the authored end of the show
        holds back the cues behind it in its pass on every node, so no cue
        can start in the milliseconds before the controller's STOP lands. A
        disabled one, as every node sees it at its start, holds nothing back
        (D31 d): the chain goes on (S15, S16). Re-read when a toggle of it
        arrives (stop_project_toggled)."""
        if not (
            isinstance(cue, ActionCue)
            and getattr(cue, "action_type", None) == "stop_project"
        ):
            return True
        arrival = getattr(cue, "_dispatch_arrival_ms", None)
        if arrival is None:
            return not getattr(cue, "enabled", True)
        return not CueHandler._common(cue, arrival + cue.prewait.milliseconds_exact)

    def _release_held_steps(self, cue: Cue, p) -> None:
        """The cues behind a stop_project that holds them back do nothing in
        this pass: nothing waits for their steps."""
        layout = getattr(p, "layout", None) or []
        pos = next((k for k, (c, _) in enumerate(layout) if c is cue), None)
        if pos is None:
            return
        for c, _ in layout[pos + 1 :]:
            self._steps_done_for(c, p)

    def stop_project_toggled(self, cue: Cue, mtc: MtcListener) -> None:
        """A toggle of a stop_project cue its pass holds, before its start
        (Design §2): disabled, it hands on to the cues behind it at their
        places (S16); enabled, it cancels them (the stop walk from itself,
        S63)."""
        p = getattr(cue, "_pass", None)
        if p is None or getattr(cue, "_revealed", False):
            return
        if not getattr(cue, "_playing", False):
            return
        held = getattr(cue, "_held_back", None)
        if held is None:
            return
        continues = self._chain_continues(cue)
        if continues and held:
            cue._held_back = False
            nxt, arrival = self._next_local_fire(cue, p)
            Logger.info(
                f"stop_project cue {cue.id} disabled: the cues behind it play at "
                "their places"
            )
            pos = p.position_of(cue)
            if pos is not None:
                self._add_steps(p, start_pos=pos + 1)
            if nxt is not None:
                self.go(nxt, mtc, arrival, pass_=p)
        elif not continues and not held:
            cue._held_back = True
            Logger.info(
                f"stop_project cue {cue.id} enabled: the cues behind it are held back"
            )
            self.cancel_pending_descendants(cue)

    @staticmethod
    def _follows_out(cue: Cue) -> bool:
        """An Auto follow whose source plays only where it has an output.

        ActionCue, FadeCue, CueList and DmxCue are local on every node, so
        every node fires their follow itself; only AudioCue and VideoCue need
        the other nodes told."""
        return (
            isinstance(cue, (AudioCue, VideoCue))
            and getattr(cue, "_local", False)
            and getattr(cue, "post_go", None) == "go_at_end"
            and getattr(cue, "_target_object", None) is not None
        )

    def _announce_follow(
        self, cue: Cue, go_gen: int, start_ms: float, follow: _FollowOut
    ) -> None:
        """Announce this pass's follow instant to the other nodes, once.

        Decided, recorded and queued in one lock section, so the messages
        leave in the order the decisions were taken; only the pass that still
        owns the cue announces. Never raises: it runs on the cue's thread."""
        relay = self._follow
        if relay is None or follow.record is not None:
            return
        try:
            with self._lock:
                if getattr(cue, "_go_generation", 0) != go_gen or getattr(
                    cue, "_stop_requested", False
                ):
                    return
                if relay.stop_pending:
                    # A STOP or a load was received and has not run yet: this
                    # pass is about to be stopped.
                    return
                run_seq = relay.run_seq
                if run_seq is None:
                    relay.warn_no_run()
                    return
                record = (self._follow_instant_ms(cue, start_ms), run_seq)
                cue._follow_out = record
                follow.record = record
                relay.announce(cue, record[0], run_seq)
        except Exception as e:
            Logger.error(f"Could not announce the follow of cue {cue.id}: {e}")

    def _take_follow_record_locked(self, cue: Cue, record: tuple) -> bool:
        """Compare-and-clear the cue's outstanding announcement. Caller holds
        self._lock. True if `record` was still the outstanding one."""
        if getattr(cue, "_follow_out", None) == record:
            cue._follow_out = None
            return True
        return False

    def _take_follow_on_restart_locked(self, cue: Cue) -> None:
        """go() is starting a cue whose earlier pass announced a follow: that
        follow will not happen. Caller holds self._lock (go()'s commit
        section, after every refusal). The earlier pass's thread may only
        notice at the new pass's end, so the cancel goes out here."""
        record = getattr(cue, "_follow_out", None)
        if record is None:
            return
        cue._follow_out = None
        relay = self._follow
        if relay is None or record[1] != relay.run_seq:
            return
        try:
            relay.cancel(cue, record[0], record[1], "restart")
        except Exception as e:
            Logger.error(f"Could not cancel the follow of cue {cue.id}: {e}")

    def _follow_fired(
        self, cue: Cue, follow: _FollowOut, fire_ms: float, go_gen: int
    ) -> bool:
        """The pass is about to fire its follow: nothing to cancel any more.

        Returns False -- do not fire -- when this pass announced its follow
        and has been replaced since (the cue was started again): go() already
        cancelled the announcement on the other nodes, so firing here would
        play only half of the target. An unannounced follow fires as before."""
        if follow.record is None:
            follow.fired = True
            return True
        with self._lock:
            if getattr(cue, "_go_generation", 0) != go_gen:
                Logger.info(
                    f"Cue {cue.id} was started again before its follow fired; "
                    "the new pass owns the follow"
                )
                return False
            follow.fired = True
            self._take_follow_record_locked(cue, follow.record)
        if abs(fire_ms - follow.record[0]) > 1.0:
            Logger.error(
                f"Cue {cue.id} fires its follow at {fire_ms:.0f}ms but "
                f"announced {follow.record[0]:.0f}ms to the other nodes"
            )
        return True

    def _leave_follow(
        self, cue: Cue, follow: _FollowOut, arm_epoch: int | None
    ) -> None:
        """go_threaded's exit: a pass that announced and did not fire cancels,
        unless every node already knows (a STOP or a load, the yield) or go()
        took the announcement (the cue was started again). Never raises."""
        record = follow.record
        if record is None or follow.fired:
            return
        try:
            with self._lock:
                if not self._take_follow_record_locked(cue, record):
                    return
                if arm_epoch is not None and arm_epoch != self._disarm_epoch:
                    return
                if follow.error:
                    reason = "error"
                elif follow.yielded:
                    return
                elif getattr(cue, "_stop_requested", False):
                    reason = "stop"
                else:
                    Logger.warning(
                        f"Cue {cue.id} ended without firing its follow for no "
                        "known reason; cancelling it on the other nodes"
                    )
                    reason = "error"
                relay = self._follow
                if relay is not None:
                    relay.cancel(cue, record[0], record[1], reason)
        except Exception as e:
            Logger.error(f"Could not cancel the follow of cue {cue.id}: {e}")

    def stop_dispatched_follow(
        self,
        cue: Cue,
        gen: int,
        disarm_epoch: int,
        armed_at: float | None,
        may_cut: bool,
        grace_s: float,
        started_before: float | None = None,
    ) -> tuple[str, float | None]:
        """Stop a cue a cross-node follow dispatched, after the owner
        cancelled that follow (869fc8ytz). Returns (outcome, age):

        - "owned": a newer GO or a STOP has the cue (generation or epoch
          moved); nothing is touched;
        - "stopped": it had not started, or started less than `grace_s` ago
          and `may_cut` (the source was stopped or started again);
        - "left": it started too long ago, or the cancel came from an error
          -- a cue on stage is never cut for an internal reason.

        `age` is seconds since the cue produced output, None if it had not.
        `started_before` is when the cue went on stage in a pass that was
        still playing when the follow dispatched it again (recorded by the
        follow's commit gate): its output counts as started.
        The decision and the stop flags are one lock section; the disarm is
        guarded again (disarm_if_unchanged)."""
        with self._lock:
            if (
                getattr(cue, "_go_generation", 0) != gen
                or self._disarm_epoch != disarm_epoch
            ):
                return "owned", None
            started = getattr(cue, "_revealed_at", None)
            if started is None and getattr(cue, "_revealed", False):
                started = monotonic()
            if started is None:
                started = started_before
            age = None if started is None else monotonic() - started
            if age is not None and (age >= grace_s or not may_cut):
                return "left", age
            cue._stop_requested = True
            new_gen = gen + 1
            cue._go_generation = new_gen
            cue._playing = False
            # 869feynrj §4.3, D12: a pending start is cancelled; a cue on stage
            # (< grace_s) fades before the disarm below cuts it.
            self.cancel_start_locked(
                cue, "stop_of_playing" if age is not None else "cancel"
            )
        self.cancel_pending_descendants(cue)
        self._end_illumination(cue)
        # Let the cue's own loop see the flag and leave (polls every 20 ms),
        # as the stop action does.
        sleep(0.1)
        self.disarm_if_unchanged(
            cue, new_gen, disarm_epoch, armed_at, reason="follow_cancelled"
        )
        return "stopped", age

    def disarm_if_unchanged(
        self,
        cue: Cue,
        gen: int,
        disarm_epoch: int,
        armed_at: float | None,
        reason: str,
    ) -> bool:
        """Disarm a cue only if nothing took it since the caller decided to.

        In one lock section: the generation, the STOP/load epoch and the arm
        stamp must be the caller's, the cue still loaded and no arm of it in
        flight; then this thread takes the cue's arm claim and unpublishes it
        (unloaded, out of the armed list). Its player and layers are released
        outside the lock while the claim is held, so no arm of the same cue
        can run meanwhile; the claim is released in a finally (a leaked one
        would make the cue unarmable until the engine restarts). Returns True
        if it disarmed."""
        with self._lock:
            registry = self._arming_registry()
            if (
                getattr(cue, "_go_generation", 0) != gen
                or self._disarm_epoch != disarm_epoch
                or not getattr(cue, "loaded", False)
                or getattr(cue, "_armed_at", None) != armed_at
                or registry.get(cue.id) is not None
            ):
                return False
            claim = _ArmClaim(holder=current_thread().name, started=monotonic())
            registry[cue.id] = claim
            cue.loaded = False
            cue._playing = False
            if cue.id in self._armed_cues_set:
                self._armed_cues.remove(cue)
                self._armed_cues_set.discard(cue.id)
        try:
            Logger.info(f"Disarming cue {cue.id} ({reason})")
            try:
                if isinstance(cue, AudioCue):
                    self.communications_thread.remove_player(
                        f"audioplayer_{cue.id}", timeout=0.1
                    )
                self.communications_thread.remove_cue(cue.id, timeout=0.1)
            except Exception:
                pass
            self._release_cue_resources(cue, reason)
        finally:
            with self._lock:
                if registry.get(cue.id) is claim:
                    del registry[cue.id]
            claim.event.set()
        return True

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
