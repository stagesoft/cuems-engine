#!/usr/bin/env python3

import pytest
from unittest.mock import patch, MagicMock
import mido
from cuemsengine.tools.MtcListener import MtcListener
from cuemsutils.tools.CTimecode import CTimecode

class TestMtcListener:
    @pytest.fixture
    def mock_mido(self):
        with patch('mido.get_input_names') as mock_get_names, \
             patch('mido.open_input') as mock_open_input:
            mock_get_names.return_value = ['MTC Port 1', 'MTC Port 2']
            mock_port = MagicMock()
            mock_open_input.return_value = mock_port
            mock_port.close.return_value = None
            yield mock_port

    @pytest.fixture
    def mtc_listener(self, mock_mido):
        step_callback = MagicMock()
        reset_callback = MagicMock()
        listener = MtcListener(
            step_callback=step_callback,
            reset_callback=reset_callback,
            port=1234
        )
        yield listener
        listener.stop()

    def test_initialization(self, mtc_listener):
        """Test that MtcListener initializes correctly"""
        assert mtc_listener.port_name == 1234
        assert mtc_listener.step_callback is not None
        assert mtc_listener.reset_callback is not None
        assert mtc_listener.daemon is True
        assert isinstance(mtc_listener.main_tc, CTimecode)
        assert mtc_listener.main_tc.fraction_frame is True

    def test_timecode_methods(self, mtc_listener):
        """Test timecode and milliseconds methods"""
        # Set a specific timecode
        test_tc = CTimecode('1:2:3:4')
        mtc_listener.main_tc = test_tc
        
        assert mtc_listener.timecode() == test_tc
        assert mtc_listener.milliseconds() == int(test_tc.frames * (1000 / float(test_tc._framerate)))

    def test_quarter_frame_handling(self, mtc_listener):
        """Test handling of quarter frame messages"""
        # Create a quarter frame message
        message = MagicMock()
        message.type = 'quarter_frame'
        message.frame_type = 4
        message.frame_value = 15

        # Call the message handler
        mtc_listener._MtcListener__handle_message(message)

        # Verify quarter frames array was updated
        assert mtc_listener._MtcListener__quarter_frames[4] == 15

    def test_sysex_handling(self, mtc_listener):
        """Test handling of sysex messages"""
        # Create a sysex message with timecode data
        message = MagicMock()
        message.type = 'sysex'
        message.data = (127, 127, 1, 1, 1, 2, 3, 4)  # Hours: 1, Minutes: 2, Seconds: 3, Frames: 4

        # Call the message handler
        mtc_listener._MtcListener__handle_message(message)
        tc = mtc_listener.main_tc
        hours, minutes, seconds, frames = tc.frames_to_tc(tc.frames)

        # Verify timecode was updated
        assert hours == 1
        assert minutes == 2
        assert seconds == 3
        assert frames == 4

    def test_mtc_decoding(self, mtc_listener):
        """Test MTC decoding methods"""
        # Test full frame decoding
        mtc_bytes = (1, 2, 3, 4)  # Hours: 1, Minutes: 2, Seconds: 3, Frames: 4
        tc = mtc_listener._MtcListener__mtc_decode(mtc_bytes)
        hours, minutes, seconds, frames = tc.frames_to_tc(tc.frames)
        
        assert hours == 1
        assert minutes == 2
        assert seconds == 3
        assert frames == 4

        # Test quarter frame decoding
        frame_pieces = [0, 0, 0, 0, 0, 0, 0, 0]
        frame_pieces[0] = 1  # Set frames
        frame_pieces[2] = 2  # Set seconds
        frame_pieces[4] = 3  # Set minutes
        frame_pieces[6] = 4  # Set hours
        
        tc = mtc_listener._MtcListener__mtc_decode_quarter_frames(frame_pieces)
        hours, minutes, seconds, frames = tc.frames_to_tc(tc.frames)
        assert tc is not None
        assert hours == 4
        assert minutes == 3
        assert seconds == 2
        assert frames == 1

    # def test_stop_method(self, mtc_listener, mock_mido):
    #     """Test that stop method closes the port"""
    #     mtc_listener.stop()
    #     mock_mido.mock_port.close.assert_called_once()

    def test_invalid_message_type(self, mtc_listener):
        """Test handling of invalid message types"""
        message = MagicMock()
        message.type = 'invalid_type'
        
        with pytest.raises(NotImplementedError):
            mtc_listener._MtcListener__handle_message(message) 


