# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

import threading
from contextlib import contextmanager
from functools import singledispatch
from time import monotonic
from types import SimpleNamespace

from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode

from ..players.PlayerHandler import PLAYER_HANDLER
from ..players.StartGate import START_GATE
from ..tools.MtcListener import MtcListener
from . import loop_mode

# ---------------------------------------------------------------------------
# The held setup re-checks its pass before it sends (869feynrj S0-2).
#
# The cue's thread parks until start - _RUN_AHEAD_MS and then runs run_cue with
# no lock: a cancel landing in that window was followed by /start_tod, /loop,
# /volmaster (and a DMX scene, a video /offset + /mtcfollow) from a pass that
# no longer existed. The thread installs a guard (CueHandler._SetupGuard) for
# the duration of run_cue; every run_* function computes what it can outside
# the lock (JACK queries, media probes, a CueList child's arm) and then does
# its state changes and its sends inside _setup_section(), which holds
# CueHandler._lock and yields False when the pass was stopped or superseded.
# Thread-local, so run_cue keeps its (cue, mtc, start) signature and a
# CueList's child is set up under its parent's guard. Without a guard (tests,
# direct calls) the section yields True and takes no lock.
# ---------------------------------------------------------------------------
_SETUP_GUARD = threading.local()


@contextmanager
def installed_guard(guard):
    """Install ``guard`` for the run_cue calls made by this thread."""
    previous = getattr(_SETUP_GUARD, "guard", None)
    _SETUP_GUARD.guard = guard
    try:
        yield guard
    finally:
        _SETUP_GUARD.guard = previous


@contextmanager
def _setup_section(cue=None):
    """``cue``: what this section sets up (a CueList's child inside its
    parent's guard), named by the guard's step-3 hold line."""
    guard = getattr(_SETUP_GUARD, "guard", None)
    if guard is None:
        yield True
        return
    with guard.section(cue) as ok:
        yield ok


# The pass this thread runs (869feynrj): the cue that owns it (a CueList's
# child plays inside its parent's pass), its go generation, and the reveal's
# decision taken under CueHandler._lock (follow committed or not). Installed
# by CueHandler.go_threaded for the whole pass, so a reader on the same thread
# (reveal_audioCue, loop_audioCue) compares against THIS pass and not against
# the cue's attributes, which a newer pass may already have reset.
_PASS = threading.local()


@contextmanager
def installed_pass(go_gen: int, owner=None):
    """Install the pass context for this thread (see _PASS)."""
    previous = getattr(_PASS, "ctx", None)
    ctx = SimpleNamespace(gen=go_gen, owner=owner, follow_committed=None)
    _PASS.ctx = ctx
    try:
        yield ctx
    finally:
        _PASS.ctx = previous


def current_pass():
    """The pass context of this thread, or None (tests, direct calls)."""
    return getattr(_PASS, "ctx", None)


def _skipped(cue) -> None:
    Logger.info(
        f"{type(cue).__name__} {cue.id}: held setup skipped, the pass was stopped "
        "or superseded since it was dispatched"
    )


@singledispatch
def run_cue(cue: Cue, mtc: MtcListener, frozen_mtc_ms: float = None):
    """
    Run a cue based on its type.

    Args:
        cue: The cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp in milliseconds.
                       When provided (e.g., for chained cues with
                       post_go='go'),
                       this timestamp is used instead of reading live MTC.
                       This ensures perfect sync between audio and video cues.
    """
    pass


def first_enabled_child(cue) -> Cue | None:
    """First enabled child of a CueList, or None (public name for CueHandler)."""
    return _first_enabled_child(cue)


def _first_enabled_child(cue: CueList) -> Cue | None:
    """First enabled child of a CueList, or None.

    Dedupes the child selection both run_cueList and reveal_cueList need.
    """
    contents = getattr(cue, "contents", None)
    if not contents:
        return None
    return next((c for c in contents if c.enabled), None)


def _ensure_child_loaded(parent: CueList, child: Cue) -> bool:
    """Give a CueList's first-enabled child the same "not loaded at go() time →
    re-arm + warn" safety net CueHandler.go() gives top-level cues.

    run_cueList/reveal_cueList dispatch to the child DIRECTLY, bypassing go()
    (CueHandler.py) — so a child that reaches its trigger un-armed (CueList used
    as a post_go target: _arm_ahead skips CueLists and arm_cue has no CueList
    branch; enabled at runtime before the async arm finished; pre-arm failed)
    would otherwise run against a cue with no player, emitting only a misleading
    log ("subprocess likely crashed between arm and GO") and no recovery.

    Returns True if the child is loaded (already, or after a successful re-arm).
    Non-local children are left untouched — they are owned by the node where
    they ARE local (arm() no-ops for non-local anyway) — and the caller keeps
    the existing direct dispatch for them.
    """
    if not getattr(child, "_local", True):
        return True  # not ours to arm; caller dispatches as before
    if getattr(child, "loaded", False):
        return True

    # Lazy import: CueHandler imports run_cue at module load, so a top-level
    # import here would be circular (mirrors reveal_actionCue's ActionHandler
    # import).
    from .CueHandler import CUE_HANDLER

    Logger.warning(
        f"CueList {parent.id} child {child.id} not loaded at trigger time "
        f"(pre-arm missed — CueList children skip go()'s guard). "
        f"Re-arming as fallback."
    )
    # arm() wraps arm_cue() in try/FINALLY, not try/except: a raise from
    # arm_audioCue/arm_videoCue (e.g. PlayerHandler.new_audio_output's
    # ValueError, or arm_videoCue's output-name lookup) would propagate out of
    # run_cueList and kill the PARENT CueList's go_threaded daemon thread —
    # silently skipping the parent's illuminate/reveal/postwait/chain/disarm,
    # the very failure this guard exists to prevent. Contain it here.
    try:
        CUE_HANDLER.arm(child, init=True)
    except Exception as e:
        Logger.error(
            f"CueList {parent.id} child {child.id} re-arm raised {e!r} — cue "
            f"will produce NO output this GO (silent audio / invisible video)."
        )
        return False
    if not getattr(child, "loaded", False):
        Logger.error(
            f"CueList {parent.id} child {child.id} re-arm did not complete — "
            f"cue will produce NO output this GO (silent audio / invisible "
            f"video)."
        )
        return False
    return True


