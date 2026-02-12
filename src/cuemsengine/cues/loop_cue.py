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
    Logger.info(f'Running audio cue loop {cue.id}, cue.loop={cue.loop} (type={type(cue.loop).__name__})')
    
    try:
        loop_counter = 0
        # duration = cue.media.regions[0].out_time - cue.media.regions[0].in_time
        duration = CTimecode(cue.media.duration)
        Logger.info(f'Audio duration: {duration}, _end_mtc: {cue._end_mtc.milliseconds}ms, current MTC: {mtc.main_tc.milliseconds}ms')

        # cue.loop: -1 = infinite, 0 = infinite, positive = fixed count
        while cue.loop < 1 or loop_counter < cue.loop:
            Logger.info(f'Audio loop iteration starting: loop_counter={loop_counter}, cue.loop={cue.loop}')
            
            while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
                sleep(0.02)  # 50Hz polling - responsive but CPU-friendly

            Logger.info(f'Audio iteration {loop_counter + 1} finished (MTC={mtc.main_tc.milliseconds}ms reached _end_mtc={cue._end_mtc.milliseconds}ms)')
            loop_counter += 1
            
            # Only update offset if we're going to loop again (cue.loop < 1 means infinite)
            will_loop_again = cue.loop < 1 or loop_counter < cue.loop
            Logger.info(f'After increment: loop_counter={loop_counter}, will_loop_again={will_loop_again}')
            
            if cue._local and will_loop_again:
                # Recalculate offset and apply for next loop iteration
                cue._start_mtc = CTimecode(start_seconds=mtc.main_tc.milliseconds/1000)
                cue._end_mtc = cue._start_mtc + duration
                # Audio player formula: file_position = MTC + offset
                # To restart from position 0, offset = -start_mtc
                offset_to_go = float(-cue._start_mtc.milliseconds)
                
                Logger.info(f'Restarting audio loop: new _start_mtc={cue._start_mtc.milliseconds}ms, new _end_mtc={cue._end_mtc.milliseconds}ms, offset={offset_to_go}')
                
                try:
                    key = '/offset'
                    cue._osc.set_value(key, offset_to_go)
                    Logger.info(f"Audio offset sent: {offset_to_go}")
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

        Logger.info(f'Audio loop FINISHED: loop_counter={loop_counter}, cue.loop={cue.loop}')

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
    
    Note: xjadeo must have force_redraw on offset change for seamless looping.
    
    Args:
        ossia: The OSC communication interface.
        mtc: The MIDI Time Code interface.
    """
    Logger.info(f'Running video cue loop {cue.id}, cue.loop={cue.loop} (type={type(cue.loop).__name__})')
    
    try:
        loop_counter = 0
        duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
        Logger.info(f'Video duration: {duration}, duration in frames: {duration.frame_number} {duration.framerate}')
        Logger.info(f'Initial _end_mtc: {cue._end_mtc.milliseconds}ms, current MTC: {mtc.main_tc.milliseconds}ms')

        # cue.loop: -1 = infinite, 0 = infinite, positive = fixed count
        while cue.loop < 1 or loop_counter < cue.loop:
            Logger.info(f'Loop iteration starting: loop_counter={loop_counter}, cue.loop={cue.loop}')
            
            # Wait for video iteration to complete
            while mtc.main_tc.milliseconds < cue._end_mtc.milliseconds:
                sleep(0.02)  # 50Hz polling - responsive but CPU-friendly

            Logger.info(f'Video iteration {loop_counter + 1} finished (MTC={mtc.main_tc.milliseconds}ms reached _end_mtc={cue._end_mtc.milliseconds}ms)')
            loop_counter += 1
            
            # Check if we'll loop again (cue.loop < 1 means infinite)
            will_loop_again = cue.loop < 1 or loop_counter < cue.loop
            
            if cue._local and will_loop_again:
                # Update timing for next iteration
                cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=cue._end_mtc.milliseconds/1000)
                cue._end_mtc = cue._start_mtc + duration
                
                # Calculate offset: xjadeo displays frame = MTC_frame + offset
                # To show frame 0 when MTC is at _start_mtc, offset = -_start_mtc.frame_number
                offset_change_frames = - cue._start_mtc.frame_number
                
                Logger.info(f'Loop {loop_counter}: setting offset={offset_change_frames} (MTC={mtc.main_tc.milliseconds}ms, _start_mtc={cue._start_mtc.milliseconds}ms, _end_mtc={cue._end_mtc.milliseconds}ms)')
                
                try:
                    cue._osc.set_value('/jadeo/offset', int(offset_change_frames))
                    Logger.info(f"Offset sent to xjadeo: {offset_change_frames}", extra={"caller": cue.__class__.__name__})
                except Exception as e:
                    Logger.error(f'Offset send failed: {e}', extra={"caller": cue.__class__.__name__})

        Logger.info(f'Loop FINISHED: loop_counter={loop_counter}, cue.loop={cue.loop}')
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
