# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""A video cue aimed at an output this node doesn't drive must stay dark.

869fgq3xv. The node drops every output with no region in display.conf at
start (DISPLAY_MISMATCH). A cue aimed at one used to be loaded anyway; with no
position/scale the videocomposer letterboxed it onto the whole canvas, i.e.
across the screens that DO work. Now the layer of an unrouted output is never
loaded, the cue keeps its place on the timeline (follows, announces and loops
behave as if it played), and the operator is told at load and at arm.

A resolved output whose position/scale send fails still plays (869f8hfra):
that is tests/unit/test_video_placement_failure.py.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import AudioCue, VideoCue

from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

LOAD = "/videocomposer/layer/load"
LOAD_SHARED = "/videocomposer/layer/load_shared"


@pytest.fixture(autouse=True)
def _fresh_unrouted_warnings():
    PLAYER_HANDLER.reset_unrouted_warnings()
    yield
    PLAYER_HANDLER.reset_unrouted_warnings()


def _make_video_cue(name="Intro") -> VideoCue:
    cue = VideoCue()
    cue.name = name
    cue.media = {"file_name": "clip.mp4", "duration": "00:00:10.000"}
    return cue


def _output(placement=(0, 0), scale=(0.5, 0.5)):
    output = MagicMock()
    output.get_layer_placement.return_value = placement
    output.get_layer_scale.return_value = scale
    return output


def _resolver(outputs: dict):
    """resolve_video_output_for_cue stand-in: a VideoOutput or an exception
    per output name."""

    def resolve(cue, output_name):
        value = outputs[output_name]
        if isinstance(value, BaseException):
            raise value
        return value

    return resolve


def _arm(cue, outputs: dict):
    from cuemsengine.cues.arm_cue import arm_videoCue

    client = MagicMock()
    with (
        patch.object(PLAYER_HANDLER, "get_video_client", return_value=client),
        patch.object(
            PLAYER_HANDLER, "get_all_cue_output_names", return_value=list(outputs)
        ),
        patch.object(PLAYER_HANDLER, "media_path", return_value="/media/clip.mp4"),
        patch.object(PLAYER_HANDLER, "media_dimensions", return_value=(1920, 1080)),
        patch.object(
            PLAYER_HANDLER,
            "resolve_video_output_for_cue",
            side_effect=_resolver(outputs),
        ),
        patch.object(PLAYER_HANDLER, "register_layer"),
        patch("cuemsengine.cues.arm_cue.Logger") as logger,
        patch("cuemsengine.players.PlayerHandler.Logger"),
    ):
        arm_videoCue(cue)
    return client, logger


def _mtc():
    mtc = MagicMock()
    mtc.main_tc.framerate = 25
    return mtc


def _run(cue, outputs: dict):
    from cuemsengine.cues.run_cue import run_videoCue

    with (
        patch.object(PLAYER_HANDLER, "media_dimensions", return_value=(1920, 1080)),
        patch.object(
            PLAYER_HANDLER,
            "resolve_video_output_for_cue",
            side_effect=_resolver(outputs),
        ),
        patch("cuemsengine.cues.run_cue.Logger") as logger,
    ):
        run_videoCue(cue, _mtc(), frozen_mtc_ms=1000.0)
    return logger


def _paths(client, path):
    return [c.args[1] for c in client.set_value.call_args_list if c.args[0] == path]


def _messages(mock_method):
    return [str(c.args[0]) for c in mock_method.call_args_list]


# ---------------------------------------------------------------------------
# Arm: unrouted outputs are never loaded
# ---------------------------------------------------------------------------


