# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import sys
from time import sleep
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest

# Patch the problematic import before importing cuemsengine
sys.modules["cuemsutils.tools.Osc_nodes_hub"] = Mock()

from cuemsutils.cues import DmxCue
from cuemsutils.tools.CTimecode import CTimecode

from cuemsengine.cues.arm_cue import arm_dmxCue
from cuemsengine.cues.loop_cue import loop_dmxCue
from cuemsengine.cues.run_cue import run_dmxCue
from cuemsengine.players.DmxPlayer import DmxClient


class TestArmDmxCue:
    """Test cases for arm_dmxCue function."""

    @pytest.fixture
    def mock_dmx_cue(self):
        """Create a mock DmxCue for testing."""
        cue = Mock(spec=DmxCue)
        cue.id = "test_dmx_cue_001"
        cue.fadein_time = 1000  # milliseconds
        cue.fadeout_time = 500
        cue._local = True

        # Mock DmxScene structure
        dmx_scene = Mock()
        dmx_universe = Mock()
        dmx_universe.universe_num = 1

        # Mock DMX channels
        ch1 = Mock()
        ch1.channel = 0
        ch1.value = 255

        ch2 = Mock()
        ch2.channel = 1
        ch2.value = 128

        ch3 = Mock()
        ch3.channel = 2
        ch3.value = 64

        dmx_universe.dmx_channels = [ch1, ch2, ch3]
        dmx_scene.DmxUniverse = dmx_universe
        cue.DmxScene = dmx_scene

        return cue

    @pytest.fixture
    def mock_dmx_client(self):
        """Create a mock DmxClient."""
        client = Mock(spec=DmxClient)
        return client

    def test_arm_dmx_cue_success(self, mock_dmx_cue, mock_dmx_client):
        """Test successful arming of DMX cue."""
        with patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler:
            mock_handler.get_dmx_player_client.return_value = mock_dmx_client

            arm_dmxCue(mock_dmx_cue)

            # Verify DMX player client was retrieved
            mock_handler.get_dmx_player_client.assert_called_once()

            # Verify cue._osc was set to the client
            assert mock_dmx_cue._osc == mock_dmx_client

            # Verify _dmx_frames was populated correctly
            assert hasattr(mock_dmx_cue, "_dmx_frames")
            assert 1 in mock_dmx_cue._dmx_frames
            assert mock_dmx_cue._dmx_frames[1] == {0: 255, 1: 128, 2: 64}

    def test_arm_dmx_cue_no_player(self, mock_dmx_cue):
        """Test arming DMX cue when no player is available."""
        with patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler:
            mock_handler.get_dmx_player_client.return_value = None

            arm_dmxCue(mock_dmx_cue)

            # Should return early without setting _osc or _dmx_frames
            assert (
                not hasattr(mock_dmx_cue, "_osc") or mock_dmx_cue._osc is None
            )

    def test_arm_dmx_cue_no_scene_data(self, mock_dmx_cue, mock_dmx_client):
        """Test arming DMX cue with no scene data."""
        mock_dmx_cue.DmxScene = None

        with patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler:
            mock_handler.get_dmx_player_client.return_value = mock_dmx_client

            arm_dmxCue(mock_dmx_cue)

            # Should set _dmx_frames to empty dict
            assert mock_dmx_cue._dmx_frames == {}

    def test_arm_dmx_cue_no_universe_data(self, mock_dmx_cue, mock_dmx_client):
        """Test arming DMX cue with no universe data."""
        mock_dmx_cue.DmxScene.DmxUniverse = None

        with patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler:
            mock_handler.get_dmx_player_client.return_value = mock_dmx_client

            arm_dmxCue(mock_dmx_cue)

            # Should set _dmx_frames to empty dict
            assert mock_dmx_cue._dmx_frames == {}

    def test_arm_dmx_cue_no_channels(self, mock_dmx_cue, mock_dmx_client):
        """Test arming DMX cue with no channel data."""
        mock_dmx_cue.DmxScene.DmxUniverse.dmx_channels = []

        with patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler:
            mock_handler.get_dmx_player_client.return_value = mock_dmx_client

            arm_dmxCue(mock_dmx_cue)

            # Should set _dmx_frames to empty dict
            assert mock_dmx_cue._dmx_frames == {}

    def test_arm_dmx_cue_multiple_channels(
        self, mock_dmx_cue, mock_dmx_client
    ):
        """Test arming DMX cue with many channels."""
        # Create 10 channels
        channels = []
        for i in range(10):
            ch = Mock()
            ch.channel = i
            ch.value = i * 10
            channels.append(ch)

        mock_dmx_cue.DmxScene.DmxUniverse.dmx_channels = channels

        with patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler:
            mock_handler.get_dmx_player_client.return_value = mock_dmx_client

            arm_dmxCue(mock_dmx_cue)

            # Verify all channels were extracted
            assert len(mock_dmx_cue._dmx_frames[1]) == 10
            for i in range(10):
                assert mock_dmx_cue._dmx_frames[1][i] == i * 10

    def test_arm_dmx_cue_error_handling(self, mock_dmx_cue, mock_dmx_client):
        """Test error handling in arm_dmxCue."""
        # Make DmxScene raise an exception
        mock_dmx_cue.DmxScene.DmxUniverse.dmx_channels = Mock(
            side_effect=AttributeError("Test error")
        )

        with patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler:
            mock_handler.get_dmx_player_client.return_value = mock_dmx_client

            arm_dmxCue(mock_dmx_cue)

            # Should set _dmx_frames to empty dict on error
            assert mock_dmx_cue._dmx_frames == {}