@run_cue.register
def run_cueList(cue: CueList, mtc: MtcListener, frozen_mtc_ms: float = None):
    """Run a CueList by dispatching its first enabled child.

    Children bypass CueHandler.go(), so replicate go()'s re-arm safety net here
    (_ensure_child_loaded) — otherwise an un-armed child fires with only a
    misleading log and no recovery.
    """
    child = _first_enabled_child(cue)
    if child is None:
        return
    if not _ensure_child_loaded(cue, child):
        return  # re-arm failed (already logged loudly) — don't dispatch
    # A CueList child plays once (869ejxng3 Q2): the load walk marks it too;
    # this covers a child reached without one (defensive, I11).
    child._in_cuelist = True
    run_cue(child, mtc, frozen_mtc_ms)


@run_cue.register
def run_actionCue(cue: ActionCue, mtc: MtcListener, frozen_mtc_ms: float = None):
    """Run an ActionCue by delegating to ActionHandler.execute_action.

    Forwards frozen_mtc_ms so a chained 'play' action triggered inside a
    post_go='go' chain preserves the chain's MTC snapshot — without it,
    ActionCue-mediated chains capture live MTC inside CueHandler.go and
    drift relative to the chain's other cues.
    """
    # Prepare-only: an ActionCue has no media to preload. But it MUST carry a
    # _start_mtc so CueHandler._reveal_wait gates it — otherwise the action would
    # fire at dispatch (a full body early) instead of at its own timeline slot.
    # The action is EXECUTED in reveal_cue() once live MTC reaches _start_mtc.
    if frozen_mtc_ms is not None:
        start_mtc = CTimecode(
            framerate=mtc.main_tc.framerate, start_seconds=frozen_mtc_ms / 1000
        )
    else:
        start_mtc = CTimecode(
            framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames
        )
    with _setup_section(cue) as ok:
        if not ok:
            _skipped(cue)
            return
        cue._start_mtc = start_mtc
    return


def _timed_wiring_check(
    cue, mixer, player_name: str, selected_outputs: list, where: str
) -> bool:
    """_verify_audio_wiring_at_go with its step-3 line (869feynrj S0-18):
    ``wiring check at <arm|GO>: <t> ms (<ok|repaired|failed>)``. A check
    that raises is logged failed and re-raised. True when the graph is
    right."""
    t0 = monotonic()
    status = "failed"
    try:
        status = _verify_audio_wiring_at_go(
            cue, mixer, player_name, selected_outputs, where=where, status=True
        )
    finally:
        Logger.info(
            f"wiring check at {where}: {(monotonic() - t0) * 1000:.1f} ms ({status})"
        )
    return status in ("ok", "repaired")


def _verify_audio_wiring_at_go(
    cue,
    mixer,
    player_name: str,
    selected_outputs: list,
    where: str = "GO",
    status: bool = False,
):
    """Check a player's mixer wiring at GO (or at arm) and fix it edge by edge.
    Returns True when the graph is right (already, or after the repair); with
    ``status=True`` one of "ok", "repaired", "failed" instead.

    Never a full rewire (869fbyjzx): a GO can reach this while the cue is
    audible (a fresh GO, or a 'play' action, on a cue that is still
    playing), and connect_player_to_outputs disconnects every edge first —
    it would cut the healthy channels too. Strays (RtAudio's auto-connect to
    system:playback that an early arm-time wiring missed, 869fcvz85) are
    removed one by one; missing mixer edges are added one by one.
    """
    diff = mixer.player_connection_diff(
        player_name=player_name,
        player_output_prefix="outport",
        selected_outputs=selected_outputs,
    )
    if diff is None:
        Logger.error(
            f"Audio cue {cue.id}: no mixer input for its outputs at {where} "
            f"({selected_outputs}) — cue will be SILENT despite showing "
            f"armed (mixer inputs unavailable)."
        )
        return "failed" if status else False
    missing, stray = diff
    if not missing and not stray:
        Logger.debug(f"Audio cue {cue.id}: graph already wired, skipping connect")
        return "ok" if status else True
    Logger.warning(
        f"Audio cue {cue.id}: graph not wired correctly at {where} "
        f"(missing: {missing}; stray: {stray}); repairing edge by edge"
    )
    connected_ok, strays_left = mixer.repair_player_connections(missing, stray)
    if not connected_ok:
        Logger.error(
            f"Audio cue {cue.id}: mixer repair failed at {where} — cue will be "
            f"SILENT despite showing armed (a mixer connection could not be "
            f"made)."
        )
    if strays_left:
        Logger.error(
            f"Audio cue {cue.id}: stray edge(s) still connected after repair: "
            f"{strays_left} — the cue may sound doubled and outside the mixer."
        )
    ok = bool(connected_ok) and not strays_left
    if status:
        return "repaired" if ok else "failed"
    return ok