# ----------------------------------------------------------------------
# 869cyndtv PR #10: 24h rollover detection (closes 869cpdbzy)
# ----------------------------------------------------------------------
class TestMtcListener24hRollover:
    """Layer 2 of PR #10: MtcListener accumulates a 24h offset on each
    detected MIDI MTC rollover so main_tc stays monotonic past 24h.

    MIDI MTC encodes hours in a 5-bit field (max 23) and real SMPTE senders
    reset to 00:00:00:00 after 24h. Without this fix, mtc.main_tc would
    reset to ~frames=1 every 24h regardless of cuemsutils 0.1.0rc7's
    CTimecode-side monotonicity.
    """

    @pytest.fixture
    def mock_mido(self):
        with patch('mido.get_input_names') as mock_get_names, \
             patch('mido.open_input') as mock_open_input:
            mock_get_names.return_value = ['MTC Port 1']
            mock_open_input.return_value = MagicMock()
            yield None

    @pytest.fixture
    def listener(self, mock_mido):
        listener = MtcListener(port='MTC Port 1')
        yield listener

    @pytest.fixture
    def listener_cb(self, mock_mido):
        """Listener WITH step + reset callbacks mocked (for cascade / resync)."""
        step = MagicMock()
        reset = MagicMock()
        l = MtcListener(port='MTC Port 1', step_callback=step, reset_callback=reset)
        l._step_mock = step
        l._reset_mock = reset
        yield l

    def test_initial_state_no_offset(self, listener):
        assert listener._24h_offset_frames == 0
        assert listener._last_decoded_frames is None

    def test_normal_advance_no_offset_accumulated(self, listener):
        # Simulate normal forward MTC progression — no wrap.
        tc1 = CTimecode(framerate=25, frames=1000)
        tc2 = CTimecode(framerate=25, frames=1500)
        adjusted1 = listener._apply_24h_offset(tc1)
        adjusted2 = listener._apply_24h_offset(tc2)
        assert listener._24h_offset_frames == 0
        assert adjusted1.frames == 1000
        assert adjusted2.frames == 1500

    def test_24h_wrap_accumulates_offset_at_25fps(self, listener):
        # Just before the wrap: MTC near 24h.
        FRAMES_24H_25 = 25 * 3600 * 24  # 2_160_000
        pre_wrap = CTimecode(framerate=25, frames=FRAMES_24H_25 - 1)
        listener._apply_24h_offset(pre_wrap)

        # Real MTC senders wrap to 00:00:00:00 after 24h. The MIDI bytes
        # decode to a CTimecode at frames ≈ 1.
        post_wrap_decoded = CTimecode(framerate=25, frames=1)
        adjusted = listener._apply_24h_offset(post_wrap_decoded)

        assert listener._24h_offset_frames == FRAMES_24H_25
        # The adjusted main_tc should land just past 24h, monotonic with
        # the pre-wrap value.
        assert adjusted.frames == 1 + FRAMES_24H_25
        assert adjusted.milliseconds_exact > pre_wrap.milliseconds_exact

    def test_two_24h_wraps_double_offset(self, listener):
        # Walk: just-before-wrap → wrap1 → just-before-wrap → wrap2.
        FRAMES_24H_25 = 25 * 3600 * 24
        listener._apply_24h_offset(CTimecode(framerate=25, frames=FRAMES_24H_25 - 1))
        listener._apply_24h_offset(CTimecode(framerate=25, frames=1))  # wrap 1
        # The previous decoded frames (per heuristic) is the raw decoded
        # frames=1, NOT the offset-adjusted frames. Walk forward to ~24h.
        listener._apply_24h_offset(CTimecode(framerate=25, frames=FRAMES_24H_25 - 1))
        adjusted = listener._apply_24h_offset(CTimecode(framerate=25, frames=1))  # wrap 2

        assert listener._24h_offset_frames == 2 * FRAMES_24H_25
        assert adjusted.frames == 1 + 2 * FRAMES_24H_25

    def test_small_backward_jump_not_treated_as_wrap(self, listener):
        # A manual seek backward by less than 1 hour must not trigger the
        # 24h offset accumulation. Seek behavior is preserved (existing
        # reset detection in __update_timecode handles seek-to-zero).
        tc1 = CTimecode(framerate=25, frames=10000)  # ~6:40 in
        tc2 = CTimecode(framerate=25, frames=100)    # seek back to ~4s
        listener._apply_24h_offset(tc1)
        listener._apply_24h_offset(tc2)
        # delta = -9900 frames = -396s = -0.11h, less than 1 hour
        assert listener._24h_offset_frames == 0

    def test_large_backward_jump_just_under_threshold(self, listener):
        # delta of exactly -1 hour at 25fps = -90000 frames; the threshold
        # is `delta < -frames_per_hour` (strict less-than), so a delta of
        # exactly -90000 should NOT trigger.
        tc1 = CTimecode(framerate=25, frames=100000)
        tc2 = CTimecode(framerate=25, frames=100000 - 90000)  # exactly 1h back
        listener._apply_24h_offset(tc1)
        listener._apply_24h_offset(tc2)
        assert listener._24h_offset_frames == 0

    def test_wrap_at_29_97fps(self, listener):
        # 29.97 DF: the 24h offset MUST be the REAL-rate frame count
        # round(86400*29.97) = 2_589_408 — NOT the label-rate 30*86400 = 2_592_000.
        # The old label-rate value reconverted to 86,486,453 ms (86.5 s too long,
        # desyncing from the C++ ms-domain receiver); the real-rate value
        # reconverts to a true ~86,400,000 ms. (Plan 4 / audit BLOCKER)
        FRAMES_24H_2997 = round(86400.0 * 29.97)
        assert FRAMES_24H_2997 == 2_589_408
        listener._apply_24h_offset(CTimecode(framerate=29.97, frames=FRAMES_24H_2997 - 1))
        adjusted = listener._apply_24h_offset(CTimecode(framerate=29.97, frames=1))
        assert listener._24h_offset_frames == FRAMES_24H_2997
        assert adjusted.frames == 1 + FRAMES_24H_2997
        # Parity with the C++ receiver (DAY_MS = 86_400_000): the post-wrap head
        # is a true 24h in ms (within one frame of rounding), NOT 86,486,453.
        assert abs(adjusted.milliseconds_rounded - 86_400_000) <= 40

    def test_wrap_preserves_polling_loop_termination(self, listener):
        # Bug 869cpdbzy symptom: `while mtc.main_tc.milliseconds_rounded < cue._end_mtc.milliseconds_rounded`
        # would never exit after MTC wrapped (mtc reset to ~0, end_mtc still
        # at large value). With Layer 2 fix, main_tc stays monotonic.
        FRAMES_24H = 25 * 3600 * 24
        # Cue starts just before 24h, runs 30s past 24h.
        cue_start = listener._apply_24h_offset(
            CTimecode(framerate=25, frames=FRAMES_24H - 100)
        )
        cue_end_frames = cue_start.frames + 750  # +30s nominal
        cue_end = CTimecode(framerate=25, frames=cue_end_frames)

        # MTC walks past 24h boundary; we simulate the wrap.
        # Just before wrap.
        mtc_at_wrap_minus_1 = listener._apply_24h_offset(
            CTimecode(framerate=25, frames=FRAMES_24H - 1)
        )
        assert mtc_at_wrap_minus_1.milliseconds_rounded < cue_end.milliseconds_rounded

        # MIDI wraps; raw decoded is ~1; after offset it's at ~24h+1.
        mtc_post_wrap = listener._apply_24h_offset(CTimecode(framerate=25, frames=1))
        assert mtc_post_wrap.milliseconds_rounded > mtc_at_wrap_minus_1.milliseconds_rounded

        # MTC continues to walk; eventually exceeds cue_end → loop terminates.
        mtc_past_end = listener._apply_24h_offset(CTimecode(framerate=25, frames=800))
        assert mtc_past_end.milliseconds_rounded > cue_end.milliseconds_rounded

    # ---------------- Plan 4: reset / control-plane / cascade / resync ----------------

    F24 = 25 * 3600 * 24   # 2_160_000
    FPH = 25 * 3600        # 90_000

    def test_wire_driven_reset_zeroes_active_offset(self, listener):
        # 4.1: after a wrap, an AUTHORITATIVE return to ~0 from a non-boundary
        # previous position zeroes the offset (the wire-driven fallback).
        listener._apply_24h_offset(CTimecode(framerate=25, frames=self.F24 - 50))
        listener._apply_24h_offset(CTimecode(framerate=25, frames=5))   # wrap
        assert listener._24h_offset_frames == self.F24
        # walk to a mid-range position, then jump back into the first hour
        listener._apply_24h_offset(CTimecode(framerate=25, frames=300000))  # ~3.3h raw
        listener._apply_24h_offset(CTimecode(framerate=25, frames=20))      # return ~0
        assert listener._24h_offset_frames == 0

    def test_real_wrap_not_classified_as_reset(self, listener):
        # 4.1 ordering: a genuine 23:59→00:00 wrap must accumulate, not reset
        # (wrap is tested before reset; both fire on delta < -1h).
        listener._apply_24h_offset(CTimecode(framerate=25, frames=self.F24 - 1))
        listener._apply_24h_offset(CTimecode(framerate=25, frames=1))
        assert listener._24h_offset_frames == self.F24

    def test_mid_range_seek_does_not_reset_offset(self, listener):
        # 4.1 guard: a large backward seek NOT landing in the first hour
        # (14h→3h) must leave the offset untouched (decoded.frames < fph is False).
        listener._apply_24h_offset(CTimecode(framerate=25, frames=self.F24 - 50))
        listener._apply_24h_offset(CTimecode(framerate=25, frames=5))   # wrap → offset
        assert listener._24h_offset_frames == self.F24
        listener._apply_24h_offset(CTimecode(framerate=25, frames=25 * 3600 * 14))  # 14h
        before = listener._24h_offset_frames
        listener._apply_24h_offset(CTimecode(framerate=25, frames=25 * 3600 * 3))   # 3h
        assert listener._24h_offset_frames == before   # unchanged (seek, not reset)

    def test_reset_24h_state_clears_both_fields(self, listener):
        # 4.4: control-plane reset zeroes the offset AND the last-pos memory
        # (None sentinel) so the next decode does not re-wrap.
        listener._apply_24h_offset(CTimecode(framerate=25, frames=self.F24 - 50))
        listener._apply_24h_offset(CTimecode(framerate=25, frames=5))
        assert listener._24h_offset_frames == self.F24
        assert listener._last_decoded_frames == 5
        listener.reset_24h_state()
        assert listener._24h_offset_frames == 0
        assert listener._last_decoded_frames is None
        adj = listener._apply_24h_offset(CTimecode(framerate=25, frames=100))
        assert listener._24h_offset_frames == 0
        assert adj.frames == 100

    def test_reset_callback_rearms_after_offset_cleared(self, listener_cb):
        # 4.3: while an offset is live, main_tc >= 24h so reset_callback is
        # silenced; after a control-plane reset, a decode at 0 re-arms it.
        l = listener_cb
        l._apply_24h_offset(CTimecode(framerate=25, frames=self.F24 - 50))
        l._apply_24h_offset(CTimecode(framerate=25, frames=5))   # offset live
        tc_high = l._apply_24h_offset(CTimecode(framerate=25, frames=10))  # >= 24h
        l._MtcListener__update_timecode(tc_high)
        assert l._reset_mock.call_count == 0      # silenced (ms != 0)
        l.reset_24h_state()
        tc_zero = l._apply_24h_offset(CTimecode('00:00:00:00', framerate=25))
        l._MtcListener__update_timecode(tc_zero)
        assert l._reset_mock.call_count == 1      # re-armed (ms == 0)

    def test_periodic_resync_train_no_false_trigger(self, listener_cb):
        # 4.5: libmtcmaster's ~2s periodic full-frame resync (advancing position)
        # must NOT accumulate an offset, must NOT fire reset_callback, and
        # main_tc must stay monotonic.
        l = listener_cb
        prev_ms = -1
        for sec in (2, 4, 6, 8, 10):
            msg = MagicMock()
            msg.type = 'sysex'
            msg.data = (127, 127, 1, 1, (1 << 5) | 0, 0, sec, 0)  # 25fps, 00:00:0s:00
            l._MtcListener__handle_message(msg)
            cur = l.main_tc.milliseconds_rounded
            assert cur >= prev_ms
            prev_ms = cur
        assert l._24h_offset_frames == 0
        assert l._reset_mock.call_count == 0

    def test_resync_fullframe_does_not_flush_qf_buffer(self, listener_cb):
        # 4.2: a full frame (seek or resync) must NOT clear the quarter-frame
        # buffer. Send QF 0..3, a resync full frame mid-sequence, then QF 4..7;
        # all 8 nibbles must survive (a C++-style unconditional flush would zero
        # indices 0..3 and corrupt the next decode).
        l = listener_cb
        def qf(ft, fv):
            m = MagicMock(); m.type = 'quarter_frame'; m.frame_type = ft; m.frame_value = fv
            return m
        def ff(h, mi, s, fr):
            m = MagicMock(); m.type = 'sysex'
            m.data = (127, 127, 1, 1, (1 << 5) | h, mi, s, fr)
            return m
        qf_vals = [0, 1, 2, 3, 4, 5, 6, 7]
        for ft in range(4):
            l._MtcListener__handle_message(qf(ft, qf_vals[ft]))
        l._MtcListener__handle_message(ff(0, 0, 1, 0))   # resync mid-sequence
        for ft in range(4, 8):
            l._MtcListener__handle_message(qf(ft, qf_vals[ft]))
        assert l._MtcListener__quarter_frames == qf_vals
