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
                sleep(0.02)  # 50Hz polling - responsive but CPU-friendly

            loop_counter += 1
            
            # Only update offset if we're going to loop again
            if cue._local and (not cue.loop or loop_counter < cue.loop):
                # Recalculate offset and apply for next loop iteration
                cue._start_mtc = CTimecode(start_seconds=mtc.main_tc.milliseconds/1000)
                cue._end_mtc = cue._start_mtc + duration
                # Audio player formula: file_position = MTC + offset
                # To restart from position 0, offset = -start_mtc
                offset_to_go = float(-cue._start_mtc.milliseconds)
                try:
                    key = '/offset'
                    cue._osc.set_value(key, offset_to_go)
                except KeyError:
                    Logger.debug(
                        f'Key error 3 in go_callback {key}',
                        extra = {"caller": cue.__class__.__name__}
                    )

        if cue._local:                
            try:
                key = '/mtcfollow'
                cue._osc.set_value(key, 0)
            except KeyError:
                Logger.debug(
                    f'Key error 4 in go_callback {key}',
                    extra = {"caller": cue.__class__.__name__}
                )

        Logger.debug(f'loop finished with Loop counter: {loop_counter} and set loop {cue.loop}')

    except AttributeError:
        pass

@loop_cue.register
def loop_dmxCue(cue: DmxCue, mtc):
    """Handle the DMX cue duration wait.
    
    DMX scenes are fire-and-forget (sent once in run_dmxCue), so we only wait 
    for the cue duration to elapse to maintain proper script timing.
    The cue._local guard is maintained for potential future looping implementation.
    
    Args:
        cue: The DmxCue
        mtc: The MIDI Time Code interface
    """
    try:
        # Wait for the cue duration to elapse
        while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
            sleep(0.02)  # 50Hz polling - responsive but CPU-friendly

        if cue._local:
            # Reserved for future looping implementation
            # Currently DMX scenes are sent once in run_dmxCue
            pass

        Logger.debug(f'DMX cue {cue.id} duration elapsed')

    except AttributeError:
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
    Logger.info(f'Running video cue loop {cue.id}')
    
    try:
        loop_counter = 0
        duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
        Logger.debug(f'Video duration: {duration}, duration in frames: {duration.frame_number} {duration.framerate}, ')
        # duration = cue.media.regions[0].out_time - cue.media.regions[0].in_time
        # duration = duration.return_in_other_framerate(mtc.main_tc.framerate)
        #in_time_adjusted = cue.media.regions[0].in_time.return_in_other_framerate(mtc.main_tc.framerate)

        while not cue.loop or loop_counter < cue.loop:
            while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
                sleep(0.02)  # 50Hz polling - responsive but CPU-friendly

            loop_counter += 1
            
            # Only update offset if we're going to loop again
            if cue._local and (not cue.loop or loop_counter < cue.loop):
                cue._start_mtc = mtc.main_tc
                cue._end_mtc = cue._start_mtc + duration
                offset_to_go = - (cue._start_mtc.frame_number)
                
                # Set new offset via pyossia OSC
                try:
                    cue._osc.set_value('/jadeo/offset.1', int(offset_to_go))
                    Logger.info(f"offset: {offset_to_go}", extra={"caller": cue.__class__.__name__})
                except Exception as e:
                    Logger.error(
                        f'offset failed: {e}',
                        extra = {"caller": cue.__class__.__name__}
                    )

        Logger.debug(f'loop finished with Loop counter: {loop_counter} and set loop {cue.loop}')
        if cue._local:
            try:
                key = '/jadeo/midi/disconnect'
                cue._osc.set_value(key, 1)
                Logger.info(
                    f"midi disconnect result: {str(cue._osc.get_value(key))}",
                    extra = {"caller": cue.__class__.__name__}
                )
            except KeyError:
                Logger.debug(
                    f'Key error (disconnect) in loop_videoCue {key}',
                    extra = {"caller": cue.__class__.__name__}
                )
        
    except AttributeError:
        pass
