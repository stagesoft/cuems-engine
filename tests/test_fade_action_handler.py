"""Unit tests for the fade_action handler (US1) and related CueHandler methods.

Covers (per Phase 6 constraints):
- Single fade_action handler — no fade-up/fade-down distinction.
- Payload built via _build_fade_payload (body fields only); envelope added by NNG layer.
- Handler MUST NOT disarm target_cue, set _fade_initial_volume, or call ch.go.
- FadeCue is NOT registered in run_cue singledispatch — inherits ActionCue branch via MRO.
- CueHandler pre-arms FadeCue.action_target unconditionally.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cuemsutils.cues import AudioCue, VideoCue
from cuemsutils.cues.FadeCue import FadeCue, FadeCurveType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_audio_cue(start_value: float = 0.5) -> AudioCue:
    cue = AudioCue()
    cue.enabled = True
    cue.loaded = True
    cue.master_vol = 100
    cue._stop_requested = False
    cue._go_generation = 0
    osc = MagicMock()
    osc.remote_port = 12300
    osc.get_value = MagicMock(return_value=start_value)
    cue._osc = osc
    return cue


def _make_video_cue(start_value: float = 0.5) -> VideoCue:
    cue = VideoCue()
    cue.enabled = True
    cue.loaded = True
    cue._stop_requested = False
    cue._go_generation = 0
    osc = MagicMock()
    osc.get_value = MagicMock(return_value=start_value)
    cue._osc = osc
    cue._layer_ids = [2]
    return cue


def _make_fade_cue(target_cue, target_value: int = 80,
                   curve_type=FadeCurveType.linear) -> FadeCue:
    cue = FadeCue({'action_target': str(target_cue.id),
                   'target_value': target_value,
                   'duration': '0:0:3:0',
                   'curve_type': curve_type.value})
    cue._action_target_object = target_cue
    return cue


def _make_mtc(ms: int = 5000, framerate: float = 25.0):
    mtc = MagicMock()
    mtc.timecode = MagicMock()
    mtc.timecode.milliseconds_rounded = ms
    mtc.main_tc = MagicMock()
    mtc.main_tc.framerate = framerate
    mtc.main_tc.milliseconds = ms
    return mtc


def _make_cue_handler(comms=None):
    """Minimal CueHandler-like object for handler injection."""
    ch = MagicMock()
    ch.communications_thread = comms or MagicMock()
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
# _build_fade_payload — body construction
# ---------------------------------------------------------------------------


class TestBuildFadePayloadAudio:
    def _build(self, start_value=0.5, target_value=80):
        from cuemsengine.cues.ActionHandler import _build_fade_payload
        target_cue = _make_audio_cue(start_value=start_value)
        fade_cue = _make_fade_cue(target_cue, target_value=target_value)
        payload = _build_fade_payload(target_cue, fade_cue, start_time=1234)
        return payload, target_cue, fade_cue

    def test_audio_osc_port(self):
        payload, target_cue, _ = self._build()
        assert payload["osc_port"] == target_cue._osc.remote_port

    def test_audio_osc_path(self):
        payload, *_ = self._build()
        assert payload["osc_path"] == "/volmaster"

    def test_audio_start_value_from_cache(self):
        """start_value MUST come from target_cue._osc.get_value(osc_path), not from constant."""
        payload, *_ = self._build(start_value=0.42)
        assert payload["start_value"] == 0.42

    def test_audio_target_value_raw_0_100(self):
        """target_value is the raw FadeCue.target_value (NOT normalised to 0–1)."""
        payload, *_ = self._build(target_value=80)
        assert payload["target_value"] == 80

    def test_audio_start_time_passed_through(self):
        from cuemsengine.cues.ActionHandler import _build_fade_payload
        target_cue = _make_audio_cue()
        fade_cue = _make_fade_cue(target_cue)
        payload = _build_fade_payload(target_cue, fade_cue, start_time=7500)
        assert payload["start_time"] == 7500

    def test_audio_duration_ms_from_milliseconds_rounded(self):
        payload, *_ = self._build()
        # FadeCue.duration = '0:0:3:0' → 3000 ms
        assert payload["duration_ms"] == 3000
        assert isinstance(payload["duration_ms"], int)

    def test_audio_curve_type_string(self):
        payload, *_ = self._build()
        assert payload["curve_type"] == "linear"

    def test_no_envelope_fields_in_body(self):
        """body MUST NOT contain envelope fields (added by send_fade_command)."""
        payload, *_ = self._build()
        for envelope_field in ("command", "fade_id", "osc_host", "curve_params"):
            assert envelope_field not in payload


class TestBuildFadePayloadVideo:
    def _build(self, start_value=0.3, target_value=100):
        from cuemsengine.cues.ActionHandler import _build_fade_payload
        target_cue = _make_video_cue(start_value=start_value)
        fade_cue = _make_fade_cue(target_cue, target_value=target_value)
        payload = _build_fade_payload(target_cue, fade_cue, start_time=1234)
        return payload, target_cue, fade_cue

    def test_video_osc_port(self):
        payload, *_ = self._build()
        assert payload["osc_port"] == 7000

    def test_video_osc_path(self):
        payload, *_ = self._build()
        assert payload["osc_path"] == "/videocomposer/layer/2/opacity"

    def test_video_start_value_from_cache(self):
        payload, *_ = self._build(start_value=0.7)
        assert payload["start_value"] == 0.7

    def test_video_target_value_raw(self):
        payload, *_ = self._build(target_value=100)
        assert payload["target_value"] == 100


def test_build_payload_unsupported_target_raises():
    from cuemsengine.cues.ActionHandler import _build_fade_payload
    fake_target = MagicMock(spec=[])  # not Audio/VideoCue
    fade_cue = MagicMock()
    try:
        _build_fade_payload(fake_target, fade_cue, start_time=0)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for unsupported target_cue type")


# ---------------------------------------------------------------------------
# _handle_fade_action — main path
# ---------------------------------------------------------------------------


class TestHandleFadeActionMainPath:
    def _call(self, target_value=80, mtc_ms=5000, start_value=0.5, comms=None):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue(start_value=start_value)
        cue = _make_fade_cue(target_cue, target_value=target_value)
        mtc = _make_mtc(mtc_ms)
        ch = _make_cue_handler(comms=comms)
        result = handler(ch, cue, mtc)
        return result, ch, cue, target_cue

    def test_returns_applied(self):
        result, *_ = self._call()
        assert result["status"] == "applied"
        assert result["action_type"] == "fade_action"

    def test_send_fade_command_called(self):
        result, ch, cue, _ = self._call()
        ch.communications_thread.send_fade_command.assert_called_once()

    def test_send_fade_command_passes_fade_id(self):
        """fade_id MUST be passed as kwarg to send_fade_command, equal to FadeCue.uuid."""
        result, ch, cue, _ = self._call()
        call_args = ch.communications_thread.send_fade_command.call_args
        assert call_args.kwargs.get("fade_id") == str(cue.id)

    def test_send_fade_command_payload_is_body_only(self):
        """Body passed to send_fade_command MUST NOT include envelope fields."""
        result, ch, *_ = self._call()
        body = ch.communications_thread.send_fade_command.call_args[0][0]
        for envelope_field in ("command", "fade_id", "osc_host", "curve_params"):
            assert envelope_field not in body

    def test_handler_does_not_disarm_target(self):
        """fade_action MUST NOT disarm target_cue."""
        result, ch, *_ = self._call()
        ch.disarm.assert_not_called()

    def test_handler_does_not_call_go_on_target(self):
        """fade_action MUST NOT call ch.go(target_cue) (no envelope-from-silence)."""
        result, ch, _, target_cue = self._call()
        # ch.go could be called for other things by other tests; assert not called
        # specifically with target_cue.
        for c in ch.go.call_args_list:
            assert c.args and c.args[0] is not target_cue

    def test_handler_does_not_set_fade_initial_volume(self):
        """target_cue MUST NOT have _fade_initial_volume set by the handler."""
        result, _, _, target_cue = self._call()
        assert not hasattr(target_cue, "_fade_initial_volume")

    def test_handler_sets_end_mtc_on_fade_cue(self):
        """FadeCue._end_mtc MUST be set so loop_fadeCue has an end-time to wait on."""
        result, _, cue, _ = self._call(mtc_ms=5000)
        assert hasattr(cue, "_end_mtc")
        # 5000ms start + 3000ms duration → 8000ms end
        assert cue._end_mtc.milliseconds_rounded == 8000

    def test_handler_sets_start_mtc_on_fade_cue(self):
        result, _, cue, _ = self._call(mtc_ms=5000)
        assert hasattr(cue, "_start_mtc")
        assert cue._start_mtc.milliseconds_rounded == 5000


# ---------------------------------------------------------------------------
# _handle_fade_action — failure paths
# ---------------------------------------------------------------------------


class TestHandleFadeActionFailures:
    def test_arm_failure_returns_failed(self):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        target_cue.loaded = False
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.arm = MagicMock(return_value=False)  # arm fails
        result = handler(ch, cue, mtc)
        assert result["status"] == "failed"

    def test_arm_failure_no_nng_dispatch(self):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        target_cue.loaded = False
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.arm = MagicMock(return_value=False)
        handler(ch, cue, mtc)
        ch.communications_thread.send_fade_command.assert_not_called()

    def test_nng_send_failure_returns_failed(self):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.communications_thread.send_fade_command.side_effect = RuntimeError("NNG down")
        result = handler(ch, cue, mtc)
        assert result["status"] == "failed"

    def test_nng_failure_target_cue_unchanged(self):
        """FR-013: NNG failure must leave target_cue state unchanged."""
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.communications_thread.send_fade_command.side_effect = RuntimeError("NNG down")
        handler(ch, cue, mtc)
        ch.disarm.assert_not_called()
        ch.go.assert_not_called()
        assert not hasattr(target_cue, "_fade_initial_volume")


# ---------------------------------------------------------------------------
# run_cue singledispatch — FadeCue MUST inherit ActionCue branch (no own branch)
# ---------------------------------------------------------------------------


def test_run_cue_has_no_explicit_fade_cue_branch():
    """Per constraint #1, FadeCue MUST NOT have its own run_cue registration."""
    from cuemsengine.cues.run_cue import run_cue
    registry = run_cue.registry
    # Ensure FadeCue is NOT registered as its own type (relies on ActionCue MRO).
    assert FadeCue not in registry, (
        "FadeCue must not have an explicit run_cue branch — "
        "it MUST inherit run_actionCue via singledispatch MRO."
    )


