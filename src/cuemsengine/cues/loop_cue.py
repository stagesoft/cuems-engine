import time
from functools import singledispatch
from time import sleep

from cuemsutils.cues import ActionCue, AudioCue, CueList, DmxCue, VideoCue
from cuemsutils.cues.Cue import Cue
from cuemsutils.cues.FadeCue import FadeCue
from cuemsutils.log import Logger

from ..tools.MtcListener import MtcListener, CTimecode

# Node-side throttle constant for future cue percentage updates sent to the
# Controller via NNG (Tier 1 of the two-tier throttle strategy).
# Each cue independently limits its update rate to this value.
# At 2 Hz with 5 concurrent cues across 2 remote nodes the Controller receives
# ~20 NNG msg/s (~4 KB/s over LAN) -- well within the NNG receiver budget.
# The Controller applies a second throttle (CUE_BROADCAST_MIN_INTERVAL in
# ControllerEngine) before forwarding updates to the UI via WebSocket (Tier 2).
# To enable percentage updates: uncomment the throttled block inside each
# loop_*Cue polling loop and increase this value if smoother UI is needed.
CUE_STATUS_UPDATE_HZ = 2

@singledispatch
def loop_cue(cue: Cue, mtc: MtcListener):
    """
    Loop a cue based on its type
    """
    pass

@loop_cue.register
def loop_cueList(cue: CueList, mtc: MtcListener):
    """
    Loop a CueList
    """
    pass

@loop_cue.register
def loop_actionCue(cue: ActionCue, mtc: MtcListener):
    """
    Loop an ActionCue
    """
    pass

@loop_cue.register
def loop_fadeCue(cue: FadeCue, mtc: MtcListener):
    """Hold a FadeCue in the cue runner for its full duration.

    The actual fade is driven by gradient-motiond over OSC; this loop simply
    blocks until the FadeCue's _end_mtc is reached so general cue lifecycle
    (auto-disarm of the FadeCue itself in go_threaded's end-of-cue path) only
    fires after the fade has elapsed. _start_mtc / _end_mtc are set by
    ActionHandler._handle_fade_action at dispatch time.
    """
    end_mtc = getattr(cue, '_end_mtc', None)
    if end_mtc is None:
        Logger.warning(f'FadeCue {cue.id} has no _end_mtc; loop_fadeCue exiting immediately')
        return

    while mtc.main_tc.milliseconds_rounded < end_mtc.milliseconds_rounded:
        if getattr(cue, '_stop_requested', False):
            Logger.info(f'FadeCue {cue.id} loop cancelled by stop request')
            return
        sleep(0.02)

@loop_cue.register
def loop_audioCue(cue: AudioCue, mtc: MtcListener):
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
        duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
        Logger.info(f'Audio duration: {duration}, _end_mtc: {cue._end_mtc.milliseconds_rounded}ms, current MTC: {mtc.main_tc.milliseconds_rounded}ms')

        while cue.loop < 1 or loop_counter < cue.loop:
            if cue._stop_requested:
                Logger.info(f'Audio loop {cue.id} cancelled by stop request')
                return
            Logger.info(f'Audio loop iteration starting: loop_counter={loop_counter}, cue.loop={cue.loop}')

            last_status_update = 0.0
            while mtc.main_tc.milliseconds_rounded < cue._end_mtc.milliseconds_rounded:
                if cue._stop_requested:
                    Logger.info(f'Audio loop {cue.id} cancelled by stop request (inner)')
                    return
                sleep(0.02)
                # Future: uncomment to enable percentage progress updates.
                # Throttled to CUE_STATUS_UPDATE_HZ (Tier 1 / node-side).
                # _now = time.monotonic()
                # if _now - last_status_update >= 1.0 / CUE_STATUS_UPDATE_HZ:
                #     last_status_update = _now
                #     _elapsed = mtc.main_tc.milliseconds_rounded - cue._start_mtc.milliseconds_rounded
                #     _total = cue._end_mtc.milliseconds_rounded - cue._start_mtc.milliseconds_rounded
                #     if _total > 0:
                #         _pct = max(1, min(99, int(100 * _elapsed / _total)))
                #         CUE_HANDLER.communications_thread.update_cue(cue.id, _pct, timeout=0.1)

            Logger.info(f'Audio iteration {loop_counter + 1} finished (MTC={mtc.main_tc.milliseconds_rounded}ms reached _end_mtc={cue._end_mtc.milliseconds_rounded}ms)')
            loop_counter += 1
            
            will_loop_again = cue.loop < 1 or loop_counter < cue.loop
            Logger.info(f'After increment: loop_counter={loop_counter}, will_loop_again={will_loop_again}')
            
            if cue._local and will_loop_again:
                cue._start_mtc = CTimecode(framerate=cue._end_mtc.framerate, frames=cue._end_mtc.frames)
                cue._end_mtc = cue._start_mtc + duration

                offset_to_go = float(-cue._start_mtc.milliseconds_rounded)
                
                Logger.info(f'Loop {loop_counter}: setting offset={offset_to_go} (MTC={mtc.main_tc.milliseconds_rounded}ms, _start_mtc={cue._start_mtc.milliseconds_rounded}ms, _end_mtc={cue._end_mtc.milliseconds_rounded}ms)')

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
def loop_dmxCue(cue: DmxCue, mtc: MtcListener):
    """Handle the DMX cue duration wait.
    
    DMX scenes are fire-and-forget (sent once in run_dmxCue), so we only wait 
    for the cue duration to elapse to maintain proper script timing.
    The cue._local guard is maintained for potential future looping implementation.
    
    Args:
        cue: The DmxCue
        mtc: The MIDI Time Code interface
    """
    try:
        last_status_update = 0.0
        while mtc.main_tc.milliseconds_rounded < cue._end_mtc.milliseconds_rounded:
            if cue._stop_requested:
                Logger.info(f'DMX loop {cue.id} cancelled by stop request')
                return
            sleep(0.02)
            # Future: uncomment to enable percentage progress updates.
            # Throttled to CUE_STATUS_UPDATE_HZ (Tier 1 / node-side).
            # _now = time.monotonic()
            # if _now - last_status_update >= 1.0 / CUE_STATUS_UPDATE_HZ:
            #     last_status_update = _now
            #     _elapsed = mtc.main_tc.milliseconds_rounded - cue._start_mtc.milliseconds_rounded
            #     _total = cue._end_mtc.milliseconds_rounded - cue._start_mtc.milliseconds_rounded
            #     if _total > 0:
            #         _pct = max(1, min(99, int(100 * _elapsed / _total)))
            #         CUE_HANDLER.communications_thread.update_cue(cue.id, _pct, timeout=0.1)

        if cue._local:
            pass

        Logger.debug(f'DMX cue {cue.id} duration elapsed')

    except AttributeError:
        pass

