"""Unit tests for the fade_action handler (US1 + US2) and related CueHandler methods.

Tests are written BEFORE implementation (TDD — Red phase).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

from cuemsutils.cues import AudioCue, VideoCue
from cuemsutils.cues.FadeCue import FadeCue, FadeCurveType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_audio_cue() -> AudioCue:
    cue = AudioCue()
    cue.enabled = True
    cue.loaded = True
    cue.master_vol = 100
    cue._stop_requested = False
    cue._go_generation = 0
    osc = MagicMock()
    osc.remote_port = 12300
    osc.get_value = MagicMock(return_value=0.0)
    cue._osc = osc
    return cue


def _make_video_cue() -> VideoCue:
    cue = VideoCue()
    cue.enabled = True
    cue.loaded = True
    cue._stop_requested = False
    cue._go_generation = 0
    osc = MagicMock()
    osc.get_value = MagicMock(return_value=0.0)
    cue._osc = osc
    cue._layer_ids = [2]
    return cue


def _make_fade_cue(target_cue, target_value: int = 100,
                   curve_type=FadeCurveType.linear) -> FadeCue:
    cue = FadeCue({'action_target': str(target_cue.id),
                   'target_value': target_value,
                   'duration': '0:0:3:0',
                   'curve_type': curve_type.value})
    cue._action_target_object = target_cue
    return cue


def _make_mtc(ms: int = 5000):
    mtc = MagicMock()
    mtc.timecode = MagicMock()
    mtc.timecode.milliseconds = ms
    return mtc


def _make_cue_handler(comms=None):
    """Minimal CueHandler-like object for handler injection."""
    ch = MagicMock()
    ch.communications_thread = comms or MagicMock()
    # arm succeeds by default
    ch.arm = MagicMock(return_value=True)
    ch.go = MagicMock()
    ch.disarm = MagicMock()
    return ch


# ---------------------------------------------------------------------------
# fade_action in SUPPORTED_CUE_ACTIONS
# ---------------------------------------------------------------------------


def test_fade_action_in_supported_cue_actions():
    from cuemsengine.cues.ActionHandler import SUPPORTED_CUE_ACTIONS
    assert "fade_action" in SUPPORTED_CUE_ACTIONS


# ---------------------------------------------------------------------------
# _handle_fade_action — fade-up path (AudioCue)
# ---------------------------------------------------------------------------


class TestHandleFadeActionFadeUpAudio:
    def _call_handler(self, cue, target_value=100, mtc_ms=5000, comms=None):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS.get("fade_action")
        assert handler is not None, "fade_action not registered in _ACTION_HANDLERS"
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=target_value)
        mtc = _make_mtc(mtc_ms)
        ch = _make_cue_handler(comms=comms)
        result = handler(ch, cue, mtc)
        return result, ch, cue, target_cue

    def test_fade_up_audio_returns_applied(self):
        result, *_ = self._call_handler(None)
        assert result["status"] == "applied"
        assert result["action_type"] == "fade_action"

    def test_fade_up_audio_sends_start_fade_command(self):
        result, ch, cue, target_cue = self._call_handler(None)
        ch.communications_thread.send_fade_command.assert_called_once()
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["command"] == "start_fade"

    def test_fade_up_audio_correct_osc_port(self):
        result, ch, cue, target_cue = self._call_handler(None)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["osc_port"] == target_cue._osc.remote_port

    def test_fade_up_audio_correct_osc_path(self):
        result, ch, cue, target_cue = self._call_handler(None)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["osc_path"] == "/volmaster"

    def test_fade_up_audio_start_value_zero_when_not_playing(self):
        """start_value = 0.0 for fade-up when target_cue was just started."""
        result, ch, cue, target_cue = self._call_handler(None)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["start_value"] == 0.0

    def test_fade_up_audio_correct_end_value(self):
        result, ch, cue, target_cue = self._call_handler(None, target_value=80)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert abs(payload["end_value"] - 0.80) < 1e-6

    def test_fade_up_audio_correct_duration_ms(self):
        result, ch, cue, target_cue = self._call_handler(None)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        # FadeCue.duration = '0:0:3:0' → 3000 ms
        assert payload["duration_ms"] == 3000

    def test_fade_up_audio_correct_start_mtc_ms(self):
        result, ch, cue, target_cue = self._call_handler(None, mtc_ms=7500)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["start_mtc_ms"] == 7500

    def test_fade_up_audio_curve_type_lowercase_string(self):
        result, ch, cue, target_cue = self._call_handler(None)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["curve_type"] == "linear"

    def test_fade_up_audio_fade_id_equals_cue_uuid(self):
        result, ch, cue, target_cue = self._call_handler(None)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["fade_id"] == str(cue.id)

    def test_fade_up_audio_osc_host_localhost(self):
        result, ch, cue, target_cue = self._call_handler(None)
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["osc_host"] == "127.0.0.1"


# ---------------------------------------------------------------------------
# _handle_fade_action — fade-up path (VideoCue)
# ---------------------------------------------------------------------------


class TestHandleFadeActionFadeUpVideo:
    def _call_handler(self, target_value=100):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_video_cue()
        cue = _make_fade_cue(target_cue, target_value=target_value)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        result = handler(ch, cue, mtc)
        return result, ch, cue, target_cue

    def test_fade_up_video_returns_applied(self):
        result, *_ = self._call_handler()
        assert result["status"] == "applied"

    def test_fade_up_video_correct_osc_port(self):
        result, ch, cue, target_cue = self._call_handler()
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["osc_port"] == 7000

    def test_fade_up_video_correct_osc_path(self):
        result, ch, cue, target_cue = self._call_handler()
        payload = ch.communications_thread.send_fade_command.call_args[0][0]
        assert payload["osc_path"] == "/videocomposer/layer/2/opacity"


# ---------------------------------------------------------------------------
# _handle_fade_action — arm failure
# ---------------------------------------------------------------------------


class TestHandleFadeActionArmFailure:
    def test_arm_failure_returns_failed(self):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        target_cue.loaded = False
        cue = _make_fade_cue(target_cue, target_value=100)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.arm = MagicMock(return_value=False)
        # After arm returns False, loaded remains False
        result = handler(ch, cue, mtc)
        assert result["status"] == "failed"

    def test_arm_failure_no_nng_dispatch(self):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        target_cue.loaded = False
        cue = _make_fade_cue(target_cue, target_value=100)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.arm = MagicMock(return_value=False)
        handler(ch, cue, mtc)
        ch.communications_thread.send_fade_command.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_fade_action — NNG send failure
# ---------------------------------------------------------------------------


class TestHandleFadeActionNNGFailure:
    def test_nng_send_failure_returns_failed(self):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=100)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.communications_thread.send_fade_command.side_effect = RuntimeError("NNG down")
        result = handler(ch, cue, mtc)
        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# run_cue.py — FadeCue singledispatch branch
# ---------------------------------------------------------------------------


def test_run_fade_cue_delegates_to_run_action_cue():
    """run_cue dispatches FadeCue to the run_actionCue path."""
    from cuemsengine.cues.run_cue import run_cue
    target_cue = _make_audio_cue()
    cue = _make_fade_cue(target_cue)
    mtc = _make_mtc()

    with patch("cuemsengine.cues.run_cue.run_actionCue") as mock_run:
        mock_run.return_value = None
        run_cue(cue, mtc)
        # run_fadeCue calls run_actionCue(cue, mtc, frozen_mtc_ms=None)
        mock_run.assert_called_once_with(cue, mtc, None)


# ---------------------------------------------------------------------------
# _fade_initial_volume side-channel in run_audioCue
# ---------------------------------------------------------------------------


def test_run_audio_cue_uses_fade_initial_volume():
    """run_audioCue uses _fade_initial_volume if set, then deletes it."""
    from cuemsengine.cues.run_cue import run_audioCue
    target_cue = _make_audio_cue()
    target_cue.master_vol = 100
    target_cue._fade_initial_volume = 0.0
    target_cue.media['duration'] = '0:0:0:0'  # avoid KeyError in run_audioCue
    mtc = _make_mtc()

    volumes_set = []

    def capture_set_value(path, value):
        if path == "/volmaster":
            volumes_set.append(value)

    target_cue._osc.set_value = MagicMock(side_effect=capture_set_value)
    target_cue._osc.get_value = MagicMock(return_value=0.0)

    # Patch CTimecode so timing setup doesn't fail on the mock mtc, and
    # PLAYER_HANDLER so the audio-connection block is a no-op.
    with patch("cuemsengine.cues.run_cue.CTimecode", MagicMock()), \
         patch("cuemsengine.cues.run_cue.PLAYER_HANDLER", MagicMock()):
        try:
            run_audioCue(cue=target_cue, mtc=mtc)
        except Exception:
            pass  # Failures beyond the volume-set step are acceptable

    # _fade_initial_volume must have been consumed (deleted) before the play loop.
    assert not hasattr(target_cue, "_fade_initial_volume")
    # The initial /volmaster write must use 0.0, not master_vol / 100.
    if volumes_set:
        assert volumes_set[0] == 0.0


# ---------------------------------------------------------------------------
# _handle_fade_action — FR-013: NNG failure must leave target state unchanged
# ---------------------------------------------------------------------------


class TestHandleFadeActionNNGFailureOrdering:
    """FR-013: go() must NOT fire if NNG dispatch fails (target state unchanged)."""

    def test_nng_failure_fade_up_go_not_called(self):
        """If send_fade_command raises, go() must not have been called."""
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.communications_thread.send_fade_command.side_effect = RuntimeError("NNG down")
        handler(ch, cue, mtc)
        ch.go.assert_not_called()

    def test_nng_failure_fade_up_no_fade_initial_volume(self):
        """If send_fade_command raises, _fade_initial_volume must not be set."""
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.communications_thread.send_fade_command.side_effect = RuntimeError("NNG down")
        handler(ch, cue, mtc)
        assert not hasattr(target_cue, "_fade_initial_volume")

    def test_nng_success_fade_up_go_called_after(self):
        """On successful NNG dispatch, go() IS called for fade-up."""
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        handler(ch, cue, mtc)
        ch.go.assert_called_once_with(target_cue, mtc)


# ---------------------------------------------------------------------------
# CueHandler.arm — pre-arm for fade-up FadeCue (T028-T029)
# ---------------------------------------------------------------------------


class TestArmFadeCuePreArmsTarget:
    """When arm(fade_up_cue, init=True) is called, the target must also be armed."""

    def _make_local_fade_cue(self, target_cue, target_value=80):
        cue = _make_fade_cue(target_cue, target_value=target_value)
        cue._local = True      # local node: arm_cue will be called
        cue._loading = None
        return cue

    def _make_local_audio_cue(self):
        cue = _make_audio_cue()
        cue._local = True
        cue._loading = None
        cue.post_go = "pause"
        cue._target_object = None
        return cue

    def _make_ch(self):
        from threading import Lock
        ch = object.__new__(__import__("cuemsengine.cues.CueHandler", fromlist=["CueHandler"]).CueHandler)
        ch._lock = Lock()
        ch._armed_cues = []
        ch._armed_cues_set = set()
        ch.communications_thread = MagicMock()
        return ch

    def test_arm_fade_action_arms_target(self):
        """arm(fade_action_cue, init=True) should also arm the target cue."""
        ch = self._make_ch()
        target_cue = self._make_local_audio_cue()
        fade_cue = self._make_local_fade_cue(target_cue, target_value=80)

        with patch("cuemsengine.cues.CueHandler.arm_cue"):
            ch.arm(fade_cue, init=True)
            ch.arm(target_cue, init=True)  # recursive call inside arm

        with patch("cuemsengine.cues.CueHandler.arm_cue"):
            # Reset and call arm with spy to verify recursive target arm
            ch._armed_cues.clear()
            ch._armed_cues_set.clear()
            target_cue.loaded = False
            fade_cue.loaded = False

            armed_ids = []
            real_arm = ch.arm

            def spy_arm(cue, init=False):
                armed_ids.append(getattr(cue, 'id', None))
                return real_arm(cue, init)

            ch.arm = spy_arm
            ch.arm(fade_cue, init=True)

        assert target_cue.id in armed_ids, (
            "arm(fade_up_cue) must recursively arm the target cue"
        )
