#!/usr/bin/env python3

import mido
import os
from typing import Callable
from threading import Thread

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
        super().__init__(name = 'mtclistener')
        self.daemon = True


    def timecode(self):
        return self.main_tc

    def milliseconds(self):
        return int(self.main_tc.frames * (1000 / float(self.main_tc._framerate))) # type: ignore[attr-defined]

    def __update_timecode(self, timecode):
        self.main_tc = timecode
        if (self.main_tc.milliseconds == 0):
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
        return CTimecode('{}:{}:{}:{}'.format(hrs, mins, secs, frs), framerate=fps)

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