@loop_cue.register
def loop_videoCue(cue: VideoCue, mtc: MtcListener):
    """Handle the video media playback loop.
        
    Manages looping behavior for all layers in cue._layer_ids,
    updating offset via the single VideoClient in cue._osc.
    """
    Logger.info(f'Running video cue loop {cue.id}, cue.loop={cue.loop} (type={type(cue.loop).__name__})')
    
    try:
        loop_counter = 0
        duration = CTimecode(cue.media.duration).return_in_other_framerate(mtc.main_tc.framerate)
        Logger.info(f'Video duration: {duration}, duration in frames: {duration.frame_number} {duration.framerate}')
        Logger.info(f'Initial _end_mtc: {cue._end_mtc.milliseconds_rounded}ms, current MTC: {mtc.main_tc.milliseconds_rounded}ms')

        layer_ids = getattr(cue, '_layer_ids', [])

        # Tell the videocomposer this is a looping cue so it wraps frames at the
        # loop boundary (instead of clamping to the last frame).
        for layer_id in layer_ids:
            try:
                cue._osc.set_value(f'/videocomposer/layer/{layer_id}/loop', 1)
            except Exception as e:
                Logger.error(f'Loop enable failed for layer {layer_id}: {e}')

        while cue.loop < 1 or loop_counter < cue.loop:
            if cue._stop_requested:
                Logger.info(f'Video loop {cue.id} cancelled by stop request')
                return
            last_status_update = 0.0
            while mtc.main_tc.milliseconds_rounded < cue._end_mtc.milliseconds_rounded:
                if cue._stop_requested:
                    Logger.info(f'Video loop {cue.id} cancelled by stop request (inner)')
                    return
                sleep(0.02)
                # Future: uncomment to enable percentage progress updates.
                # Throttled to CUE_STATUS_UPDATE_HZ (Tier 1 / node-side).
                # _now = time.monotonic()
                # if _now - last_status_update >= 1.0 / CUE_STATUS_UPDATE_HZ:
                #     last_status_update = _now
                #     _elapsed = mtc.main_tc.milliseconds_rounded - cue._start_mtc.milliseconds_rounded
                #     _total = cue._end_mtc.milliseconds_rounded - cue._start_mtc.milliseconds_rounded
                #     if _total > 0:
                #         _pct = max(1, min(99, int(100 * _elapsed / _total)))
                #         CUE_HANDLER.communications_thread.update_cue(cue.id, _pct, timeout=0.1)

            Logger.info(f'Video iteration {loop_counter + 1} finished (MTC={mtc.main_tc.milliseconds_rounded}ms reached _end_mtc={cue._end_mtc.milliseconds_rounded}ms)')
            loop_counter += 1
            
            will_loop_again = cue.loop < 1 or loop_counter < cue.loop
            
            if cue._local and will_loop_again:
                cue._start_mtc = CTimecode(framerate=cue._end_mtc.framerate, frames=cue._end_mtc.frames)
                cue._end_mtc = cue._start_mtc + duration
                offset_change_frames = -cue._start_mtc.frame_number
                
                Logger.info(f'Loop {loop_counter}: setting offset={offset_change_frames}')

                for layer_id in layer_ids:
                    try:
                        cue._osc.set_value(f'/videocomposer/layer/{layer_id}/offset', int(offset_change_frames))
                    except Exception as e:
                        Logger.error(f'Offset send failed for layer {layer_id}: {e}')

        Logger.info(f'Loop FINISHED: loop_counter={loop_counter}, cue.loop={cue.loop}')
        
    except AttributeError:
        pass
