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
    """
    Run a CueList

    This function will run the fist cue in the list
    """
    try:
        if cue.contents:
            cue.contents[0].go(mtc)
    except Exception as e:
        Logger.error(
            f'GO failed for content {cue.contents[0].id}: {e}',
            extra = {"caller": cue.__class__.__name__}
        )

@run_cue.register
def run_actionCue(cue: ActionCue, mtc: MtcListener, frozen_mtc_ms: float = None):
    """
    Run an ActionCue
    """
    pass


    # TODO: Implement this
    if cue.action_type == 'load':
        cue._action_target_object.arm(cue._conf, cue._armed_list)
    elif cue.action_type == 'unload':
        cue._action_target_object.disarm()
    elif cue.action_type == 'play':
        cue._action_target_object.go(mtc)
    elif cue.action_type == 'pause':
        pass
    elif cue.action_type == 'stop':
        pass
    elif cue.action_type == 'enable':
        cue._action_target_object.enabled = True
    elif cue.action_type == 'disable':
        cue._action_target_object.enabled = False
    # DEV: To be implemented
    elif cue.action_type == 'fade_in':
        cue._action_target_object.enabled = False
    elif cue.action_type == 'fade_out':
        cue._action_target_object.enabled = False
    elif cue.action_type == 'wait':
        cue._action_target_object.enabled = False
    elif cue.action_type == 'go_to':
        cue._action_target_object.enabled = False
    elif cue.action_type == 'pause_project':
        cue._action_target_object.enabled = False
    elif cue.action_type == 'resume_project':
        cue._action_target_object.enabled = False

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
    else:
        mtc_ms = float(mtc.main_tc.milliseconds)
    
    cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=mtc_ms/1000)
    # Convert duration to MTC framerate to prevent drift when looping
    duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
    cue._end_mtc = cue._start_mtc + duration
    
    # Audio player formula: file_position = MTC + offset
    # To play from position 0 when MTC = start_mtc, we need offset = -start_mtc
    offset_to_go = float(-cue._start_mtc.milliseconds)
    
    # Try to connect player to mixer based on cue output settings
    try:
        mixer = PLAYER_HANDLER.get_audio_mixer()
        if mixer:
            uuid_slug = ''.join(str(cue.id).split('-'))
            # Actual JACK client name is Audio_Player-{uuid} with ports "outport 0", "outport 1"
            player_name = f'Audio_Player-{uuid_slug}'
            
            # Parse cue.outputs to determine which mixer inputs to use
            # Format: [{'output_name': 'uuid_system:playback_1', ...}, ...]
            selected_outputs = []
            if hasattr(cue, 'outputs') and cue.outputs:
                for output in cue.outputs:
                    output_name = output.get('output_name', '')
                    # Extract port name after the UUID (36 chars + underscore)
                    if len(output_name) > 37:
                        port_name = output_name[37:]  # e.g., 'system:playback_1'
                        selected_outputs.append(port_name)
            
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
        else:
            mtc_ms = float(mtc.main_tc.milliseconds)
        
        # Calculate MTC timing - use explicit framerate for consistency
        cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=mtc_ms/1000)
        
        # DMX cues have no media - duration is inferred from fade times
        # Duration = fadein_time + fadeout_time (both in milliseconds)
        fadein_ms = getattr(cue, 'fadein_time', 0)
        fadeout_ms = getattr(cue, 'fadeout_time', 0)
        duration_ms = fadein_ms + fadeout_ms
        
        # Convert duration to timecode format with explicit framerate
        duration_seconds = duration_ms / 1000.0
        duration = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=duration_seconds)
        cue._end_mtc = cue._start_mtc + duration
        
        # Calculate offset (same calculation as AudioCue)
        offset_milliseconds = cue._start_mtc.milliseconds
        
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
        
        # Send DMX scene bundle to local player
        cue._osc.send_dmx_scene(
            universe_frames=universe_frames,
            mtc_time=offset_milliseconds,
            fade_time=fade_time
        )
        
        Logger.info(
            f"DMX scene sent to local player for cue {cue.id}: "
            f"offset={offset_milliseconds}ms, universes={len(universe_frames)}, fade={fade_time}s",
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
    
    Args:
        cue: The video cue to run
        mtc: The MTC listener (for framerate info)
        frozen_mtc_ms: Optional frozen MTC timestamp for perfect sync with chained cues
    
    Supports multiple video outputs - sends commands to all OSC clients in cue._osc_list.
    """
    Logger.info(f'Running video cue loop {cue.id}')
    
    # Get OSC clients for all outputs
    osc_list = getattr(cue, '_osc_list', [cue._osc]) if hasattr(cue, '_osc') else []
    if not osc_list:
        Logger.error(f'No OSC clients available for video cue {cue.id}')
        return
    
    Logger.debug(f'Video cue {cue.id} has {len(osc_list)} output(s)')
    
    # CRITICAL FOR SYNC: Use frozen timestamp if provided (for post_go='go' chains)
    if frozen_mtc_ms is not None:
        mtc_ms = frozen_mtc_ms
        Logger.debug(f'VideoCue {cue.id} using frozen MTC: {mtc_ms}ms')
    else:
        mtc_ms = float(mtc.main_tc.milliseconds)
    
    # Calculate timing - create snapshot copy of current MTC (not a reference!)
    cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=mtc_ms/1000)
    duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
    cue._end_mtc = cue._start_mtc + duration
    # xjadeo formula: displayFrame = MTC + offset
    # To show video frame 0 when MTC is at frame N, we need offset = -N
    offset_to_go = -cue._start_mtc.frame_number
    
    video_path = PLAYER_HANDLER.media_path(cue.media['file_name'])
    
    # Send commands to ALL video outputs
    for i, osc_client in enumerate(osc_list):
        # Load the video file via pyossia OSC
        try:
            osc_client.set_value('/jadeo/load', video_path)
            Logger.info(f"load {video_path} on output {i}", extra={"caller": cue.__class__.__name__})
        except Exception as e:
            Logger.error(f"Video load failed on output {i}: {e}", extra={"caller": cue.__class__.__name__})
        
        Logger.info(f"Video cue output {i}: port={osc_client.remote_port}, offset={offset_to_go}", extra={"caller": cue.__class__.__name__})
        
        # Set offset via pyossia OSC (NEGATIVE value: xjadeo formula is displayFrame = MTC + offset)
        try:
            osc_client.set_value('/jadeo/offset', int(offset_to_go))
            Logger.info(f"offset: {offset_to_go} on output {i}", extra={"caller": cue.__class__.__name__})
        except Exception as e:
            Logger.error(f"Offset set failed on output {i}: {e}", extra={"caller": cue.__class__.__name__})
        
        # Connect to MTC via pyossia OSC
        try:
            osc_client.set_value('/jadeo/cmd', 'midi connect Midi Through')
            Logger.info(f"midi connect on output {i}", extra={"caller": cue.__class__.__name__})
        except Exception as e:
            Logger.error(f"MIDI connect failed on output {i}: {e}", extra={"caller": cue.__class__.__name__})