class TestArmSkipsUnroutedOutputs:
    def test_single_unrouted_output_loads_nothing(self):
        cue = _make_video_cue()
        client, logger = _arm(cue, {"2": KeyError("2")})
        assert _paths(client, LOAD) == []
        assert _paths(client, LOAD_SHARED) == []
        assert cue._layer_ids == []
        assert cue._layer_outputs == {}
        assert cue._unrouted_outputs == ["2"]
        errors = [m for m in _messages(logger.error) if "stays dark" in m]
        assert len(errors) == 1
        assert str(cue.id) in errors[0] and '"2"' in errors[0]
        assert "Intro" in errors[0]

    def test_dead_first_output_moves_the_driver_to_the_first_routed_one(self):
        cue = _make_video_cue()
        client, _ = _arm(cue, {"2": KeyError("2"), "0": _output(), "1": _output()})
        assert _paths(client, LOAD) == [["/media/clip.mp4", f"{cue.id}_1"]]
        assert _paths(client, LOAD_SHARED) == [
            ["/media/clip.mp4", f"{cue.id}_2", f"{cue.id}_1"]
        ]
        assert cue._layer_ids == [f"{cue.id}_1", f"{cue.id}_2"]
        assert cue._layer_outputs == {f"{cue.id}_1": "0", f"{cue.id}_2": "1"}
        assert cue._unrouted_outputs == ["2"]

    def test_dead_middle_output_keeps_the_ids_of_the_others(self):
        cue = _make_video_cue()
        client, _ = _arm(cue, {"0": _output(), "2": KeyError("2"), "1": _output()})
        assert _paths(client, LOAD) == [["/media/clip.mp4", f"{cue.id}_0"]]
        assert _paths(client, LOAD_SHARED) == [
            ["/media/clip.mp4", f"{cue.id}_2", f"{cue.id}_0"]
        ]
        assert cue._layer_outputs == {f"{cue.id}_0": "0", f"{cue.id}_2": "1"}

    @pytest.mark.parametrize(
        "error",
        [
            KeyError("2"),
            KeyError("No VideoCueOutput match for node_custom_0"),
            RuntimeError("Cannot resolve canvas dimensions"),
            ValueError("cannot convert float NaN to integer"),
            TypeError("'NoneType' object is not iterable"),
        ],
        ids=[
            "alias",
            "custom-no-match",
            "no-canvas",
            "unexpected-value",
            "unexpected-type",
        ],
    )
    def test_any_resolver_failure_is_unrouted_and_never_escapes_the_arm(self, error):
        cue = _make_video_cue()
        client, _ = _arm(cue, {"0": error, "1": _output()})
        assert cue._unrouted_outputs == ["0"]
        assert cue._layer_ids == [f"{cue.id}_1"]
        assert _paths(client, LOAD) == [["/media/clip.mp4", f"{cue.id}_1"]]

    def test_unrouted_layers_are_not_counted_as_placement_failures(self):
        cue = _make_video_cue()
        _arm(cue, {"2": KeyError("2"), "0": _output()})
        assert cue._placement_failed == []

    def test_placement_failure_on_a_routed_output_still_loads_it(self):
        """869f8hfra stays: a resolved output whose position send fails plays."""
        cue = _make_video_cue()
        broken = _output()
        broken.get_layer_placement.side_effect = KeyError("width")
        client, logger = _arm(cue, {"0": broken})
        assert cue._layer_ids == [f"{cue.id}_0"]
        assert cue._unrouted_outputs == []
        assert cue._placement_failed == [f"{cue.id}_0"]
        assert [m for m in _messages(logger.error) if "NOT applied" in m]

    def test_a_rearm_resets_every_list_even_when_nothing_is_routed(self):
        cue = _make_video_cue()
        cue._placement_failed = ["stale"]
        cue._layer_ids = ["stale"]
        cue._layer_outputs = {"stale": "9"}
        cue._unrouted_outputs = ["9"]
        _arm(cue, {"2": KeyError("2")})
        assert cue._placement_failed == []
        assert cue._layer_ids == []
        assert cue._layer_outputs == {}
        assert cue._unrouted_outputs == ["2"]

    def test_the_error_is_logged_once_per_load_then_at_debug(self):
        cue = _make_video_cue()
        _, first = _arm(cue, {"2": KeyError("2")})
        _, second = _arm(cue, {"2": KeyError("2")})
        assert [m for m in _messages(first.error) if "stays dark" in m]
        assert not [m for m in _messages(second.error) if "stays dark" in m]
        assert [m for m in _messages(second.debug) if "stays dark" in m]
        PLAYER_HANDLER.reset_unrouted_warnings()  # what each load does
        _, third = _arm(cue, {"2": KeyError("2")})
        assert [m for m in _messages(third.error) if "stays dark" in m]


# ---------------------------------------------------------------------------
# Run: the timeline is stamped even with zero layers; layers map by id
# ---------------------------------------------------------------------------