def _audio_wiring_target(cue):
    """(mixer, JACK client name, the JACK ports its outputs resolve to) of an
    AudioCue's player, or None without a mixer."""
    mixer = PLAYER_HANDLER.get_audio_mixer()
    if not mixer:
        return None
    uuid_slug = "".join(str(cue.id).split("-"))
    # Actual JACK client name is Audio_Player-{uuid} with ports
    # "outport 0", "outport 1"
    player_name = f"Audio_Player-{uuid_slug}"
    # Resolve JACK port names from cue output IDs via audio output lookup
    selected_outputs = []
    if hasattr(cue, "outputs") and cue.outputs:
        for output in cue.outputs:
            output_name = output.get("output_name", "")
            if len(output_name) > 37:
                output_id = output_name[37:]
                port_name = PLAYER_HANDLER.resolve_audio_port(output_id)
                if port_name:
                    selected_outputs.append(port_name)
                else:
                    selected_outputs.append(output_id)
    return mixer, player_name, selected_outputs


def verify_audio_wiring_at_arm(cue) -> None:
    """869feynrj §4.5a (preload at arm, CAPS selfgate only): the mixer wiring
    check, done once at the end of a successful arm instead of at every GO.
    A selfgate player is built with RTAUDIO_JACK_DONT_CONNECT (S0-20), so no
    RtAudio auto-connect can appear after the arm's own wiring; a GO keeps
    only the cheap port_exists of outport 0. The result is kept on the cue
    (``_wiring_ok``): a check that failed or raised is not trusted, and the
    next GO runs the full diff and repair (review fix 5). Never raises."""
    cue._wiring_ok = False
    try:
        target = _audio_wiring_target(cue)
        if target is None:
            cue._wiring_ok = True  # no mixer on this node: nothing to wire
            return
        mixer, player_name, selected_outputs = target
        cue._wiring_ok = _timed_wiring_check(
            cue, mixer, player_name, selected_outputs, "arm"
        )
    except Exception as e:
        Logger.warning(f"Audio cue {cue.id}: wiring check at arm failed: {e}")


def _audio_ports_ok_at_go(cue, selfgate: bool = False) -> bool:
    """The JACK half of an audio GO, outside any lock. False only when the
    player's outport 0 is gone (it died between arm and GO).

    selfgate (869feynrj §4.5a, review 2 F10): the wiring was checked at arm;
    only the port check stays, unless that check did not succeed
    (``_wiring_ok`` not True): then the full diff and repair run here and
    their result is kept. An older player keeps the GO-time diff and
    edge-by-edge repair (869fbyjzx): its RtAudio may auto-connect when the
    stream starts, so its GO OSC is byte-identical to before."""
    # Verify mixer graph; only repair if drifted. Arm already wired it; the
    # unconditional reconnect at GO costs ~21-28 ms (measured) without
    # touching the audio path.
    try:
        target = _audio_wiring_target(cue)
        if target is None:
            return True
        mixer, player_name, selected_outputs = target
        Logger.debug(f"Audio cue {cue.id} selected outputs: {selected_outputs}")

        # If the player's outport 0 is missing, the subprocess died between
        # arm and GO. connect_player_to_outputs would block 15 s in its
        # port-wait loop before failing; abort fast instead.
        channel_0 = f"{player_name}:outport 0"
        if not mixer.conn_man.port_exists(channel_0):
            Logger.error(
                f"Audio cue {cue.id}: player JACK ports missing at GO "
                f"({channel_0}); subprocess likely crashed between arm "
                f"and GO. Aborting cue."
            )
            return False

        if not selfgate:
            _timed_wiring_check(cue, mixer, player_name, selected_outputs, "GO")
        elif getattr(cue, "_wiring_ok", None) is not True:
            Logger.warning(
                f"Audio cue {cue.id}: its wiring check at arm did not succeed; "
                "checking and repairing it at GO"
            )
            cue._wiring_ok = _timed_wiring_check(
                cue, mixer, player_name, selected_outputs, "GO"
            )
    except Exception as e:
        Logger.warning(f"Could not validate/connect player to mixer: {e}")
    return True


