"""Unit tests for the fade_action handler (US1) and related CueHandler methods.

Covers (per Phase 6 constraints):
- Single fade_action handler — no fade-up/fade-down distinction.
- _build_fade_payload returns list[dict]: 1 entry for AudioCue, N entries for VideoCue
  (one per layer_id), each carrying its own layer-suffixed fade_id.
- Handler MUST NOT disarm target_cue, set _fade_initial_volume, or call ch.go.
- FadeCue is NOT registered in run_cue singledispatch — inherits ActionCue branch via MRO.
- CueHandler pre-arms FadeCue.action_target unconditionally.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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


def _make_video_cue(start_value: float = 0.5, layer_ids=None) -> VideoCue:
    cue = VideoCue()
    cue.enabled = True
    cue.loaded = True
    cue._stop_requested = False
    cue._go_generation = 0
    osc = MagicMock()
    osc.remote_port = 7000
    osc.get_value = MagicMock(return_value=start_value)
    cue._osc = osc
    cue._layer_ids = list(layer_ids) if layer_ids is not None else [2]
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
    mtc.main_tc.milliseconds_rounded = ms
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
# _build_fade_payload — AudioCue (single-entry list)
# ---------------------------------------------------------------------------


class TestBuildFadePayloadAudio:
    def _build(self, start_value=0.5, target_value=80, fade_id="fade-uuid"):
        from cuemsengine.cues.ActionHandler import _build_fade_payload
        target_cue = _make_audio_cue(start_value=start_value)
        fade_cue = _make_fade_cue(target_cue, target_value=target_value)
        payloads = _build_fade_payload(target_cue, fade_cue, start_mtc_ms=1234,
                                       fade_id=fade_id)
        return payloads, target_cue, fade_cue

    def test_audio_returns_single_entry_list(self):
        payloads, *_ = self._build()
        assert isinstance(payloads, list)
        assert len(payloads) == 1

    def test_audio_fade_id_is_base_fade_id(self):
        """AudioCue uses the base fade_id (no layer suffix — there's only one endpoint)."""
        payloads, *_ = self._build(fade_id="my-fade-uuid")
        assert payloads[0]["fade_id"] == "my-fade-uuid"

    def test_audio_osc_port(self):
        payloads, target_cue, _ = self._build()
        assert payloads[0]["osc_port"] == target_cue._osc.remote_port

    def test_audio_osc_path(self):
        payloads, *_ = self._build()
        assert payloads[0]["osc_path"] == "/volmaster"

    def test_audio_start_value_from_cache(self):
        """start_value MUST come from target_cue._osc.get_value(osc_path)."""
        payloads, *_ = self._build(start_value=0.42)
        assert payloads[0]["start_value"] == 0.42

    def test_audio_end_value_normalised_to_unit_range(self):
        """FadeCue.target_value (UI scale 0-100) is sent as end_value (OSC scale 0.0-1.0)."""
        payloads, *_ = self._build(target_value=80)
        assert payloads[0]["end_value"] == pytest.approx(0.8)
        assert isinstance(payloads[0]["end_value"], float)

    def test_audio_start_time_passed_through(self):
        from cuemsengine.cues.ActionHandler import _build_fade_payload
        target_cue = _make_audio_cue()
        fade_cue = _make_fade_cue(target_cue)
        payloads = _build_fade_payload(target_cue, fade_cue, start_mtc_ms=7500,
                                       fade_id="fid")
        assert payloads[0]["start_mtc_ms"] == 7500

    def test_audio_duration_ms_from_milliseconds_rounded(self):
        payloads, *_ = self._build()
        assert payloads[0]["duration_ms"] == 3000
        assert isinstance(payloads[0]["duration_ms"], int)

    def test_audio_curve_type_string(self):
        payloads, *_ = self._build()
        assert payloads[0]["curve_type"] == "linear"

    def test_audio_no_unwanted_envelope_fields(self):
        """Body MUST NOT contain command, osc_host, curve_params (NNG layer adds those).

        fade_id IS present in each entry so the handler can dispatch per-entry.
        """
        payloads, *_ = self._build()
        for envelope_field in ("command", "osc_host", "curve_params"):
            assert envelope_field not in payloads[0]


# ---------------------------------------------------------------------------
# _build_fade_payload — VideoCue (one entry per layer_id)
# ---------------------------------------------------------------------------


class TestBuildFadePayloadVideoSingleLayer:
    def _build(self, start_value=0.3, target_value=100, layer_ids=(2,),
               fade_id="vid-fade"):
        from cuemsengine.cues.ActionHandler import _build_fade_payload
        target_cue = _make_video_cue(start_value=start_value, layer_ids=layer_ids)
        fade_cue = _make_fade_cue(target_cue, target_value=target_value)
        payloads = _build_fade_payload(target_cue, fade_cue, start_mtc_ms=1234,
                                       fade_id=fade_id)
        return payloads, target_cue, fade_cue

    def test_video_single_layer_one_entry(self):
        payloads, *_ = self._build(layer_ids=(2,))
        assert len(payloads) == 1

    def test_video_single_layer_osc_port(self):
        payloads, *_ = self._build()
        assert payloads[0]["osc_port"] == 7000

    def test_video_single_layer_osc_path(self):
        payloads, *_ = self._build(layer_ids=(2,))
        assert payloads[0]["osc_path"] == "/videocomposer/layer/2/opacity"

    def test_video_single_layer_fade_id_suffixed(self):
        """VideoCue fade_id is suffixed with _{layer_id} even for a single layer."""
        payloads, *_ = self._build(layer_ids=(2,), fade_id="base-uuid")
        assert payloads[0]["fade_id"] == "base-uuid_2"

    def test_video_single_layer_start_value_from_cache(self):
        payloads, *_ = self._build(start_value=0.7)
        assert payloads[0]["start_value"] == 0.7


class TestBuildFadePayloadVideoMultiLayer:
    def _build(self, layer_ids=(0, 2, 5), fade_id="multi-uuid"):
        from cuemsengine.cues.ActionHandler import _build_fade_payload
        target_cue = _make_video_cue(start_value=0.5, layer_ids=layer_ids)
        fade_cue = _make_fade_cue(target_cue, target_value=80)
        payloads = _build_fade_payload(target_cue, fade_cue, start_mtc_ms=1234,
                                       fade_id=fade_id)
        return payloads, target_cue, fade_cue

    def test_video_multi_layer_one_entry_per_layer(self):
        payloads, *_ = self._build(layer_ids=(0, 2, 5))
        assert len(payloads) == 3

    def test_video_multi_layer_osc_paths_per_layer(self):
        payloads, *_ = self._build(layer_ids=(0, 2, 5))
        paths = [p["osc_path"] for p in payloads]
        assert paths == [
            "/videocomposer/layer/0/opacity",
            "/videocomposer/layer/2/opacity",
            "/videocomposer/layer/5/opacity",
        ]

    def test_video_multi_layer_fade_ids_distinct_and_suffixed(self):
        payloads, *_ = self._build(layer_ids=(0, 2, 5), fade_id="base-uuid")
        fade_ids = [p["fade_id"] for p in payloads]
        assert fade_ids == ["base-uuid_0", "base-uuid_2", "base-uuid_5"]

    def test_video_multi_layer_shared_fields(self):
        """end_value, start_mtc_ms, duration_ms, curve_type, osc_port shared across layers."""
        payloads, *_ = self._build(layer_ids=(0, 2, 5))
        for p in payloads:
            assert p["end_value"] == pytest.approx(0.8)
            assert p["start_mtc_ms"] == 1234
            assert p["duration_ms"] == 3000
            assert p["curve_type"] == "linear"
            assert p["osc_port"] == 7000


def test_build_payload_unsupported_target_raises():
    from cuemsengine.cues.ActionHandler import _build_fade_payload
    fake_target = MagicMock(spec=[])  # not Audio/VideoCue
    fade_cue = MagicMock()
    try:
        _build_fade_payload(fake_target, fade_cue, start_mtc_ms=0, fade_id="x")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for unsupported target_cue type")


def test_build_payload_video_no_layer_ids_raises():
    from cuemsengine.cues.ActionHandler import _build_fade_payload
    target_cue = _make_video_cue(layer_ids=[])
    fade_cue = _make_fade_cue(target_cue)
    try:
        _build_fade_payload(target_cue, fade_cue, start_mtc_ms=0, fade_id="x")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for VideoCue with no _layer_ids")


# ---------------------------------------------------------------------------
# _handle_fade_action — main path (AudioCue, single dispatch)
# ---------------------------------------------------------------------------


class TestHandleFadeActionAudio:
    def _call(self, target_value=80, mtc_ms=5000, start_value=0.5, comms=None):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue(start_value=start_value)
        cue = _make_fade_cue(target_cue, target_value=target_value)
        mtc = _make_mtc(mtc_ms)
        ch = _make_cue_handler(comms=comms)
        result = handler(ch, cue, target_cue, mtc)
        return result, ch, cue, target_cue

    def test_returns_applied(self):
        result, *_ = self._call()
        assert result["status"] == "applied"
        assert result["action_type"] == "fade_action"

    def test_send_fade_command_called_once(self):
        result, ch, *_ = self._call()
        assert ch.communications_thread.send_fade_command.call_count == 1

    def test_send_fade_command_passes_base_fade_id(self):
        """AudioCue fade_id is the base FadeCue.uuid (no layer suffix)."""
        result, ch, cue, _ = self._call()
        kwargs = ch.communications_thread.send_fade_command.call_args.kwargs
        assert kwargs.get("fade_id") == str(cue.id)

    def test_send_fade_command_payload_has_no_envelope_or_fade_id(self):
        """Body sent to send_fade_command MUST NOT include envelope fields or fade_id
        (fade_id is passed as kwarg; envelope is added by send_fade_command itself)."""
        result, ch, *_ = self._call()
        body = ch.communications_thread.send_fade_command.call_args[0][0]
        for excluded in ("command", "osc_host", "curve_params", "fade_id"):
            assert excluded not in body

    def test_handler_does_not_disarm_target(self):
        result, ch, *_ = self._call()
        ch.disarm.assert_not_called()

    def test_handler_does_not_call_go_on_target(self):
        result, ch, _, target_cue = self._call()
        for c in ch.go.call_args_list:
            assert c.args and c.args[0] is not target_cue

    def test_handler_does_not_set_fade_initial_volume(self):
        result, _, _, target_cue = self._call()
        assert not hasattr(target_cue, "_fade_initial_volume")

    def test_handler_sets_end_mtc_on_fade_cue(self):
        result, _, cue, _ = self._call(mtc_ms=5000)
        assert hasattr(cue, "_end_mtc")
        assert cue._end_mtc.milliseconds_rounded == 8000

    def test_handler_sets_start_mtc_on_fade_cue(self):
        result, _, cue, _ = self._call(mtc_ms=5000)
        assert hasattr(cue, "_start_mtc")
        assert cue._start_mtc.milliseconds_rounded == 5000


# ---------------------------------------------------------------------------
# _handle_fade_action — VideoCue multi-layer dispatch
# ---------------------------------------------------------------------------


class TestHandleFadeActionVideoMultiLayer:
    def _call(self, layer_ids=(0, 2, 5), mtc_ms=5000):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_video_cue(layer_ids=layer_ids)
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc(mtc_ms)
        ch = _make_cue_handler()
        result = handler(ch, cue, target_cue, mtc)
        return result, ch, cue, target_cue

    def test_returns_applied(self):
        result, *_ = self._call()
        assert result["status"] == "applied"

    def test_send_fade_command_called_per_layer(self):
        result, ch, *_ = self._call(layer_ids=(0, 2, 5))
        assert ch.communications_thread.send_fade_command.call_count == 3

    def test_send_fade_command_fade_ids_layer_suffixed(self):
        result, ch, cue, _ = self._call(layer_ids=(0, 2, 5))
        base = str(cue.id)
        observed = [
            c.kwargs.get("fade_id")
            for c in ch.communications_thread.send_fade_command.call_args_list
        ]
        assert observed == [f"{base}_0", f"{base}_2", f"{base}_5"]

    def test_send_fade_command_osc_paths_per_layer(self):
        result, ch, *_ = self._call(layer_ids=(0, 2, 5))
        paths = [
            c.args[0]["osc_path"]
            for c in ch.communications_thread.send_fade_command.call_args_list
        ]
        assert paths == [
            "/videocomposer/layer/0/opacity",
            "/videocomposer/layer/2/opacity",
            "/videocomposer/layer/5/opacity",
        ]

    def test_send_fade_command_no_fade_id_in_body(self):
        result, ch, *_ = self._call(layer_ids=(0, 2))
        for c in ch.communications_thread.send_fade_command.call_args_list:
            body = c.args[0]
            assert "fade_id" not in body


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
        ch.arm = MagicMock(return_value=False)
        result = handler(ch, cue, target_cue, mtc)
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
        handler(ch, cue, target_cue, mtc)
        ch.communications_thread.send_fade_command.assert_not_called()

    def test_nng_send_failure_returns_failed(self):
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_audio_cue()
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()
        ch.communications_thread.send_fade_command.side_effect = RuntimeError("NNG down")
        result = handler(ch, cue, target_cue, mtc)
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
        handler(ch, cue, target_cue, mtc)
        ch.disarm.assert_not_called()
        ch.go.assert_not_called()
        assert not hasattr(target_cue, "_fade_initial_volume")

    def test_video_nng_failure_aborts_remaining_layers(self):
        """If layer 1 dispatch fails, layers 2..N must NOT be sent."""
        from cuemsengine.cues.ActionHandler import _ACTION_HANDLERS
        handler = _ACTION_HANDLERS["fade_action"]
        target_cue = _make_video_cue(layer_ids=[0, 2, 5])
        cue = _make_fade_cue(target_cue, target_value=80)
        mtc = _make_mtc()
        ch = _make_cue_handler()

        call_count = {"n": 0}
        def flaky_send(payload, fade_id=None, timeout=None):
            call_count["n"] += 1
            if call_count["n"] == 2:  # fail on second layer
                raise RuntimeError("NNG down for layer 2")
        ch.communications_thread.send_fade_command.side_effect = flaky_send

        result = handler(ch, cue, target_cue, mtc)
        assert result["status"] == "failed"
        # Sent layer 0, failed on layer 2, did NOT attempt layer 5.
        assert ch.communications_thread.send_fade_command.call_count == 2


# ---------------------------------------------------------------------------
# run_cue singledispatch — FadeCue MUST inherit ActionCue branch (no own branch)
# ---------------------------------------------------------------------------


def test_run_cue_has_no_explicit_fade_cue_branch():
    """Per constraint #1, FadeCue MUST NOT have its own run_cue registration."""
    from cuemsengine.cues.run_cue import run_cue
    registry = run_cue.registry
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
