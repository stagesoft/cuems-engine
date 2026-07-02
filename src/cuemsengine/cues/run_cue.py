# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

from functools import singledispatch
from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode

from ..tools.MtcListener import MtcListener
from ..players.PlayerHandler import PLAYER_HANDLER
from .helpers import find_timing

@singledispatch
def run_cue(cue: Cue, mtc: MtcListener, frozen_mtc_ms: float = None):
    """
    Run a cue based on its type.
    
    Args:
        cue: The cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp in milliseconds.
                       When provided (e.g., for chained cues with post_go='go'),
                       this timestamp is used instead of reading live MTC.
                       This ensures perfect sync between audio and video cues.
    """
    pass

@run_cue.register
def run_cueList(cue: CueList, mtc: MtcListener, frozen_mtc_ms: float = None):
    """Run a CueList by dispatching its first enabled child."""
    if cue.contents:
        first_enabled = next((c for c in cue.contents if c.enabled), None)
        if first_enabled:
            run_cue(first_enabled, mtc, frozen_mtc_ms)

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
        cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=frozen_mtc_ms/1000)
    else:
        cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames)
    return


@run_cue.register
def run_audioCue(cue: AudioCue, mtc, frozen_mtc_ms: float = None):
    """
    Run an AudioCue
    
    Args:
        cue: The audio cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp for perfect sync with chained cues
    """
    # Set True only once /offset is sent below. If setup aborts early (e.g. mixer
    # / JACK ports missing), reveal_audioCue sees this False and no-ops instead of
    # asserting mtcfollow on a player that never got set up.
    cue._reveal_ready = False

    # CRITICAL FOR SYNC: Use frozen timestamp if provided (for post_go='go' chains)
    # Otherwise read live MTC. This ensures audio and video cues share the same reference.
    if frozen_mtc_ms is not None:
        mtc_ms = frozen_mtc_ms
        Logger.debug(f'AudioCue {cue.id} using frozen MTC: {mtc_ms}ms')
        # Frozen path: only have a float ms snapshot (CueHandler captured it
        # before this point); reconstruct via canonicalized __init__ which
        # routes through HMSF + tc_to_frames, drop-frame correct.
        cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=mtc_ms/1000)
    else:
        # Live MTC path: frame-domain construction skips the lossy
        # ms→seconds→frames round-trip entirely (mirrors loop_cue.py:107,224).
        cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames)

    # Convert duration to MTC framerate to prevent drift when looping
    duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
    cue._end_mtc = cue._start_mtc + duration

    # Audio player formula: file_position = MTC + offset
    # To play from position 0 when MTC = start_mtc, we need offset = -start_mtc
    offset_to_go = -cue._start_mtc.milliseconds_exact
    
    # Verify mixer graph; only repair if drifted. Arm already wired it; the
    # unconditional reconnect at GO costs ~21-28 ms (measured) without
    # touching the audio path.
    try:
        mixer = PLAYER_HANDLER.get_audio_mixer()
        if mixer:
            uuid_slug = ''.join(str(cue.id).split('-'))
            # Actual JACK client name is Audio_Player-{uuid} with ports "outport 0", "outport 1"
            player_name = f'Audio_Player-{uuid_slug}'

            # Resolve JACK port names from cue output IDs via audio output lookup
            selected_outputs = []
            if hasattr(cue, 'outputs') and cue.outputs:
                for output in cue.outputs:
                    output_name = output.get('output_name', '')
                    if len(output_name) > 37:
                        output_id = output_name[37:]
                        port_name = PLAYER_HANDLER.resolve_audio_port(output_id)
                        if port_name:
                            selected_outputs.append(port_name)
                        else:
                            selected_outputs.append(output_id)

            Logger.debug(f"Audio cue {cue.id} selected outputs: {selected_outputs}")

            # If the player's outport 0 is missing, the subprocess died between
            # arm and GO. connect_player_to_outputs would block 15 s in its
            # port-wait loop before failing; abort fast instead.
            channel_0 = f'{player_name}:outport 0'
            if not mixer.conn_man.port_exists(channel_0):
                Logger.error(
                    f"Audio cue {cue.id}: player JACK ports missing at GO "
                    f"({channel_0}); subprocess likely crashed between arm "
                    f"and GO. Aborting cue."
                )
                return

            if mixer.player_connections_correct(
                player_name=player_name,
                player_output_prefix='outport',
                selected_outputs=selected_outputs,
            ):
                Logger.debug(f"Audio cue {cue.id}: graph already wired, skipping connect")
            else:
                Logger.warning(
                    f"Audio cue {cue.id}: graph not wired correctly at GO; "
                    f"repairing via connect_player_to_outputs"
                )
                mixer.connect_player_to_outputs(
                    player_name=player_name,
                    player_output_prefix='outport',
                    selected_outputs=selected_outputs,
                )
    except Exception as e:
        Logger.warning(f"Could not validate/connect player to mixer: {e}")
    
    # Define the offset - use MTC framerate for consistent timing with video
    try:
        key = '/offset'

        cue._osc.set_value(key, offset_to_go)
        Logger.info(
            f"offset {offset_to_go} to {key}: {str(cue._osc.get_node(key).parameter.value)}",
            extra = {"caller": cue.__class__.__name__}
        )
    except Exception as e:
        Logger.warning(
            f'Error setting offset in run_audioCue: {e}',
            extra = {"caller": cue.__class__.__name__}
        )
    else:
        # Setup reached the offset send → safe for reveal_cue to start following.
        cue._reveal_ready = True

    # /mtcfollow is DEFERRED to reveal_cue() (MTC-gated reveal). Following early
    # with a future-negative offset hits the audioplayer's "Out of file
    # boundaries" path and TERMINATES the cue before it plays. The offset above
    # is harmless while not following; reveal_cue turns following on at
    # start_mtc, where the seek position is ~0.

    # Apply master volume from cue settings
    try:
        master_vol = getattr(cue, 'master_vol', None)
        if master_vol is not None:
            # UI uses 0-100 percentage, audioplayer expects 0.0-1.0 gain
            # Convert and clamp to valid range
            vol_value = max(0.0, min(1.0, float(master_vol) / 100.0))
            cue._osc.set_value('/volmaster', vol_value)
            Logger.info(
                f"master_vol {master_vol}% -> {vol_value} set on audio cue {cue.id}",
                extra = {"caller": cue.__class__.__name__}
            )
    except Exception as e:
        Logger.warning(
            f'Error setting master volume in run_audioCue: {e}',
            extra = {"caller": cue.__class__.__name__}
        )