@run_cue.register
def run_audioCue(cue: AudioCue, mtc, frozen_mtc_ms: float = None):
    """
    Run an AudioCue

    Args:
        cue: The audio cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp for perfect sync with
        chained cues
    """
    player = PLAYER_HANDLER.audio_player(cue)
    capable = loop_mode.player_capable(player)
    dayalign = loop_mode.player_dayalign(player)
    selfgate = loop_mode.player_selfgate(player)
    period = loop_mode.period_of(cue)

    # CRITICAL FOR SYNC: Use frozen timestamp if provided (for post_go='go'
    # chains)
    # Otherwise read live MTC. This ensures audio and video cues share the
    # same reference.
    if frozen_mtc_ms is not None:
        mtc_ms = frozen_mtc_ms
        Logger.debug(f"AudioCue {cue.id} using frozen MTC: {mtc_ms}ms")
        # Frozen path: only have a float ms snapshot (CueHandler captured it
        # before this point); reconstruct via canonicalized __init__ which
        # routes through HMSF + tc_to_frames, drop-frame correct.
        start_mtc = CTimecode(
            framerate=mtc.main_tc.framerate, start_seconds=mtc_ms / 1000
        )
    else:
        # Live MTC path: frame-domain construction skips the lossy
        # ms→seconds→frames round-trip entirely (mirrors loop_cue.py:107,224).
        start_mtc = CTimecode(
            framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames
        )

    if period is not None:
        # The pass ends on the file's real length P (one rounding, from the
        # absolute instant, G20), not on the stored duration rounded to frames.
        end_mtc = loop_mode.tc_at(
            mtc.main_tc.framerate, start_mtc.milliseconds_exact + period.ms
        )
    else:
        # Convert duration to MTC framerate to prevent drift when looping
        duration = CTimecode(cue.media.duration).return_in_other_framerate(
            mtc.main_tc.framerate
        )
        end_mtc = start_mtc + duration

    # Audio player formula: file_position = MTC + offset, offset = -start_mtc;
    # a dayalign player gets the start itself, modulo 24 h (/start_tod)
    ports_ok = _audio_ports_ok_at_go(cue, selfgate)

    with _setup_section(cue) as ok:
        if not ok:
            _skipped(cue)
            return
        # Set True only once /offset is sent below. If setup aborts early
        # (e.g. mixer / JACK ports missing), the follow commit and
        # reveal_audioCue see this False and send no follow to a player that
        # never got set up.
        cue._reveal_ready = False
        # 869feynrj §4.2: set by this pass's follow commit, read by its reveal.
        cue._follow_committed = False
        # Wrap mode (869ejxng3, plan §4.5), all reset per GO: _player_wraps is
        # set only by the player's wrap ack, so an abort below leaves it False;
        # the fallback is latched for this GO only (M6).
        cue._player_wraps = False
        cue._wrap_requested = False
        cue._wrap_fallback = False
        cue._wrap_reveal_t = None
        cue._audio_capable = capable
        cue._audio_dayalign = dayalign
        cue._start_mtc = start_mtc
        cue._end_mtc = end_mtc
        if not ports_ok:
            return

        # Define the start - use MTC framerate for consistent timing with video
        try:
            key, value = loop_mode.start_message(cue, cue._start_mtc.milliseconds_exact)
            cue._osc.set_value(key, value)
            Logger.info(
                f"start {value} to {key}:{cue._osc.get_node(key).parameter.value}",
                extra={"caller": cue.__class__.__name__},
            )
        except Exception as e:
            Logger.warning(
                f"Error setting offset in run_audioCue: {e}",
                extra={"caller": cue.__class__.__name__},
            )
        else:
            # Setup reached the offset send → safe to start following.
            cue._reveal_ready = True
            _send_loop_mode(cue, capable, period)

        # /mtcfollow is not sent here. A selfgate player (869feynrj) gets it at
        # the FOLLOW COMMIT, start - F, under CueHandler._lock: it then starts
        # itself at sample 0. Any other player gets it at the MTC-gated reveal
        # (reveal_cue), as before; following early with a future-negative
        # offset used to terminate the cue in the audioplayer (869dyufeh, fixed
        # in 0.0.3-10), so older players keep the reveal-time follow.

        # Apply master volume from cue settings (at every GO, S0-15: a FadeCue
        # may have moved the player's level since the arm)
        try:
            master_vol = getattr(cue, "master_vol", None)
            if master_vol is not None:
                # UI uses 0-100 percentage, audioplayer expects 0.0-1.0 gain
                # Convert and clamp to valid range
                vol_value = max(0.0, min(1.0, float(master_vol) / 100.0))
                cue._osc.set_value("/volmaster", vol_value)
                Logger.info(
                    f"master_vol {master_vol}% -> {vol_value} set on audio cue "
                    f"{cue.id}",
                    extra={"caller": cue.__class__.__name__},
                )
        except Exception as e:
            Logger.warning(
                f"Error setting master volume in run_audioCue: {e}",
                extra={"caller": cue.__class__.__name__},
            )


def _send_loop_mode(cue, capable: bool, period) -> None:
    """After the offset: ``/loop [passes, num, den]`` for a wrap-eligible cue,
    ``/loop [1]`` for every other cue on a capable player; nothing to an old
    player. One INFO line per GO naming the mode."""
    if not capable:
        Logger.info(f"Audio cue {cue.id} loop mode: legacy (player without CAPS loop)")
        return
    wrap = period is not None and cue.loop != 1 and not loop_mode.in_cuelist(cue)
    args = loop_mode.loop_args(cue, period) if wrap else [1]
    try:
        cue._osc.set_value("/loop", args)
    except Exception as e:
        Logger.warning(f"Error sending /loop {args} in run_audioCue: {e}")
        wrap = False
    cue._wrap_requested = wrap
    if wrap:
        Logger.info(
            f"Audio cue {cue.id} loop mode: wrap+varispeed, passes {cue.loop}, "
            f"P = {period.num}/{period.den} = {period.ms:.3f} ms"
        )
    else:
        why = (
            "plays once"
            if cue.loop == 1 or loop_mode.in_cuelist(cue)
            else "no loop period"
        )
        Logger.info(f"Audio cue {cue.id} loop mode: legacy ({why})")


@run_cue.register
def run_dmxCue(cue: DmxCue, mtc, frozen_mtc_ms: float = None):
    """
    Run a DmxCue

    Sends DMX scene bundle directly to the local DMX player.
    Synchronized with MTC. The scene contains frame data, timing, and fade
    info.
    DMX cues have no media duration - duration is inferred from fade times.
    Only fadein_time is used for now. fade_out defaults to 0

    Args:
        cue: The DMX cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp for perfect sync with
        chained cues
    """
    with _setup_section(cue) as ok:
        if not ok:
            _skipped(cue)
            return
        _run_dmxCue_held(cue, mtc, frozen_mtc_ms)


def _run_dmxCue_held(cue: DmxCue, mtc, frozen_mtc_ms: float = None):
    """run_dmxCue's body: the scene send IS the DMX commit, so all of it runs
    inside the setup section (869feynrj S0-2)."""
    try:
        # CRITICAL FOR SYNC: Use frozen timestamp if provided (for post_go='go'
        # chains)
        if frozen_mtc_ms is not None:
            mtc_ms = frozen_mtc_ms
            Logger.debug(f"DmxCue {cue.id} using frozen MTC: {mtc_ms}ms")
            # Frozen path: only have a float ms snapshot; canonicalized
            # __init__ routes through HMSF + tc_to_frames.
            cue._start_mtc = CTimecode(
                framerate=mtc.main_tc.framerate, start_seconds=mtc_ms / 1000
            )
        else:
            # Live MTC path: frame-domain construction (no round-trip loss).
            cue._start_mtc = CTimecode(
                framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames
            )

        # DMX cues have no media - duration is inferred from fade times
        # Duration = fadein_time + fadeout_time (both in milliseconds)
        fadein_ms = getattr(cue, "fadein_time", 0)
        fadeout_ms = getattr(cue, "fadeout_time", 0)
        duration_ms = fadein_ms + fadeout_ms

        # Convert duration to timecode format with explicit framerate
        duration_seconds = duration_ms / 1000.0
        duration = CTimecode(
            framerate=mtc.main_tc.framerate, start_seconds=duration_seconds
        )
        cue._end_mtc = cue._start_mtc + duration

        # Absolute MTC time for this cue (ms). DMX player expects mtc_time as
        # absolute
        # "0:0:S.sss" string so it can schedule m_mtcStart = max(playHead,
        # time).
        offset_milliseconds = cue._start_mtc.milliseconds_exact
        mtc_time_str = f"0:0:{offset_milliseconds / 1000.0}"

        # Get DMX frame data from the cue
        universe_frames = getattr(cue, "_dmx_frames", {})

        if not universe_frames:
            Logger.warning(
                f"DMX cue {cue.id} has no frame data to send",
                extra={"caller": cue.__class__.__name__},
            )
            return

        # Convert fadein_time to seconds for the DMX player (only fadein is
        # used for now)
        fade_time = fadein_ms / 1000.0

        # Check if we have an OSC client
        if cue._osc is None:
            Logger.error(
                f"DMX cue {cue.id} has no OSC client available",
                extra={"caller": cue.__class__.__name__},
            )
            return

        # Enable MTC following so the dmxplayer tracks timecode and stops
        # advancing when MTC stops (e.g. on STOP command).
        cue._osc.enable_mtcfollow()

        # Send DMX scene bundle to local player (mtc_time absolute so no
        # overlap/loss)
        cue._osc.send_dmx_scene(
            universe_frames=universe_frames,
            mtc_time=mtc_time_str,
            fade_time=fade_time,
        )

        Logger.info(
            f"DMX scene sent to local player for cue {cue.id}: "
            f"mtc_time={mtc_time_str} ({offset_milliseconds}ms),"
            f"universes={len(universe_frames)}, fade={fade_time}s",
            extra={"caller": cue.__class__.__name__},
        )

    except Exception as e:
        Logger.error(
            f"Error running DMX cue {cue.id}: {e}",
            extra={"caller": cue.__class__.__name__},
        )
        Logger.exception(e)


def _record_placement_failure(cue: VideoCue, layer_id: str) -> None:
    """Add layer_id to cue._placement_failed (reset by every arm)."""
    failed = getattr(cue, "_placement_failed", None)
    if failed is None:
        failed = cue._placement_failed = []
    if layer_id not in failed:
        failed.append(layer_id)


