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
        # Convert duration to MTC framerate to prevent drift when looping (same as video)
        duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
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
                # Update timing for next iteration (same pattern as video)
                cue._start_mtc = CTimecode(framerate=mtc.main_tc.framerate, start_seconds=cue._end_mtc.milliseconds/1000)
                cue._end_mtc = cue._start_mtc + duration
                
                # Audio player formula: file_position = MTC + offset
                # To restart from position 0, offset = -start_mtc
                offset_to_go = float(-cue._start_mtc.milliseconds)
                
                Logger.info(f'Loop {loop_counter}: setting offset={offset_to_go} (MTC={mtc.main_tc.milliseconds}ms, _start_mtc={cue._start_mtc.milliseconds}ms, _end_mtc={cue._end_mtc.milliseconds}ms)')
                
                try:
                    cue._osc.set_value('/offset', offset_to_go)
                    Logger.info(f"Audio offset sent: {offset_to_go}", extra={"caller": cue.__class__.__name__})
                except Exception as e:
                    Logger.error(f'Audio offset send failed: {e}', extra={"caller": cue.__class__.__name__})

        Logger.info(f'Audio loop FINISHED: loop_counter={loop_counter}, cue.loop={cue.loop}')
        if cue._local:
            try:
                cue._osc.set_value('/mtcfollow', 0)
                Logger.info(f"Audio mtcfollow disabled", extra={"caller": cue.__class__.__name__})
            except Exception as e:
                Logger.warning(f'Error disabling mtcfollow: {e}', extra={"caller": cue.__class__.__name__})

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
            # Disable MTC follow when cue ends (same behaviour as audioplayer)
            try:
                cue._osc.set_value('/mtcfollow', 0)
                Logger.info("DMX mtcfollow disabled", extra={"caller": cue.__class__.__name__})
            except Exception as e:
                Logger.warning(f'Error disabling mtcfollow: {e}', extra={"caller": cue.__class__.__name__})
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
    
    Supports multiple video outputs - sends commands to all OSC clients in cue._osc_list.
    
    Note: xjadeo must have force_redraw on offset change for seamless looping.
    
    Args:
        mtc: The MIDI Time Code interface.
    """
    Logger.info(f'Running video cue loop {cue.id}, cue.loop={cue.loop} (type={type(cue.loop).__name__})')
    
    # Get OSC clients for all outputs
    osc_list = getattr(cue, '_osc_list', [cue._osc]) if hasattr(cue, '_osc') else []
    if not osc_list:
        Logger.error(f'No OSC clients available for video cue {cue.id}')
        return
    
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
                
                # Send offset to ALL outputs
                for i, osc_client in enumerate(osc_list):
                    try:
                        osc_client.set_value('/jadeo/offset', int(offset_change_frames))
                        Logger.debug(f"Offset sent to xjadeo output {i}: {offset_change_frames}", extra={"caller": cue.__class__.__name__})
                    except Exception as e:
                        Logger.error(f'Offset send failed on output {i}: {e}', extra={"caller": cue.__class__.__name__})

        Logger.info(f'Loop FINISHED: loop_counter={loop_counter}, cue.loop={cue.loop}')
        if cue._local:
            # Disconnect MIDI on ALL outputs
            for i, osc_client in enumerate(osc_list):
                try:
                    key = '/jadeo/midi/disconnect'
                    osc_client.set_value(key, 1)
                    Logger.debug(f"midi disconnect sent to output {i}", extra={"caller": cue.__class__.__name__})
                except KeyError:
                    Logger.debug(f'Key error (disconnect) in loop_videoCue on output {i}', extra={"caller": cue.__class__.__name__})
        
    except AttributeError:
        pass
