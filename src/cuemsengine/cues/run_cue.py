from functools import singledispatch

from .Cue import Cue
from .CueList import CueList
from .AudioCue import AudioCue
from .ActionCue import ActionCue
from .DmxCue import DmxCue
from .VideoCue import VideoCue

from ..log import Logger
from ..CTimecode import CTimecode

@singledispatch
def run_cue(cue: Cue, ossia, mtc):
    """
    Run a cue based on its type
    """
    pass

@run_cue.register
def _(cue: CueList, ossia, mtc):
    """
    Run a CueList

    This function will run the fist cue in the list
    """
    try:
        if cue.contents:
            cue.contents[0].go(ossia, mtc)
    except Exception as e:
        Logger.error(
            f'GO failed for content {cue.contents[0].uuid}: {e}',
            extra = {"caller": cue.__class__.__name__}
        )

@run_cue.register
def _(cue: ActionCue, ossia, mtc):
    """
    Run an ActionCue
    """
    if cue.action_type == 'load':
        cue._action_target_object.arm(cue._conf, ossia, cue._armed_list)
    elif cue.action_type == 'unload':
        cue._action_target_object.disarm(ossia)
    elif cue.action_type == 'play':
        cue._action_target_object.go(ossia, mtc)
    elif cue.action_type == 'pause':
        pass
    elif cue.action_type == 'stop':
        pass
    elif cue.action_type == 'enable':
        cue._action_target_object.enabled = True
    elif cue.action_type == 'disable':
        cue._action_target_object.enabled = False
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
def _(cue: AudioCue, ossia, mtc):
    """
    Run an AudioCue
    """
    if cue._local:
        try:
            key = f'{cue._osc_route}/offset'
            #cue._start_mtc = CTimecode(frames=mtc.main_tc.milliseconds + harcoded_go_offset)
            
            # cue._start_mtc = CTimecode(frames=harcoded_go_offset)
            
            cue._end_mtc = cue._start_mtc + (cue.media.regions[0].out_time - cue.media.regions[0].in_time)
            offset_to_go = float(-(cue._start_mtc.milliseconds) + cue.media.regions[0].in_time.milliseconds)
            ossia.send_message(key, offset_to_go)
            Logger.info(
                f"Sending offset {offset_to_go} to {key} {str(ossia._oscquery_registered_nodes[key][0].value)}",
                extra = {"caller": cue.__class__.__name__}
            )
        except KeyError:
            Logger.debug(
                f'Key error 1 in go_callback {key}',
                extra = {"caller": cue.__class__.__name__}
            )

        # Connect to mtc signal
        try:
            key = f'{cue._osc_route}/mtcfollow'
            ossia.send_message(key, 1)
        except KeyError:
            Logger.debug(
                f'Key error 2 in go_callback {key}',
                extra = {"caller": cue.__class__.__name__}
            )

@run_cue.register
def _(cue: DmxCue, ossia, mtc):
    """
    Run a DmxCue
    """
    try:
        key = f'{cue._osc_route}{cue._offset_route}'
        ossia.osc_registered_nodes[key][0].value = cue.review_offset(mtc)
        Logger.info(
            f"DMX play {cue.uuid}: {key} {str(ossia.osc_registered_nodes[key][0].value)}",
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'OSC Key error 1 in go_callback {key}',
            extra = {"caller": cue.__class__.__name__}
        )
    try:
        key = f'{cue._osc_route}/mtcfollow'
        ossia.osc_registered_nodes[key][0].value = True
    except KeyError:
        Logger.debug(
            f'OSC Key error 2 in go_callback {key}',
            extra = {"caller": cue.__class__.__name__}
        )

@run_cue.register
def _(cue: VideoCue, ossia, mtc):
    """
    Run a VideoCue
    """
    ### harcoded for TODO: proto_fruta, need fixx
    #try to make all cues start at sync at 10 second timecode!
    harcoded_go_offset = 20000

    if cue._local:
        # PLAY : specific video cue stuff
        try:
            key = f'{cue._osc_route}/jadeo/offset'
            #cue._start_mtc = mtc.main_tc

            ### harcoded for TODO: proto_fruta, need fixx             
            cue._start_mtc = CTimecode(frames=harcoded_go_offset)
            
            offset_to_go, _ = find_timing(cue, mtc)
            ossia.send_message(key, offset_to_go)
            Logger.info(
                key + " " + str(ossia._oscquery_registered_nodes[key][0].value),
                extra = {"caller": cue.__class__.__name__}
            )
        except KeyError:
            Logger.debug(
                f'Key error 1 (offset) in go_callback {key}',
                extra = {"caller": cue.__class__.__name__}
            )
        
        try:
            key = f'{cue._osc_route}/jadeo/cmd'
            ossia.send_message(key, "midi connect Midi Through")
        except KeyError:
            Logger.debug(
                f'Key error 2 (connect) in go_callback {key}',
                extra = {"caller": cue.__class__.__name__}
            )

def find_timing(cue: Cue, mtc) -> tuple[int, CTimecode]:
    """Find the duration and offset of a cue
     
    Args:
        cue (Cue): The cue with _start_mtc defined to find the timing
        mtc (Mtc): The main timecode object
    """
    # Calculate duration
    duration = cue.media.regions[0].out_time - cue.media.regions[0].in_time
    duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
    # Set cue end timecode
    cue._end_mtc = cue._start_mtc + duration
    in_time_fr_adjusted = cue.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate)
    # Calculate offset to go
    offset_to_go = in_time_fr_adjusted.frame_number - cue._start_mtc.frame_number
    return offset_to_go, duration