@run_cue.register
def run_videoCue(cue: VideoCue, mtc, frozen_mtc_ms: float = None):
    """Run a VideoCue.

    Sends offset/visible/mtcfollow to all layers in cue._layer_ids
    via the single VideoClient in cue._osc.
    """
    Logger.info(f"Running video cue {cue.id}")

    layer_ids = getattr(cue, "_layer_ids", [])
    # The media probe (os.stat, a cached ffprobe fallback, 869fat84r) stays
    # outside the setup section's lock (869feynrj S0-2).
    media_dims = (
        PLAYER_HANDLER.cue_media_dimensions(cue)
        if layer_ids and getattr(cue, "_osc", None) is not None
        else (None, None)
    )
    with _setup_section(cue) as ok:
        if not ok:
            _skipped(cue)
            return
        _run_videoCue_held(cue, mtc, frozen_mtc_ms, layer_ids, media_dims)


def _run_videoCue_held(cue: VideoCue, mtc, frozen_mtc_ms, layer_ids, media_dims):
    """run_videoCue's state changes and sends, inside the setup section."""

    # The timeline is stamped BEFORE the layer check (869fgq3xv): a cue with
    # no layers on this node (every output dark) still has a body. Downstream
    # reads _start_mtc/_end_mtc: the Auto-follow instant and its cross-node
    # announce (CueHandler._follow_instant_ms), the reveal wait, loop_videoCue.
    # Left at their zero defaults, a go_at_end follow fired at start+postwait
    # cluster-wide and an infinite loop re-based in a tight loop.
    if frozen_mtc_ms is not None:
        mtc_ms = frozen_mtc_ms
        Logger.debug(f"VideoCue {cue.id} using frozen MTC: {mtc_ms}ms")
        # Frozen path: float ms snapshot; canonicalized __init__ handles it.
        cue._start_mtc = CTimecode(
            framerate=mtc.main_tc.framerate, start_seconds=mtc_ms / 1000
        )
    else:
        # Live MTC path: frame-domain construction (no round-trip loss).
        cue._start_mtc = CTimecode(
            framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames
        )

    # Loop mode (869ejxng3 §4.5, Phase B), fixed for this GO: wrap when the
    # videocomposer is capable and the period carries a video frame count
    # (D15: no mismatch sends a cue to legacy), else legacy.
    wrap = loop_mode.video_wrap_eligible(cue, PLAYER_HANDLER.video_caps)
    cue._video_wrap = wrap
    if wrap:
        pass_ms = loop_mode.period_of(cue).ms
    elif cue.loop != 1:
        pass_ms = loop_mode.video_legacy_pass_ms(cue)
    else:
        pass_ms = None
    if pass_ms is not None:
        # The pass ends on P (in legacy, on min(P, V), R24), one rounding from
        # the absolute instant (G20).
        cue._end_mtc = loop_mode.tc_at(
            mtc.main_tc.framerate, cue._start_mtc.milliseconds_exact + pass_ms
        )
    else:
        duration = CTimecode(cue.media.duration).return_in_other_framerate(
            mtc.main_tc.framerate
        )
        cue._end_mtc = cue._start_mtc + duration
    offset_to_go = -cue._start_mtc.frame_number

    if not layer_ids or getattr(cue, "_osc", None) is None:
        unrouted = getattr(cue, "_unrouted_outputs", None)
        if not layer_ids and unrouted:
            Logger.info(
                f"Video cue {cue.id} is dark on this node (outputs not driven:"
                f" {unrouted}); timeline kept, nothing sent"
            )
        else:
            Logger.error(f"Video cue {cue.id} has no layers or no OSC client")
        return

    client = cue._osc

    # Infinite-loop cues (cue.loop < 1, e.g. loop=-1) must have wraparound
    # enabled on the videocomposer BEFORE the layer starts following MTC below.
    # Otherwise there's a race: the layer follows MTC (mtcfollow=1) from here,
    # but /loop is only sent later by loop_videoCue() — which go_threaded calls
    # AFTER the postwait sleep. In that window the VC has wraparound_=false, so
    # when the media frame overshoots its length it CLAMPS to the last frame
    # (LayerPlayback: adjustedFrame = totalFrames-1) and the video visibly
    # freezes on the final frame until loop_videoCue() finally sends /loop.
    # Sending it here closes the race so the first loop wraps cleanly. Finite
    # loops (cue.loop >= 1) keep the existing loop_videoCue timing untouched.
    loop_early = getattr(cue, "loop", 1) < 1
    # In wrap mode every looping layer gets /loop [1, passes] + /loop/period
    # before /mtcfollow instead: the videocomposer counts the passes itself.

    # Re-apply position for each layer before making visible (layer may not
    # have been ready when position was set during arm). Each layer's output
    # comes from the arm, by layer id: with an unrouted output skipped, layer
    # i is no longer output i (869fgq3xv).
    layer_outputs = getattr(cue, "_layer_outputs", None) or {}
    media_w, media_h = media_dims

    for layer_id in layer_ids:
        layer_path = f"/videocomposer/layer/{layer_id}"

        # Re-apply canvas position from the output config
        output_name = layer_outputs.get(layer_id)
        if output_name is None:
            Logger.warning(
                f"Video cue {cue.id} layer {layer_id}: no output recorded at arm;"
                " placement re-apply skipped"
            )
        else:
            try:
                output = PLAYER_HANDLER.resolve_video_output_for_cue(cue, output_name)
                x, y = output.get_layer_placement()
                client.set_value(f"{layer_path}/position", [x, y])
                sx, sy = output.get_layer_scale(media_w, media_h)
                client.set_value(f"{layer_path}/scale", [sx, sy])
                # Applied now: clear a failure recorded at arm.
                failed = getattr(cue, "_placement_failed", None)
                if failed and layer_id in failed:
                    failed.remove(layer_id)
            except (KeyError, RuntimeError, ValueError) as e:
                _record_placement_failure(cue, layer_id)
                Logger.error(
                    f'Video cue {cue.id} layer {layer_id} on output "{output_name}":'
                    f" position/scale re-apply at GO NOT applied, either may be"
                    f" left at its default ({type(e).__name__}: {e})"
                )
            except Exception:
                _record_placement_failure(cue, layer_id)
                Logger.exception(
                    f"Unexpected error re-applying position for layer"
                    f' {layer_id} (output "{output_name}"): NOT applied'
                )

        client.set_value(f"{layer_path}/offset", int(offset_to_go))
        # Enable wraparound early for infinite loops, BEFORE mtcfollow, so the
        # first loop wraps instead of freezing on the clamped last frame.
        if wrap:
            loop_mode.send_video_wrap(cue, [layer_id])
        elif loop_early:
            client.set_value(f"{layer_path}/loop", [1])
        # Preload the correct frame while INVISIBLE: offset+mtcfollow let the
        # videocomposer decode the frame at this MTC position, but the layer
        # stays hidden. /visible is DEFERRED to reveal_cue() (MTC-gated reveal
        # at the cue's start_mtc) — this is what makes prewait/postwait gaps real.
        client.set_value(f"{layer_path}/mtcfollow", 1)

    Logger.info(
        f"Video cue {cue.id} set up (held invisible): {len(layer_ids)} layer(s),"
        f" offset={offset_to_go}"
    )
    if cue.loop != 1:
        Logger.info(f"Video cue {cue.id} loop mode: {_video_loop_mode_text(cue, wrap)}")