@run_cue.register
def run_dmxCue(cue: DmxCue, mtc, frozen_mtc_ms: float = None):
    """
    Run a DmxCue
    
    Sends DMX scene bundle directly to the local DMX player.
    Synchronized with MTC. The scene contains frame data, timing, and fade info.
    DMX cues have no media duration - duration is inferred from fade times.
    Only fadein_time is used for now. fade_out defaults to 0
    
    Args:
        cue: The DMX cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp for perfect sync with chained cues
    """
    try:
        # CRITICAL FOR SYNC: Use frozen timestamp if provided (for post_go='go' chains)
        if frozen_mtc_ms is not None:
            mtc_ms = frozen_mtc_ms
            Logger.debug(f'DmxCue {cue.id} using frozen MTC: {mtc_ms}ms')
            # Frozen path: only have a float ms snapshot; canonicalized
            # __init__ routes through HMSF + tc_to_frames.
            cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=mtc_ms/1000)
        else:
            # Live MTC path: frame-domain construction (no round-trip loss).
            cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames)

        # DMX cues have no media - duration is inferred from fade times
        # Duration = fadein_time + fadeout_time (both in milliseconds)
        fadein_ms = getattr(cue, 'fadein_time', 0)
        fadeout_ms = getattr(cue, 'fadeout_time', 0)
        duration_ms = fadein_ms + fadeout_ms

        # Convert duration to timecode format with explicit framerate
        duration_seconds = duration_ms / 1000.0
        duration = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=duration_seconds)
        cue._end_mtc = cue._start_mtc + duration

        # Absolute MTC time for this cue (ms). DMX player expects mtc_time as absolute
        # "0:0:S.sss" string so it can schedule m_mtcStart = max(playHead, time).
        offset_milliseconds = cue._start_mtc.milliseconds_exact
        mtc_time_str = f"0:0:{offset_milliseconds / 1000.0}"
        
        # Get DMX frame data from the cue
        universe_frames = getattr(cue, '_dmx_frames', {})
        
        if not universe_frames:
            Logger.warning(
                f"DMX cue {cue.id} has no frame data to send",
                extra = {"caller": cue.__class__.__name__}
            )
            return
        
        # Convert fadein_time to seconds for the DMX player (only fadein is used for now)
        fade_time = fadein_ms / 1000.0
        
        # Check if we have an OSC client
        if cue._osc is None:
            Logger.error(
                f"DMX cue {cue.id} has no OSC client available",
                extra = {"caller": cue.__class__.__name__}
            )
            return
        
        # Enable MTC following so the dmxplayer tracks timecode and stops
        # advancing when MTC stops (e.g. on STOP command).
        cue._osc.enable_mtcfollow()

        # Send DMX scene bundle to local player (mtc_time absolute so no overlap/loss)
        cue._osc.send_dmx_scene(
            universe_frames=universe_frames,
            mtc_time=mtc_time_str,
            fade_time=fade_time
        )
        
        Logger.info(
            f"DMX scene sent to local player for cue {cue.id}: "
            f"mtc_time={mtc_time_str} ({offset_milliseconds}ms), universes={len(universe_frames)}, fade={fade_time}s",
            extra = {"caller": cue.__class__.__name__}
        )
        
    except Exception as e:
        Logger.error(
            f'Error running DMX cue {cue.id}: {e}',
            extra = {"caller": cue.__class__.__name__}
        )
        Logger.exception(e)