class TestRunDarkCue:
    def _dark_cue(self):
        cue = _make_video_cue()
        _arm(cue, {"2": KeyError("2")})
        cue._osc = MagicMock()
        return cue

    def test_a_dark_cue_sends_nothing_but_keeps_its_timeline(self):
        cue = self._dark_cue()
        logger = _run(cue, {"2": KeyError("2")})
        cue._osc.set_value.assert_not_called()
        assert cue._start_mtc.milliseconds_exact == pytest.approx(1000.0)
        assert cue._end_mtc.milliseconds_exact == pytest.approx(11000.0)
        infos = [m for m in _messages(logger.info) if "dark on this node" in m]
        assert len(infos) == 1
        assert not [m for m in _messages(logger.error) if "no layers" in m]

    def test_the_auto_follow_instant_is_the_end_not_the_start(self):
        """Before 869fgq3xv a zero-layer cue left _end_mtc at zero, so the
        follow fired at start + postwait, cluster-wide (review F1)."""
        from cuemsengine.cues.CueHandler import CueHandler

        cue = self._dark_cue()
        cue.postwait = "00:00:02.000"
        _run(cue, {"2": KeyError("2")})
        instant = CueHandler._follow_instant_ms(cue, 1000.0)
        assert instant == pytest.approx(11000.0 + 2000.0)

    def test_reveal_sends_nothing_for_a_dark_cue(self):
        from cuemsengine.cues.run_cue import reveal_videoCue

        cue = self._dark_cue()
        reveal_videoCue(cue, _mtc())
        cue._osc.set_value.assert_not_called()

    def test_a_counted_loop_with_no_layers_finishes_without_sending(self):
        from cuemsengine.cues.loop_cue import loop_videoCue

        cue = self._dark_cue()
        _run(cue, {"2": KeyError("2")})
        cue.loop = 2
        cue._local = True
        cue._stop_requested = False
        mtc = MagicMock()
        mtc.main_tc.framerate = 25
        mtc.main_tc.milliseconds_rounded = 10**9  # past every end
        with patch("cuemsengine.cues.loop_cue.Logger"):
            loop_videoCue(cue, mtc)
        cue._osc.set_value.assert_not_called()

    def test_no_layers_and_nothing_unrouted_is_still_an_error(self):
        cue = _make_video_cue()
        cue._layer_ids = []
        cue._osc = MagicMock()
        logger = _run(cue, {})
        assert [m for m in _messages(logger.error) if "no layers" in m]


class TestRunMapsLayersById:
    def test_reapply_uses_each_layers_own_output(self):
        cue = _make_video_cue()
        out0, out1 = _output(placement=(-960, 0)), _output(placement=(960, 0))
        _arm(cue, {"0": out0, "2": KeyError("2"), "1": out1})
        cue._osc = MagicMock()
        _run(cue, {"0": out0, "2": KeyError("2"), "1": out1})
        positions = {
            c.args[0]: c.args[1]
            for c in cue._osc.set_value.call_args_list
            if c.args[0].endswith("/position")
        }
        assert positions == {
            f"/videocomposer/layer/{cue.id}_0/position": [-960, 0],
            f"/videocomposer/layer/{cue.id}_2/position": [960, 0],
        }

    def test_a_layer_without_a_recorded_output_warns_and_skips(self):
        cue = _make_video_cue()
        cue._layer_ids = [f"{cue.id}_0"]
        cue._layer_outputs = {}
        cue._osc = MagicMock()
        logger = _run(cue, {})
        assert [m for m in _messages(logger.warning) if "re-apply skipped" in m]
        assert not [
            c
            for c in cue._osc.set_value.call_args_list
            if c.args[0].endswith("/position")
        ]


# ---------------------------------------------------------------------------
# CueHandler.arm publishes a dark cue: no GO-gate hold, no fallback re-arm
# ---------------------------------------------------------------------------


def test_cue_handler_publishes_a_dark_cue_as_armed():
    from cuemsengine.cues.CueHandler import CUE_HANDLER

    cue = _make_video_cue()
    cue.enabled = True
    cue.loaded = False
    cue._local = True
    cue._target_object = None
    with (
        patch.object(PLAYER_HANDLER, "get_video_client", return_value=MagicMock()),
        patch.object(PLAYER_HANDLER, "get_all_cue_output_names", return_value=["2"]),
        patch.object(PLAYER_HANDLER, "media_path", return_value="/media/clip.mp4"),
        patch.object(PLAYER_HANDLER, "media_dimensions", return_value=(1920, 1080)),
        patch.object(
            PLAYER_HANDLER, "resolve_video_output_for_cue", side_effect=KeyError("2")
        ),
    ):
        result = CUE_HANDLER.arm(cue, init=True)
    try:
        assert result is True
        assert cue.loaded is True
        assert cue._layer_ids == []
    finally:
        CUE_HANDLER.disarm(cue)