def _video_loop_mode_text(cue, wrap: bool) -> str:
    """The one-line loop mode of a looping VideoCue at GO (§4.5)."""
    period = loop_mode.period_of(cue)
    if wrap:
        return (
            f"wrap, passes {loop_mode.video_passes(cue)}, P = {period.num}/{period.den}"
            f" = {period.ms:.3f} ms, {period.real_frames} frames,"
            f" {getattr(cue, '_loop_origin', None)} length"
        )
    if loop_mode.in_cuelist(cue):
        return "legacy (CueList child)"
    if period is None:
        return "legacy (no loop period)"
    if loop_mode.video_length(period) is None:
        return "legacy (no video frame count, the stored media duration)"
    if loop_mode.VC_LOOP_PERIOD not in PLAYER_HANDLER.video_caps:
        return "legacy (videocomposer without loop_period, re-anchored on min(P, V))"
    return "legacy"


# ---------------------------------------------------------------------------
# reveal_cue: second phase. run_cue() prepares a cue HELD (video invisible,
# audio not-following, action not-yet-run); go_threaded waits until live MTC
# reaches the cue's start_mtc, then calls reveal_cue to make it appear / play /
# execute. This is what turns prewait/postwait offsets into real timeline gaps.
# DmxCue self-schedules (absolute mtc_time) and CueList have nothing → no-op.
# ---------------------------------------------------------------------------
@singledispatch
def reveal_cue(cue: Cue, mtc: MtcListener, frozen_mtc_ms: float = None):
    """Reveal a held cue at its start_mtc. Default no-op (DmxCue self-schedules)."""
    pass


@reveal_cue.register
def reveal_videoCue(cue: VideoCue, mtc, frozen_mtc_ms: float = None):
    layer_ids = getattr(cue, "_layer_ids", [])
    if not layer_ids or getattr(cue, "_osc", None) is None:
        return
    for layer_id in layer_ids:
        try:
            cue._osc.set_value(f"/videocomposer/layer/{layer_id}/visible", 1)
        except Exception as e:
            Logger.warning(
                f"reveal_videoCue: /visible failed for layer {layer_id}: {e}"
            )
    Logger.info(f"Video cue {cue.id} revealed: {len(layer_ids)} layer(s) visible")


