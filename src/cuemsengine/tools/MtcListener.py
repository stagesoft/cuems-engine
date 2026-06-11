# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

#!/usr/bin/env python3

import mido
import os
from typing import Callable
from threading import Thread, Lock

from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode

# HEADLESS/CLOUD: On servers without an ALSA sequencer (/dev/snd/seq absent)
# switch mido to the JACK-backed rtmidi backend so virtual MIDI ports are
# still accessible.  On hardware nodes with ALSA this block is a no-op.
if not os.path.exists('/dev/snd/seq'):
    mido.set_backend('mido.backends.rtmidi/UNIX_JACK')

class MtcListener(Thread):
    def __init__(self, step_callback: Callable | None = None, reset_callback: Callable | None = None, port: str | None = None):
        # self.main_tc = CTimecode('0:0:0:0')
        self.main_tc = CTimecode()
        self.main_tc.set_fractional(True)

        self.__quarter_frames = [0,0,0,0,0,0,0,0]
        self.port = None
        self.port_name = None
        self.__open_port(port)

        self.step_callback = step_callback
        self.reset_callback = reset_callback

        # 24h MTC rollover state (closes 869cpdbzy):
        # MIDI MTC encodes hours in a 5-bit field (0-23) and real SMPTE senders
        # reset to 00:00:00:00 after 24h. This listener detects that wrap by
        # comparing decoded TC frames against the previous one (a backward jump
        # of more than 1 hour indicates a rollover, not a manual seek) and
        # accumulates a 24h offset that is added to every subsequent decoded
        # TC. CTimecode itself is monotonic past 24h post-cuemsutils 0.1.0rc7
        # (PR #10 layer 1), but without this listener-side accumulation the
        # received MTC would reset to ~frames=1 every 24h regardless.
        self._24h_offset_frames: int = 0
        self._last_decoded_frames: int | None = None
        # Guards _24h_offset_frames + _last_decoded_frames against the race
        # between this listener's mido callback thread (running _apply_24h_offset
        # on every authoritative decode) and the engine's load thread (calling
        # reset_24h_state on project load). The read-modify-write
        # `_24h_offset_frames +=` is NOT atomic under the GIL. Mirrors the C++
        # receiver's wrapStateMutex_.
        self._wrap_lock = Lock()

        super().__init__(name = 'mtclistener')
        self.daemon = True

    def _apply_24h_offset(self, decoded: CTimecode) -> CTimecode:
        """Detect 24h MTC rollover and apply accumulated offset.

        Heuristic: a real 24h wrap goes from 23:59:59:F (frames ≈ 24h - 1f)
        to 00:00:00:00 (frames ≈ 0). We treat a backward jump as a 24h wrap
        only when both:
        - delta < -1h (large backward jump, not a small seek), AND
        - prev_frames was within the last hour of the 24h boundary.

        The second condition is critical: without it, a manual seek back to
        00:00:00:00 from ANY high-watermark MTC time (e.g. after the engine
        has been running for 4h and the user reloads a project, which sends
        a Full-Frame SYSEX SEEK to frame 0) is mistakenly treated as a 24h
        wrap, adding a phantom 2,160,000-frame offset that corrupts every
        downstream timestamp (cue offsets become -2160k, video layers try
        to seek to frame -2.5M of a 300-frame clip, layers stay in
        awaitingFrame forever, monitor goes black).

        For environments with manual seeking, deltas under 1h are treated
        as seeks (no offset accumulated; existing reset detection still
        fires when main_tc.milliseconds_rounded reaches 0).

        Returns the offset-adjusted CTimecode (or the original if no offset
        is active).
        """
        with self._wrap_lock:
            if self._last_decoded_frames is not None:
                delta = decoded.frames - self._last_decoded_frames
                # Real-rate constants, NOT decoded._int_framerate (the LABEL rate,
                # 30 for 29.97). At 29.97 the label rate would make a 24h offset of
                # 30*86400 = 2,592,000 frames, which CTimecode reconverts (÷ the
                # real 29.97) to 86,486,453 ms instead of a true 86,400,000 ms — an
                # 86.5s divergence from the C++ ms-domain receiver. round(...*real)
                # keeps 25/30 fps identical and corrects 29.97. (Plan 4 / audit)
                fps = float(decoded.framerate)
                frames_per_hour = round(3600.0 * fps)
                frames_per_24h = round(86400.0 * fps)
                near_24h_boundary = (
                    self._last_decoded_frames > frames_per_24h - frames_per_hour
                )
                if delta < -frames_per_hour and near_24h_boundary:
                    # 24h MTC rollover: prev was in the last hour of the day and
                    # the head jumped back > 1h → accumulate a full day.
                    self._24h_offset_frames += frames_per_24h
                    Logger.info(
                        f'MtcListener: detected 24h MTC rollover '
                        f'(prev frames={self._last_decoded_frames}, '
                        f'new={decoded.frames}, delta={delta}); '
                        f'accumulated offset = {self._24h_offset_frames} frames '
                        f'({self._24h_offset_frames / fps / 3600:.1f}h)'
                    )
                elif delta < -frames_per_hour and decoded.frames < frames_per_hour:
                    # Transport reset: an authoritative return to ~0 (new pos in
                    # the first hour) from a NON-boundary previous position. The
                    # exact inverse of the wrap predicate, so wrap vs reset stay
                    # mutually exclusive (wrap is tested first). The
                    # `decoded.frames < frames_per_hour` guard is MANDATORY — it
                    # stops a mid-range seek (e.g. 14h→3h) from wrongly zeroing.
                    # Mirrors the C++ applyWrap reset branch (wireMs < HOUR_MS).
                    self._24h_offset_frames = 0
                    Logger.info(
                        f'MtcListener: transport reset to ~0 '
                        f'(prev frames={self._last_decoded_frames}, '
                        f'new={decoded.frames}); cleared 24h offset'
                    )
                elif delta < -frames_per_hour:
                    Logger.info(
                        f'MtcListener: large backward MTC jump ignored as '
                        f'manual seek (prev frames={self._last_decoded_frames}, '
                        f'new={decoded.frames}, delta={delta}); not a 24h wrap '
                        f'(prev < {frames_per_24h - frames_per_hour})'
                    )
            self._last_decoded_frames = decoded.frames

            if self._24h_offset_frames > 0:
                return CTimecode(
                    framerate=decoded.framerate,
                    frames=decoded.frames + self._24h_offset_frames,
                )
            return decoded

    def reset_24h_state(self) -> None:
        """Clear the 24h-wrap accumulator (control-plane reset).

        Called from the engine's project-load/reset orchestration (NOT off the
        wire): a graceful reload sends MTC back toward 0 with only a SMALL
        backward delta, which the wire-driven reset in _apply_24h_offset cannot
        catch (it requires delta < -1h). Without this, a project loaded after a
        >24h run would start at hour 24+ and the cue-sequence reset_callback
        (gated on milliseconds_rounded == 0) would stay silenced forever.

        Zeroes both the offset and the last-position memory (None sentinel,
        mirroring the C++ resetWrapOffset() → lastWireMs_ = -1) under the same
        lock the decode path uses, so it cannot interleave with a concurrent
        wrap accumulation on the callback thread.
        """
        with self._wrap_lock:
            self._24h_offset_frames = 0
            self._last_decoded_frames = None


    def timecode(self):
        return self.main_tc

    def milliseconds(self):
        return int(self.main_tc.frames * (1000 / float(self.main_tc._framerate))) # type: ignore[attr-defined]

    def __update_timecode(self, timecode):
        self.main_tc = timecode
        if (self.main_tc.milliseconds_rounded == 0):
            if self.step_callback != None and self.reset_callback != None:
                self.reset_callback()
        if self.step_callback != None:
            self.step_callback(self.main_tc)

    def __open_port(self, port):
        # HEADLESS/CLOUD: get_input_names() can throw when no MIDI subsystem is
        # present; catch and treat as empty list so the engine keeps running.
        # port_name is left as None and re-detected later in ControllerEngine.start()
        # once the timecode sender has created the virtual MIDI port.
        try:
            ports = mido.get_input_names() # type: ignore[attr-defined]
        except Exception as e:
            Logger.warning(f'Could not list MIDI input ports: {e}')
            ports = []

        if port is not None:
            # Exact match first; fall back to substring match because ALSA/JACK
            # port names include the client name and ID suffix
            # e.g. "Midi Through Port-0" → "Midi Through:Midi Through Port-0 14:0"
            if port in ports:
                self.port_name = port
            else:
                matches = [p for p in ports if port in p]
                if matches:
                    self.port_name = matches[0]
                    Logger.info(f'MIDI port "{port}" matched as "{self.port_name}"')
                else:
                    Logger.warning(f'MIDI port "{port}" not found, auto-detecting...')
                    port = None  # fall through to auto-detect

        if port is None:
            # Prefer ports whose name contains "mtc" (e.g. MtcMaster:MTCPort)
            mtc_ports = [s for s in ports if "mtc" in s.lower()]
            if mtc_ports:
                self.port_name = mtc_ports[-1]
            elif ports:
                self.port_name = ports[-1]
            else:
                # HEADLESS/CLOUD: no ports yet; caller must retry after the
                # virtual MIDI sender port has been created.
                self.port_name = None
                Logger.warning('No MIDI input ports available')
        if self.port_name:
            Logger.info(f'MtcListener will use MIDI port: {self.port_name}')

    def run(self):
        Logger.debug('Starting MTC listener')
        self.port = mido.open_input( # type: ignore[attr-defined]
            self.port_name,
            callback = self.__handle_message
        )
        Logger.info('Listening to MIDI messages on > {} <'.format(self.port_name))

    def stop(self):
        if self.port is not None:
            self.port.close()

    def __handle_message(self, message):
        if message.type == 'quarter_frame':        
            self.__quarter_frames[message.frame_type] = message.frame_value
            if (message.frame_type == 3) or (message.frame_type == 7):
                self.__update_timecode(self.main_tc + 1)
            #    print('QF+:',self.main_tc)
            if message.frame_type == 7:
                tc = self.__mtc_decode_quarter_frames(self.__quarter_frames)
            #    print('QFC:',tc)
                self.__update_timecode(tc)
        elif message.type == 'sysex':
            # check to see if this is a timecode frame
            if len(message.data) == 8 and message.data[0:4] == (127,127,1,1):
                data = message.data[4:]
                tc = self.__mtc_decode(data)
                Logger.debug('FF:' + tc.__str__())
                self.__update_timecode(tc)
                # Deliberately do NOT clear self.__quarter_frames here. Full
                # frames (a seek, or libmtcmaster's ~2s periodic resync) never
                # touch the QF buffer, and the QF decode fires only at
                # frame_type==7 reading all 8 in-order-refreshed indices — so no
                # stale-nibble decode occurs. The C++ receiver clears its decoder
                # state on every full frame, but that resets C++-only
                # sequence-validity fields (qfCount/direction/flags) this
                # index-based decoder lacks; flushing here would instead corrupt
                # the next decode when a resync lands mid-QF-sequence. (Plan 4)
        else:
            Logger.debug(message)
            raise(NotImplementedError)
    
    def __mtc_decode(self, mtc_bytes):
        #print(mtc_bytes)
        rhh, mins, secs, frs = mtc_bytes
        rateflag = rhh >> 5
        hrs      = rhh & 31
        fps = ['24','25','29.97','30'][rateflag]
        # total_frames = frs + float(fps) * (secs + mins * 60 + hrs * 60 * 60) //  TODO: goes to frame 0 in tc, non existent frame, changed to tc 0:0:0:0 = frame 1
        decoded = CTimecode('{}:{}:{}:{}'.format(hrs, mins, secs, frs), framerate=fps)
        # Route through 24h-wrap detection so main_tc stays monotonic past 24h.
        # See _apply_24h_offset docstring for heuristic details (closes 869cpdbzy).
        return self._apply_24h_offset(decoded)

    def __mtc_decode_full_frame(self, full_frame_bytes):
        mtc_bytes = full_frame_bytes[5:-1]
        return self.__mtc_decode(mtc_bytes)

    def __mtc_decode_quarter_frames(self, frame_pieces):
        mtc_bytes = bytearray(4)
        if len(frame_pieces) < 8:
            return None
        for piece in range(8):
            mtc_index = 3 - piece//2    # quarter frame pieces are in reverse order of mtc_encode
            this_frame = frame_pieces[piece]
            if this_frame is bytearray or this_frame is list:
                this_frame = this_frame[1] # type: ignore[index]
            # ignore the frame_piece marker bits
            data = this_frame & 15      # type: ignore[operator]
            if piece % 2 == 0:
                # 'even' pieces came from the low nibble
                # and the first piece is 0, so it's even
                mtc_bytes[mtc_index] += data
            else:
                # 'odd' pieces came from the high nibble
                mtc_bytes[mtc_index] += data * 16
        return self.__mtc_decode(mtc_bytes)
