from functools import singledispatch
from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode

from ..tools.MtcListener import MtcListener
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
def run_audioCue(cue: AudioCue, ossia, mtc):
    """
    Run an AudioCue
    """
    # Define the offset
    try:
        key = '/offset'
        cue._start_mtc = CTimecode(frames=mtc.main_tc.milliseconds)
        
        cue._end_mtc = cue._start_mtc + (cue.media.regions[0].out_time - cue.media.regions[0].in_time)
        offset_to_go = float(-(cue._start_mtc.milliseconds) + cue.media.regions[0].in_time.milliseconds)
        
        cue._osc.set_value(key, offset_to_go)
        Logger.info(
            f"offset {offset_to_go} to {key}: {str(cue._osc.get_value(key))}",
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
def run_dmxCue(cue: DmxCue, ossia, mtc):
    """
    Run a DmxCue
    """
    pass

    # TODO: Implement this
    # Define the offset
    try:
        key = f'{cue._osc_route}{cue._offset_route}'
        ossia.set_value(key, cue.review_offset(mtc))
        Logger.info(
            f"DMX play {cue.id}: {key} {str(ossia.get_value(key))}",
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'OSC Key error 1 in run_dmxCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )

    # Connect to mtc signal
    try:
        key = '/mtcfollow'
        cue._osc.set_value(key, 1)
    except KeyError:
        Logger.debug(
            f'OSC Key error 2 in run_dmxCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )

@run_cue.register
def run_videoCue(cue: VideoCue, ossia, mtc):
    """
    Run a VideoCue
    """
    # Define the offset
    try:
        key = '/offset'
        cue._start_mtc = CTimecode(frames=mtc.main_tc.milliseconds)
        
        cue._end_mtc = cue._start_mtc + (cue.media.regions[0].out_time - cue.media.regions[0].in_time)
        offset_to_go = float(-(cue._start_mtc.milliseconds) + cue.media.regions[0].in_time.milliseconds)
        
        cue._osc.set_value(key, offset_to_go)
        Logger.info(
            f"offset {offset_to_go} result: {str(cue._osc.get_value(key))}",
            extra = {"caller": cue.__class__.__name__}
        )
    except KeyError:
        Logger.debug(
            f'Key error 1 in run_videoCue {key}',
            extra = {"caller": cue.__class__.__name__}
        )
        
        try:
            key = '/jadeo/cmd'
            ossia.set_value(key, "midi connect Midi Through")
        except KeyError:
            Logger.debug(
                f'Key error 2 (connect) in run_videoCue {key}',
                extra = {"caller": cue.__class__.__name__}
            )