@run_cue.register
def run_videoCue(cue: VideoCue, mtc, frozen_mtc_ms: float = None):
    """Run a VideoCue.
    
    Sends offset/visible/mtcfollow to all layers in cue._layer_ids
    via the single VideoClient in cue._osc.
    """
    Logger.info(f'Running video cue {cue.id}')

    layer_ids = getattr(cue, '_layer_ids', [])
    if not layer_ids or cue._osc is None:
        Logger.error(f'Video cue {cue.id} has no layers or no OSC client')
        return

    if frozen_mtc_ms is not None:
        mtc_ms = frozen_mtc_ms
        Logger.debug(f'VideoCue {cue.id} using frozen MTC: {mtc_ms}ms')
        # Frozen path: float ms snapshot; canonicalized __init__ handles it.
        cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=mtc_ms/1000)
    else:
        # Live MTC path: frame-domain construction (no round-trip loss).
        cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, frames=mtc.main_tc.frames)

    duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
    cue._end_mtc = cue._start_mtc + duration
    offset_to_go = -cue._start_mtc.frame_number

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
    loop_early = getattr(cue, 'loop', 1) < 1

    # Re-apply position for each layer before making visible (layer may not have
    # been ready when position was set during arm)
    output_names = PLAYER_HANDLER.get_all_cue_output_names(cue)

    for index, layer_id in enumerate(layer_ids):
        layer_path = f'/videocomposer/layer/{layer_id}'

        # Re-apply canvas position from the output config
        if index < len(output_names):
            output_name = output_names[index]
            try:
                output = PLAYER_HANDLER.resolve_video_output_for_cue(cue, output_name)
                x, y = output.get_layer_placement()
                client.set_value(f'{layer_path}/position', [x, y])
                sx, sy = output.get_layer_scale()
                if sx != 1.0 or sy != 1.0:
                    client.set_value(f'{layer_path}/scale', [sx, sy])
            except (KeyError, RuntimeError, ValueError) as e:
                Logger.warning(f'Could not re-apply position for layer {layer_id}: {e}')
            except Exception:
                Logger.exception(f'Unexpected error re-applying position for layer {layer_id} (output "{output_name}")')

        client.set_value(f'{layer_path}/offset', int(offset_to_go))
        # Enable wraparound early for infinite loops, BEFORE mtcfollow, so the
        # first loop wraps instead of freezing on the clamped last frame.
        if loop_early:
            client.set_value(f'{layer_path}/loop', 1)
        # Preload the correct frame while INVISIBLE: offset+mtcfollow let the
        # videocomposer decode the frame at this MTC position, but the layer
        # stays hidden. /visible is DEFERRED to reveal_cue() (MTC-gated reveal
        # at the cue's start_mtc) — this is what makes prewait/postwait gaps real.
        client.set_value(f'{layer_path}/mtcfollow', 1)

    Logger.info(f"Video cue {cue.id} set up (held invisible): {len(layer_ids)} layer(s), offset={offset_to_go}")


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
    layer_ids = getattr(cue, '_layer_ids', [])
    if not layer_ids or getattr(cue, '_osc', None) is None:
        return
    for layer_id in layer_ids:
        try:
            cue._osc.set_value(f'/videocomposer/layer/{layer_id}/visible', 1)
        except Exception as e:
            Logger.warning(f'reveal_videoCue: /visible failed for layer {layer_id}: {e}')
    Logger.info(f'Video cue {cue.id} revealed: {len(layer_ids)} layer(s) visible')


@reveal_cue.register
def reveal_audioCue(cue: AudioCue, mtc, frozen_mtc_ms: float = None):
    if getattr(cue, '_osc', None) is None:
        return
    if not getattr(cue, '_reveal_ready', True):
        # run_audioCue aborted setup before /offset (e.g. player ports missing);
        # don't assert mtcfollow on a player that never got set up.
        Logger.info(f'Audio cue {cue.id} reveal skipped (setup aborted)')
        return
    # Re-assert offset (MTC is now at start_mtc → seek position ~0), then follow.
    try:
        start = getattr(cue, '_start_mtc', None)
        if start is not None:
            cue._osc.set_value('/offset', -start.milliseconds_exact)
    except Exception as e:
        Logger.warning(f'reveal_audioCue: /offset failed: {e}')
    try:
        cue._osc.set_value('/mtcfollow', 1)
    except Exception as e:
        Logger.warning(f'reveal_audioCue: /mtcfollow failed: {e}')
    Logger.info(f'Audio cue {cue.id} revealed: following MTC')


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
    """
    if getattr(cue, 'contents', None):
        first_enabled = next((c for c in cue.contents if c.enabled), None)
        if first_enabled:
            reveal_cue(first_enabled, mtc, frozen_mtc_ms)