# ---------------------------------------------------------------------------
# Load-time preflight (NodeEngine.check_unrouted_video_outputs)
# ---------------------------------------------------------------------------

NE = "cuemsengine.NodeEngine"


def _node(cues: list, outputs_map: dict):
    from cuemsengine.NodeEngine import NodeEngine

    node = object.__new__(NodeEngine)
    by_id = {c.id: c for c in cues}
    node.script = MagicMock()
    node.script.find.side_effect = lambda cue_id: by_id.get(cue_id)
    node.outputs_map = outputs_map
    return node


def _video(name, enabled=True):
    cue = _make_video_cue(name)
    cue.enabled = enabled
    return cue


class TestLoadPreflight:
    def _check(self, node, resolve, video_client=True):
        with (
            patch.object(
                PLAYER_HANDLER,
                "get_video_client",
                return_value=MagicMock() if video_client else None,
            ),
            patch.object(
                PLAYER_HANDLER, "resolve_video_output_for_cue", side_effect=resolve
            ),
            patch.object(
                PLAYER_HANDLER, "driven_video_outputs", return_value=["0=HDMI-A-1"]
            ),
            patch(f"{NE}.Logger") as logger,
            patch("cuemsengine.players.PlayerHandler.Logger"),
        ):
            found = node.check_unrouted_video_outputs()
        return found, logger

    def test_names_only_enabled_video_cues_aimed_at_dead_outputs(self):
        lit, dark, disabled = (
            _video("Lit"),
            _video("Dark"),
            _video("Off", enabled=False),
        )
        audio = AudioCue()
        node = _node(
            [lit, dark, disabled, audio],
            {lit.id: ["0"], dark.id: ["2"], disabled.id: ["2"], audio.id: ["2"]},
        )
        found, logger = self._check(
            node, _resolver({"0": _output(), "2": KeyError("2")})
        )
        assert [c["cue_id"] for c in found] == [dark.id]
        warnings = [
            m
            for m in _messages(logger.warning)
            if m.startswith("UNROUTED_VIDEO_OUTPUT:")
        ]
        assert len(warnings) == 1
        assert str(dark.id) in warnings[0] and "Dark" in warnings[0]
        assert "0=HDMI-A-1" in warnings[0]

    def test_a_clean_load_says_nothing(self):
        lit = _video("Lit")
        node = _node([lit], {lit.id: ["0"]})
        found, logger = self._check(node, _resolver({"0": _output()}))
        assert found == []
        assert not [m for m in _messages(logger.warning) if "UNROUTED" in m]

    def test_a_node_without_a_video_stack_gets_one_summary_line(self):
        a, b = _video("A"), _video("B")
        node = _node([a, b], {a.id: ["0"], b.id: ["1"]})
        found, logger = self._check(node, _resolver({}), video_client=False)
        warnings = _messages(logger.warning)
        assert len(warnings) == 1
        assert "no video stack" in warnings[0] and "2 video cue(s)" in warnings[0]
        assert "UNROUTED_VIDEO_OUTPUT" not in warnings[0]

    def test_a_broken_entry_never_aborts_the_load(self):
        node = _node([], {})
        node.script.find.side_effect = RuntimeError("boom")
        node.outputs_map = {"x": ["0"]}
        found, logger = self._check(node, _resolver({}))
        assert found == []
        assert logger.exception.called or logger.error.called

    def test_the_preflight_resets_the_once_per_load_arm_errors(self):
        PLAYER_HANDLER.first_unrouted_report("cue", "2")
        node = _node([], {})
        self._check(node, _resolver({}))
        assert PLAYER_HANDLER.first_unrouted_report("cue", "2") is True


def test_the_preflight_runs_after_ready_project_and_before_the_arms():
    from cuemsengine.NodeEngine import NodeEngine

    src = inspect.getsource(NodeEngine._load_project_inner)
    ready = src.index("self.ready_project(")
    check = src.index("self.check_unrouted_video_outputs(")
    arm = src.index("self.ready_script(")
    assert ready < check < arm
    assert "check_unrouted_video_outputs" not in inspect.getsource(
        NodeEngine.ready_project
    ), "ready_project is also the deploy command, which can run mid-show"