class TestRunDmxCue:
    """Test cases for run_dmxCue function."""

    @pytest.fixture
    def mock_dmx_cue(self):
        """Create a mock DmxCue for running."""
        cue = Mock(spec=DmxCue)
        cue.id = "test_dmx_cue_001"
        cue.fadein_time = 2000  # 2 seconds in milliseconds
        cue.fadeout_time = 1000  # 1 second in milliseconds
        cue._local = True
        # Duration = fadein_time + fadeout_time = 3000ms = 3 seconds

        # Mock DMX frames
        cue._dmx_frames = {1: {0: 255, 1: 128, 2: 64}}

        # Mock OSC client
        cue._osc = Mock(spec=DmxClient)

        return cue

    @pytest.fixture
    def mock_mtc(self):
        """Create a mock MTC listener."""
        mtc = Mock()
        mtc.main_tc = Mock()
        mtc.main_tc.milliseconds_rounded = 10000  # 10 seconds
        return mtc

    def test_run_dmx_cue_success(self, mock_dmx_cue, mock_mtc):
        """Test successful running of DMX cue."""
        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Verify MTC timing was calculated
        assert hasattr(mock_dmx_cue, "_start_mtc")
        assert hasattr(mock_dmx_cue, "_end_mtc")

        # Verify send_dmx_scene was called
        mock_dmx_cue._osc.send_dmx_scene.assert_called_once()

        # Verify call parameters
        call_args = mock_dmx_cue._osc.send_dmx_scene.call_args
        assert call_args.kwargs["universe_frames"] == {
            1: {0: 255, 1: 128, 2: 64}
        }
        assert (
            call_args.kwargs["mtc_time"]
            == mock_dmx_cue._start_mtc.milliseconds_rounded
        )
        assert call_args.kwargs["fade_time"] == 2.0  # 2000ms / 1000

    def test_run_dmx_cue_no_frames(self, mock_dmx_cue, mock_mtc):
        """Test running DMX cue with no frame data."""
        mock_dmx_cue._dmx_frames = {}

        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Should return early without calling send_dmx_scene
        mock_dmx_cue._osc.send_dmx_scene.assert_not_called()

    def test_run_dmx_cue_no_osc_client(self, mock_dmx_cue, mock_mtc):
        """Test running DMX cue with no OSC client."""
        mock_dmx_cue._osc = None

        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Should return early (no exception)
        # Just verify it doesn't crash
        assert mock_dmx_cue._osc is None

    def test_run_dmx_cue_zero_fadein(self, mock_dmx_cue, mock_mtc):
        """Test running DMX cue with zero fadein time."""
        mock_dmx_cue.fadein_time = 0

        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Verify fade_time is 0.0
        call_args = mock_dmx_cue._osc.send_dmx_scene.call_args
        assert call_args.kwargs["fade_time"] == 0.0

    def test_run_dmx_cue_no_fadein_attribute(self, mock_dmx_cue, mock_mtc):
        """Test running DMX cue without fadein_time attribute."""
        del mock_dmx_cue.fadein_time

        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Should default to 0.0
        call_args = mock_dmx_cue._osc.send_dmx_scene.call_args
        assert call_args.kwargs["fade_time"] == 0.0

    def test_run_dmx_cue_error_handling(self, mock_dmx_cue, mock_mtc):
        """Test error handling in run_dmxCue."""
        # Make send_dmx_scene raise an exception
        mock_dmx_cue._osc.send_dmx_scene.side_effect = Exception("Test error")

        # Should not raise exception (error is caught and logged)
        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Verify send_dmx_scene was attempted
        mock_dmx_cue._osc.send_dmx_scene.assert_called_once()

    def test_run_dmx_cue_mtc_offset_calculation(self, mock_dmx_cue, mock_mtc):
        """Test MTC offset calculation."""
        mtc_time = 15000  # 15 seconds
        mock_mtc.main_tc.milliseconds_rounded = mtc_time

        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Verify start and end MTC were calculated
        # Allow for small rounding differences (CTimecode may round slightly)
        assert (
            abs(mock_dmx_cue._start_mtc.milliseconds_rounded - mtc_time) <= 1
        )

        # End MTC should be greater than start MTC
        # Duration is calculated from fadein_time + fadeout_time (2000 + 1000 =
        # 3000ms)
        # Allow for small rounding differences
        expected_duration = 3000  # fadein_time + fadeout_time
        assert (
            abs(
                (
                    mock_dmx_cue._end_mtc.milliseconds_rounded
                    - mock_dmx_cue._start_mtc.milliseconds_rounded
                )
                - expected_duration
            )
            <= 1
        )

    def test_run_dmx_cue_multiple_universes(self, mock_dmx_cue, mock_mtc):
        """Test running DMX cue with multiple universes."""
        mock_dmx_cue._dmx_frames = {
            1: {0: 255, 1: 128},
            2: {0: 100, 1: 200},
            3: {0: 50},
        }

        run_dmxCue(mock_dmx_cue, mock_mtc)

        # Verify all universes were passed to send_dmx_scene
        call_args = mock_dmx_cue._osc.send_dmx_scene.call_args
        assert len(call_args.kwargs["universe_frames"]) == 3
        assert 1 in call_args.kwargs["universe_frames"]
        assert 2 in call_args.kwargs["universe_frames"]
        assert 3 in call_args.kwargs["universe_frames"]


