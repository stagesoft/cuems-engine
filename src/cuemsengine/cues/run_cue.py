from functools import singledispatch
from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode

from ..tools.MtcListener import MtcListener
from ..players.PlayerHandler import PLAYER_HANDLER
from .helpers import find_timing

@singledispatch
def run_cue(cue: Cue, mtc: MtcListener):
    """
    Run a cue based on its type
    """
    pass

@run_cue.register
def run_cueList(cue: CueList, mtc: MtcListener):
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
def run_actionCue(cue: ActionCue, mtc: MtcListener):
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
def run_audioCue(cue: AudioCue, mtc):
    """
    Run an AudioCue
    """
    # Define the offset
    try:
        key = '/offset'
        cue._start_mtc = CTimecode(start_seconds=mtc.main_tc.milliseconds/1000)
        cue._end_mtc = cue._start_mtc + CTimecode(cue.media.duration)
        
        #cue._end_mtc = cue._start_mtc + (cue.media.regions[0].out_time - cue.media.regions[0].in_time)
        #offset_to_go = float(-(cue._start_mtc.milliseconds) + cue.media.regions[0].in_time.milliseconds)
        offset_to_go = cue._start_mtc.milliseconds

        cue._osc.set_value(key, offset_to_go)
        Logger.info(
            f"offset {offset_to_go} to {key}: {str(cue._osc.get_node(key).parameter.value)}",
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error 1 in run_audioCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )

    # Connect to mtc signal
    try:
        key = '/mtcfollow'
        cue._osc.set_value(key, 1)
    except KeyError:
        Logger.debug(
            f'Key error 2 in run_audioCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )

@run_cue.register
def run_dmxCue(cue: DmxCue, mtc):
    """
    Run a DmxCue
    
    Sends DMX scene bundle directly to the local DMX player.
    Synchronized with MTC. The scene contains frame data, timing, and fade info.
    DMX cues have no media duration - duration is inferred from fade times.
    Only fadein_time is used for now. fade_out defaults to 0
    """
    try:
        # Calculate MTC timing (same as AudioCue)
        cue._start_mtc = CTimecode(start_seconds=mtc.main_tc.milliseconds/1000)
        
        # DMX cues have no media - duration is inferred from fade times
        # Duration = fadein_time + fadeout_time (both in milliseconds)
        fadein_ms = getattr(cue, 'fadein_time', 0)
        fadeout_ms = getattr(cue, 'fadeout_time', 0)
        duration_ms = fadein_ms + fadeout_ms
        
        # Convert duration to timecode format (HH:MM:SS.mmm)
        duration_seconds = duration_ms / 1000.0
        cue._end_mtc = cue._start_mtc + CTimecode(start_seconds=duration_seconds)
        
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
def run_videoCue(cue: VideoCue, mtc):
    """
    Run a VideoCue
    """
    Logger.info(f'Running video cue loop {cue.id}')
    
    # TEMPORARY FIX for xjadeo: Load the video file on run.
    # xjadeo can only display one video at a time, so when multiple cues share
    # the same output, the last armed cue's video overwrites previous ones.
    # This ensures the correct video is loaded when the cue actually runs.
    # TODO: Remove this when migrating to a multi-layer video player that can
    # pre-load multiple videos simultaneously (arm loads, run just plays).
    try:
        key = '/jadeo/load'
        value = PLAYER_HANDLER.media_path(cue.media['file_name'])
        cue._osc.set_value(key, value)
        Logger.info(
            f"load {value} result: {str(cue._osc.get_node(key).parameter.value)}",
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error (load) in run_videoCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )
    
    # Define the offset
    try:
        key = '/jadeo/offset'
        cue._start_mtc = mtc.main_tc
        duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
        cue._end_mtc = cue._start_mtc + duration
        #cue._end_mtc = cue._start_mtc + (cue.media.regions[0].out_time - cue.media.regions[0]['Region']['in_time'])
        #offset_to_go = float(-(cue._start_mtc.milliseconds) + cue.media.regions[0].in_time.milliseconds)
        offset_to_go = cue._start_mtc.frame_number
        cue._osc.set_value(key, str(offset_to_go))
        Logger.info(
            f"offset {offset_to_go} result: {str(cue._osc.get_node(key).parameter.value)}",
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error 1 in run_videoCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )

    # Connect to mtc signal
    try:
        key = '/jadeo/cmd'
        cue._osc.set_value(key, "midi connect Midi Through")
    except KeyError:
        Logger.debug(
            f'Key error 2 (connect) in run_videoCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )
