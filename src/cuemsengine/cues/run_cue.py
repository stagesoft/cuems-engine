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
    """Run an ActionCue by delegating to ActionHandler.execute_action."""
    from .ActionHandler import ACTION_HANDLER

    ACTION_HANDLER.execute_action(cue, mtc)


@run_cue.register
def run_audioCue(cue: AudioCue, mtc, frozen_mtc_ms: float = None):
    """
    Run an AudioCue
    
    Args:
        cue: The audio cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp for perfect sync with chained cues
    """
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
    
    # Try to connect player to mixer based on cue output settings
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
            
            # Connect based on selected outputs
            mixer.connect_player_to_outputs(
                player_name=player_name,
                player_output_prefix='outport',
                selected_outputs=selected_outputs
            )
    except Exception as e:
        Logger.warning(f"Could not connect player to mixer: {e}")
    
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

    # Connect to mtc signal
    try:
        key = '/mtcfollow'
        cue._osc.set_value(key, 1)
    except Exception as e:
        Logger.warning(
            f'Error setting mtcfollow in run_audioCue: {e}',
            extra = {"caller": cue.__class__.__name__}
        )
    
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
        # Send mtcfollow before visible so the videocomposer loads the
        # correct frame (using offset + MTC position) while the layer is
        # still invisible. This prevents rendering a stale frame.
        client.set_value(f'{layer_path}/mtcfollow', 1)
        client.set_value(f'{layer_path}/visible', 1)

    Logger.info(f"Video cue {cue.id} running: {len(layer_ids)} layer(s), offset={offset_to_go}")
