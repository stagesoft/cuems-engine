# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""A video layer whose placement/scale could not be applied must say so.

The cue still arms and plays (a wrong-sized video beats no video in a live
show), but the failure is logged at ERROR naming the cue, the layer and the
output, and recorded in cue._placement_failed, which every arm resets
(869f8hfra).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cuemsutils.cues import VideoCue


def _make_video_cue() -> VideoCue:
    cue = VideoCue()
    cue.media = {"file_name": "clip.mp4", "duration": "00:00:10.000"}
    return cue


def _arm(cue, resolve):
    from cuemsengine.cues.arm_cue import arm_videoCue
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    client = MagicMock()
    with (
        patch.object(PLAYER_HANDLER, "get_video_client", return_value=client),
        patch.object(
            PLAYER_HANDLER, "get_all_cue_output_names", return_value=["output-0"]
        ),
        patch.object(PLAYER_HANDLER, "media_path", return_value="/media/clip.mp4"),
        patch.object(PLAYER_HANDLER, "media_dimensions", return_value=(1920, 1080)),
        patch.object(PLAYER_HANDLER, "resolve_video_output_for_cue", **resolve),
        patch.object(PLAYER_HANDLER, "register_layer"),
        patch("cuemsengine.cues.arm_cue.Logger") as logger,
    ):
        arm_videoCue(cue)
    return client, logger


def _run(cue, resolve):
    from cuemsengine.cues.run_cue import run_videoCue
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    mtc = MagicMock()
    mtc.main_tc.framerate = 25
    with (
        patch.object(
            PLAYER_HANDLER, "get_all_cue_output_names", return_value=["output-0"]
        ),
        patch.object(PLAYER_HANDLER, "media_dimensions", return_value=(1920, 1080)),
        patch.object(PLAYER_HANDLER, "resolve_video_output_for_cue", **resolve),
        patch("cuemsengine.cues.run_cue.Logger") as logger,
    ):
        run_videoCue(cue, mtc, frozen_mtc_ms=1000.0)
    return logger


def _error_messages(logger):
    return [str(c.args[0]) for c in logger.error.call_args_list]


NO_OUTPUT = {"side_effect": KeyError("No VideoCueOutput match for output-0")}


def _working_output():
    output = MagicMock()
    output.get_layer_placement.return_value = (0, 0)
    output.get_layer_scale.return_value = (0.5, 0.5)
    return {"return_value": output}


class TestArmPlacementFailure:
    def test_failure_is_logged_at_error_with_cue_layer_and_output(self):
        cue = _make_video_cue()
        _, logger = _arm(cue, NO_OUTPUT)
        layer_id = cue._layer_ids[0]
        errors = [m for m in _error_messages(logger) if "NOT applied" in m]
        assert len(errors) == 1
        assert str(cue.id) in errors[0]
        assert layer_id in errors[0]
        assert "output-0" in errors[0]
        logger.warning.assert_not_called()

    def test_failure_is_recorded_on_the_cue_and_the_cue_still_arms(self):
        cue = _make_video_cue()
        _arm(cue, NO_OUTPUT)
        assert cue._placement_failed == [cue._layer_ids[0]]
        assert len(cue._layer_ids) == 1

    def test_a_clean_rearm_clears_a_previous_failure(self):
        cue = _make_video_cue()
        cue._placement_failed = ["stale_layer_0"]
        _, logger = _arm(cue, _working_output())
        assert cue._placement_failed == []
        assert not [m for m in _error_messages(logger) if "NOT applied" in m]


class TestRunPlacementFailure:
    def test_reapply_failure_is_logged_at_error_and_recorded(self):
        cue = _make_video_cue()
        cue._layer_ids = ["layer_0"]
        cue._osc = MagicMock()
        cue._placement_failed = []
        logger = _run(cue, NO_OUTPUT)
        errors = [m for m in _error_messages(logger) if "NOT applied" in m]
        assert len(errors) == 1
        assert "layer_0" in errors[0]
        assert "output-0" in errors[0]
        assert cue._placement_failed == ["layer_0"]

    def test_reapply_failure_without_a_prior_arm_record_does_not_crash(self):
        cue = _make_video_cue()
        cue._layer_ids = ["layer_0"]
        cue._osc = MagicMock()
        _run(cue, NO_OUTPUT)
        assert cue._placement_failed == ["layer_0"]

    def test_successful_reapply_clears_the_arm_failure(self):
        cue = _make_video_cue()
        cue._layer_ids = ["layer_0"]
        cue._osc = MagicMock()
        cue._placement_failed = ["layer_0"]
        _run(cue, _working_output())
        assert cue._placement_failed == []
