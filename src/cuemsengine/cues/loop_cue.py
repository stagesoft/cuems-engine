from functools import singledispatch
from time import sleep

from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode

@singledispatch
def loop_cue(cue: Cue, mtc):
    """
    Loop a cue based on its type
    """
    pass

@loop_cue.register
def loop_cueList(cue: CueList, mtc):
    """
    Loop a CueList
    """
    pass

@loop_cue.register
def loop_actionCue(cue: ActionCue, mtc):
    """
    Loop an ActionCue
    """
    pass

@loop_cue.register
def loop_audioCue(cue: AudioCue, mtc):
    """Handle the audio media playback loop.
        
    This method manages the playback loop for audio media, including handling
    looping behavior and OSC communication for timing control.
    
    Args:
        ossia: The OSC communication interface.
        mtc: The MIDI Time Code interface.
    """
    try:
        loop_counter = 0
        # duration = cue.media.regions[0].out_time - cue.media.regions[0].in_time
        duration = CTimecode(cue.media.duration)

        while not cue.loop or loop_counter < cue.loop:
            while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
                sleep(0.005)

            if cue._local:
                # Recalculate offset and apply
                cue._start_mtc = CTimecode(start_seconds=mtc.main_tc.milliseconds/1000)
                cue._end_mtc = cue._start_mtc + duration
                offset_to_go = float(-(cue._start_mtc.milliseconds) + duration.milliseconds)
                # offset_to_go = duration.milliseconds * (-1)
                try:
                    key = '/offset'
                    cue._osc.set_value(key, offset_to_go)
                except KeyError:
                    Logger.debug(
                        f'Key error 3 in go_callback {key}',
                        extra = {"caller": cue.__class__.__name__}
                    )

            loop_counter += 1

        if cue._local:                
            try:
                key = '/mtcfollow'
                cue._osc.set_value(key, 0)
            except KeyError:
                Logger.debug(
                    f'Key error 4 in go_callback {key}',
                    extra = {"caller": cue.__class__.__name__}
                )

    except AttributeError:
        pass

@loop_cue.register
def loop_dmxCue(cue: DmxCue, mtc):
    """
    Loop a DmxCue
    """
    pass

@loop_cue.register
def loop_videoCue(cue: VideoCue, mtc):
    """Handle the video media playback loop.
        
    This method manages the playback loop for video media, including handling
    looping behavior, frame rate conversion, and OSC communication for timing control.
    
    Args:
        ossia: The OSC communication interface.
        mtc: The MIDI Time Code interface.
    """
    try:
        loop_counter = 0
        duration = CTimecode(cue.media.duration)
        # duration = cue.media.regions[0].out_time - cue.media.regions[0].in_time
        # duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
        #in_time_adjusted = cue.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate)

        while not cue.loop or loop_counter < cue.loop:
            while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
                sleep(0.005)

            if cue._local:
                try:
                    key = '/jadeo/offset'
                    cue._start_mtc = CTimecode(start_seconds=mtc.main_tc.milliseconds/1000)
                    cue._end_mtc = cue._start_mtc + duration
                    # offset_to_go = in_time_adjusted.frame_number - cue._start_mtc.frame_number
                    offset_to_go = duration.frame_number * (-1)
                    cue._osc.set_value(key, str(offset_to_go))
                    Logger.info(
                        key + " " + str(cue._osc.get_node(key).parameter.value),
                        extra = {"caller": cue.__class__.__name__}
                    )
                except KeyError:
                    Logger.debug(
                        f'Key error 1 (offset) in go_callback {key}',
                        extra = {"caller": cue.__class__.__name__}
                    )
            
            loop_counter += 1

        if cue._local:
            try:
                key = '/jadeo/cmd'
                cue._osc.set_value(key, 'midi disconnect')
                Logger.info(
                    key + " " + str(cue._osc.get_value(key)),
                    extra = {"caller": cue.__class__.__name__}
                )
            except KeyError:
                Logger.debug(
                    f'Key error 1 (disconnect) in arm_callback {key}',
                    extra = {"caller": cue.__class__.__name__}
                )

    except AttributeError:
        pass