@reveal_cue.register
def reveal_audioCue(cue: AudioCue, mtc, frozen_mtc_ms: float = None):
    if getattr(cue, "_osc", None) is None:
        return
    if not getattr(cue, "_reveal_ready", True):
        # run_audioCue aborted setup before /offset (e.g. player ports missing);
        # don't assert mtcfollow on a player that never got set up.
        Logger.info(f"Audio cue {cue.id} reveal skipped (setup aborted)")
        return
    ctx = current_pass()
    if ctx is not None and ctx.follow_committed is not None:
        # Decided in go_threaded's reveal section, under CueHandler._lock: a
        # newer pass's setup may have reset _follow_committed since.
        committed = ctx.follow_committed
    else:
        committed = getattr(cue, "_follow_committed", False) is True
    if committed:
        # 869feynrj §4.2 step 3: a selfgate player got /mtcfollow 1 at the
        # follow commit (start - F) and started itself at sample 0. The
        # reveal re-sends no start (one in PLAY is a reset job, §2.3) and no
        # follow; only /loop in wrap mode, which heals a lost setup /loop
        # (review #11), and the wrap-ack clock starts here as before.
        if loop_mode.wrap_active(cue):
            try:
                cue._osc.set_value(
                    "/loop", loop_mode.loop_args(cue, loop_mode.period_of(cue))
                )
            except Exception as e:
                Logger.warning(f"reveal_audioCue: /loop failed: {e}")
            cue._wrap_reveal_t = monotonic()
        Logger.info(
            f"Audio cue {cue.id} revealed: started by itself (follow committed)"
        )
        return
    # Re-assert offset (MTC is now at start_mtc → seek position ~0), then follow.
    try:
        start = getattr(cue, "_start_mtc", None)
        if start is not None:
            cue._osc.set_value(*loop_mode.start_message(cue, start.milliseconds_exact))
    except Exception as e:
        Logger.warning(f"reveal_audioCue: /offset failed: {e}")
    if loop_mode.wrap_active(cue):
        # re-sent at the reveal (idempotent); the 1 s ack check starts here
        try:
            cue._osc.set_value(
                "/loop", loop_mode.loop_args(cue, loop_mode.period_of(cue))
            )
        except Exception as e:
            Logger.warning(f"reveal_audioCue: /loop failed: {e}")
        cue._wrap_reveal_t = monotonic()
    try:
        player = PLAYER_HANDLER.audio_player(cue)
        if loop_mode.player_selfgate(player):
            # A selfgate player whose follow commit did not happen (its send
            # failed): this reveal-time follow goes through the start gate, so
            # the player is marked following and every later stop (STOP,
            # pause, stop, a cancel) still reaches it with /cancelstart; sent
            # only while the pass that owns it is current.
            gen = ctx.gen if ctx is not None else None
            owner = ctx.owner if ctx is not None and ctx.owner is not None else cue

            def still_current():
                return not getattr(owner, "_stop_requested", False) and (
                    gen is None or getattr(owner, "_go_generation", 0) == gen
                )

            START_GATE.send_follow(player, cue._osc, cue, gen, still_current)
        else:
            cue._osc.set_value("/mtcfollow", 1)
    except Exception as e:
        Logger.warning(f"reveal_audioCue: /mtcfollow failed: {e}")
    Logger.info(f"Audio cue {cue.id} revealed: following MTC")


@reveal_cue.register
def reveal_actionCue(cue: ActionCue, mtc, frozen_mtc_ms: float = None):
    # ActionCues EXECUTE here (at start_mtc), not in run_cue — so a chained
    # action fires at its own timeline slot, not a full body early.
    from .ActionHandler import ACTION_HANDLER

    ACTION_HANDLER.execute_action(cue, mtc, frozen_mtc_ms)


@reveal_cue.register
def reveal_cueList(cue: CueList, mtc, frozen_mtc_ms: float = None):
    """Reveal a CueList target by revealing its first enabled child.

    Mirrors run_cueList: run_cue set the child up HELD, so reveal must recurse to
    the same child — otherwise a CueList used as a post_go='go'/'go_at_end' target
    would leave its child's video invisible / audio silent forever (no error).

    run_cueList (earlier in go_threaded) is the arm point, so by reveal the child
    is normally loaded. If it isn't (run_cueList's re-arm failed — already logged
    loudly there), we log + SKIP rather than re-arm: a reveal-time arm without
    run_cue's setup would leave _start_mtc at its default and make reveal_audioCue
    send a wrong /offset then enable /mtcfollow — actively wrong playback, worse
    than a clean skip.
    """
    child = _first_enabled_child(cue)
    if child is None:
        return
    if getattr(child, "_local", True) and not getattr(child, "loaded", False):
        Logger.warning(
            f"CueList {cue.id} reveal: child {child.id} not loaded (setup never "
            f"completed) — skipping reveal."
        )
        return
    reveal_cue(child, mtc, frozen_mtc_ms)


@singledispatch
def blank_cue(cue: Cue, mtc: MtcListener):
    """Hide a cue's output at its body end, WITHOUT disarming it.

    Used by the pause/go_at_end postwait tail: loop_videoCue leaves /loop 1 on,
    so an undisarmed video keeps visibly wrap-looping after the body ends —
    blank_cue hides it while the cue stays in _armed_cues (STOP-reachable
    through the whole tail; disarming here instead would make the tail
    unreachable by stop_all_cues → ghost fire after STOP). Default no-op:
    audio is already silent (legacy: loop_audioCue sends /mtcfollow 0 at loop
    end; wrap mode, 869ejxng3: the player ends by itself after its last pass),
    DMX scenes have ended, actions/CueLists have nothing to hide.
    """
    pass


@blank_cue.register
def blank_videoCue(cue: VideoCue, mtc):
    layer_ids = getattr(cue, "_layer_ids", [])
    if not layer_ids or getattr(cue, "_osc", None) is None:
        return
    for layer_id in layer_ids:
        try:
            cue._osc.set_value(f"/videocomposer/layer/{layer_id}/visible", 0)
        except Exception as e:
            Logger.warning(
                f"blank_videoCue: /visible 0 failed for layer {layer_id}: {e}"
            )
    Logger.info(
        f"Video cue {cue.id} blanked for postwait tail:"
        f" {len(layer_ids)} layer(s) hidden"
    )