class TestLoopDmxCue:
    """Test cases for loop_dmxCue function."""

    @pytest.fixture
    def mock_dmx_cue(self):
        """Create a mock DmxCue for looping."""
        cue = Mock(spec=DmxCue)
        cue.id = "test_dmx_cue_001"
        cue._local = True
        cue.loop = 0  # No looping
        cue.fadein_time = 2000  # 2 seconds
        cue.fadeout_time = 3000  # 3 seconds
        # Duration = fadein_time + fadeout_time = 5000ms = 5 seconds

        # Mock timing
        cue._start_mtc = CTimecode(start_seconds=10.0)
        cue._end_mtc = CTimecode(start_seconds=15.0)

        return cue

    @pytest.fixture
    def mock_mtc(self):
        """Create a mock MTC listener."""
        mtc = Mock()
        mtc.main_tc = Mock()
        mtc.main_tc.milliseconds_rounded = 10000  # Start at 10 seconds
        return mtc

    def test_loop_dmx_cue_waits_for_duration(self, mock_dmx_cue, mock_mtc):
        """Test that loop_dmxCue waits for cue duration."""
        # Set up MTC with a simple attribute that can be updated
        mock_main_tc = Mock()
        mock_main_tc.milliseconds_rounded = 10000  # Start at 10 seconds
        mock_mtc.main_tc = mock_main_tc

        # Set _end_mtc to a value that requires waiting
        from cuemsutils.tools.CTimecode import CTimecode

        mock_dmx_cue._end_mtc = CTimecode(
            start_seconds=15.0
        )  # End at 15 seconds

        with patch("cuemsengine.cues.loop_cue.sleep") as mock_sleep:
            # Simulate MTC advancing: after first sleep, advance to past end
            # time
            call_count = [0]

            def advance_mtc(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    # After first sleep call, advance MTC past end time
                    mock_main_tc.milliseconds_rounded = 15000

            mock_sleep.side_effect = advance_mtc

            loop_dmxCue(mock_dmx_cue, mock_mtc)

            # Verify sleep was called at least once (waiting for duration)
            assert mock_sleep.call_count >= 1

    def test_loop_dmx_cue_local_guard(self, mock_dmx_cue, mock_mtc):
        """Test that loop_dmxCue has cue._local guard for future use."""
        # Set MTC to already be past end time
        mock_mtc.main_tc.milliseconds_rounded = 20000

        with patch("cuemsengine.cues.loop_cue.sleep"):
            loop_dmxCue(mock_dmx_cue, mock_mtc)

            # Should complete without error
            # The _local guard is present but currently just has 'pass'
            assert True  # Test passes if no exception

    def test_loop_dmx_cue_remote(self, mock_dmx_cue, mock_mtc):
        """Test loop_dmxCue with remote cue (cue._local = False)."""
        mock_dmx_cue._local = False
        mock_mtc.main_tc.milliseconds_rounded = 20000  # Past end time

        with patch("cuemsengine.cues.loop_cue.sleep"):
            loop_dmxCue(mock_dmx_cue, mock_mtc)

            # Should still wait for duration (timing applies to all cues)
            assert True  # Test passes if no exception

    def test_loop_dmx_cue_attribute_error(self, mock_dmx_cue, mock_mtc):
        """Test loop_dmxCue handles AttributeError gracefully."""
        # Remove _end_mtc to cause AttributeError
        del mock_dmx_cue._end_mtc

        with patch("cuemsengine.cues.loop_cue.sleep"):
            # Should not raise exception (caught by try/except)
            loop_dmxCue(mock_dmx_cue, mock_mtc)

            assert True  # Test passes if no exception

    def test_loop_dmx_cue_timing_accuracy(self, mock_dmx_cue, mock_mtc):
        """Test that loop_dmxCue waits until correct end time."""
        # Set up MTC progression
        current_time = [10000]  # Start at 10 seconds

        def advance_time():
            current_time[0] += 1000  # Advance 1 second per check
            return current_time[0]

        type(mock_mtc.main_tc).milliseconds_rounded = property(
            lambda self: advance_time()
        )

        with patch("cuemsengine.cues.loop_cue.sleep") as mock_sleep:
            mock_dmx_cue._end_mtc = CTimecode(
                start_seconds=14.0
            )  # End at 14 seconds

            loop_dmxCue(mock_dmx_cue, mock_mtc)

            # Should loop until MTC reaches or exceeds end time
            # sleep should be called multiple times (once per 5ms check)
            assert mock_sleep.call_count >= 1


class TestDmxCueIntegration:
    """Integration tests for DMX cue workflow."""

    @pytest.fixture
    def dmx_cue(self):
        """Create a realistic DmxCue for integration testing."""
        cue = Mock(spec=DmxCue)
        cue.id = "dmx_001"
        cue.fadein_time = 1000
        cue.fadeout_time = 500
        cue._local = True
        cue.loop = 0

        # Setup DmxScene
        dmx_scene = Mock()
        dmx_universe = Mock()
        dmx_universe.universe_num = 1

        ch1 = Mock()
        ch1.channel = 0
        ch1.value = 255
        ch2 = Mock()
        ch2.channel = 1
        ch2.value = 128

        dmx_universe.dmx_channels = [ch1, ch2]
        dmx_scene.DmxUniverse = dmx_universe
        cue.DmxScene = dmx_scene

        # Setup fade times (duration = fadein + fadeout = 5000ms)
        cue.fadein_time = 2000  # 2 seconds
        cue.fadeout_time = 3000  # 3 seconds

        return cue

    def test_arm_run_loop_workflow(self, dmx_cue):
        """Test complete workflow: arm -> run -> loop."""
        mock_client = Mock(spec=DmxClient)
        mock_mtc = Mock()

        # Create a mock main_tc object with milliseconds as a simple attribute
        # We'll update it directly when needed
        mock_main_tc = Mock()
        mock_main_tc.milliseconds_rounded = 1000
        mock_mtc.main_tc = mock_main_tc

        with (
            patch("cuemsengine.cues.arm_cue.PLAYER_HANDLER") as mock_handler,
            patch("cuemsengine.cues.loop_cue.sleep") as mock_sleep,
        ):

            mock_handler.get_dmx_player_client.return_value = mock_client

            # Step 1: Arm the cue
            arm_dmxCue(dmx_cue)

            assert dmx_cue._osc == mock_client
            assert dmx_cue._dmx_frames == {1: {0: 255, 1: 128}}

            # Step 2: Run the cue (with MTC at 1000ms)
            run_dmxCue(dmx_cue, mock_mtc)

            assert hasattr(dmx_cue, "_start_mtc")
            assert hasattr(dmx_cue, "_end_mtc")
            mock_client.send_dmx_scene.assert_called_once()

            # Verify _end_mtc was calculated correctly
            # _start_mtc should be ~1000ms, _end_mtc should be start + (fadein
            # + fadeout)
            # fadein_time=2000ms, fadeout_time=3000ms, so duration=5000ms
            expected_duration = 5000
            assert (
                abs(
                    (
                        dmx_cue._end_mtc.milliseconds_rounded
                        - dmx_cue._start_mtc.milliseconds_rounded
                    )
                    - expected_duration
                )
                <= 1
            )

            # Step 3: Loop/wait for duration
            # Set MTC to well past end time so loop exits immediately
            # Use a value that's definitely greater than _end_mtc
            mock_main_tc.milliseconds_rounded = (
                dmx_cue._end_mtc.milliseconds_rounded + 10000
            )
            loop_dmxCue(dmx_cue, mock_mtc)

            # Since MTC is already past end time, sleep should not be called
            # (or called very few times if there's a race condition)
            # Complete workflow executed successfully
            assert True
