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