def test_run_cue_fade_cue_resolves_to_run_actionCue():
    """run_cue(FadeCue) MUST dispatch to the ActionCue branch (via MRO)."""
    from cuemsengine.cues.run_cue import run_cue
    target_cue = _make_audio_cue()
    cue = _make_fade_cue(target_cue)
    mtc = _make_mtc()
    with patch("cuemsengine.cues.run_cue.ACTION_HANDLER", create=True) as mock_handler:
        # run_actionCue does `from .ActionHandler import ACTION_HANDLER` lazily;
        # patch the module the import returns.
        with patch("cuemsengine.cues.ActionHandler.ACTION_HANDLER") as mock_ah:
            run_cue(cue, mtc)
            mock_ah.execute_action.assert_called_once_with(cue, mtc)


# ---------------------------------------------------------------------------
# CueHandler.arm — pre-arm of FadeCue.action_target
# ---------------------------------------------------------------------------


class TestArmFadeCuePreArmsTarget:
    """arm(fade_cue, init=True) MUST also arm fade_cue._action_target_object."""

    def _make_local_fade_cue(self, target_cue, target_value=80):
        cue = _make_fade_cue(target_cue, target_value=target_value)
        cue._local = True
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
        from cuemsengine.cues.CueHandler import CueHandler
        ch = object.__new__(CueHandler)
        ch._lock = Lock()
        ch._armed_cues = []
        ch._armed_cues_set = set()
        ch.communications_thread = MagicMock()
        return ch

    def test_arm_fade_action_arms_target(self):
        ch = self._make_ch()
        target_cue = self._make_local_audio_cue()
        fade_cue = self._make_local_fade_cue(target_cue, target_value=80)

        with patch("cuemsengine.cues.CueHandler.arm_cue"):
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
            "arm(fade_cue) must recursively arm the target cue"
        )

    def test_arm_fade_action_arms_target_when_target_value_zero(self):
        """Pre-arm MUST NOT depend on target_value > 0 (constraint #3 unification)."""
        ch = self._make_ch()
        target_cue = self._make_local_audio_cue()
        fade_cue = self._make_local_fade_cue(target_cue, target_value=0)

        with patch("cuemsengine.cues.CueHandler.arm_cue"):
            target_cue.loaded = False
            fade_cue.loaded = False

            armed_ids = []
            real_arm = ch.arm

            def spy_arm(cue, init=False):
                armed_ids.append(getattr(cue, 'id', None))
                return real_arm(cue, init)

            ch.arm = spy_arm
            ch.arm(fade_cue, init=True)

        assert target_cue.id in armed_ids
