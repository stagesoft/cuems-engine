# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Unit tests for arm_videoCue's opacity deploy step.

The client (VideoClient) is the sole source of truth for a layer's live
opacity once armed — ActionHandler._build_fade_payload only falls back to
VideoCue.opacity (the CuemsScript-stored value) when nothing has been
deployed to the client yet (get_value_if_set returns None). arm_videoCue is
what establishes that initial deployment, mirroring run_audioCue's existing
master_vol -> /volmaster deploy for AudioCue.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import VideoCue


def _make_video_cue(opacity: int | None = None) -> VideoCue:
    cue = VideoCue()
    if opacity is not None:
        cue.opacity = opacity
    cue.media = {"file_name": "clip.mp4"}
    return cue


def _arm(cue, output_names=("output-0",)):
    from cuemsengine.cues.arm_cue import arm_videoCue
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    client = MagicMock()
    with (
        patch.object(PLAYER_HANDLER, "get_video_client", return_value=client),
        patch.object(
            PLAYER_HANDLER, "get_all_cue_output_names", return_value=list(output_names)
        ),
        patch.object(PLAYER_HANDLER, "media_path", return_value="/media/clip.mp4"),
        patch.object(PLAYER_HANDLER, "media_dimensions", return_value=(1920, 1080)),
        patch.object(
            PLAYER_HANDLER,
            "resolve_video_output_for_cue",
            side_effect=RuntimeError("no output mapping in this test"),
        ),
        patch.object(PLAYER_HANDLER, "register_layer"),
    ):
        arm_videoCue(cue)
    return client


def _opacity_calls(client, layer_id):
    return [
        c
        for c in client.set_value.call_args_list
        if c.args[0] == f"/videocomposer/layer/{layer_id}/opacity"
    ]


class TestArmVideoCueOpacityDeploy:
    def test_deploys_stored_opacity_normalised_to_0_1_scale(self):
        cue = _make_video_cue(opacity=60)
        client = _arm(cue)
        layer_id = cue._layer_ids[0]
        calls = _opacity_calls(client, layer_id)
        assert len(calls) == 1
        assert calls[0].args[1] == pytest.approx(0.6)

    def test_deploys_default_100_when_no_opacity_predefined(self):
        cue = _make_video_cue(opacity=None)
        client = _arm(cue)
        layer_id = cue._layer_ids[0]
        calls = _opacity_calls(client, layer_id)
        assert len(calls) == 1
        assert calls[0].args[1] == pytest.approx(1.0)

    def test_deploys_opacity_per_layer_for_multi_output_cue(self):
        cue = _make_video_cue(opacity=25)
        client = _arm(cue, output_names=("output-0", "output-1"))
        assert len(cue._layer_ids) == 2
        for layer_id in cue._layer_ids:
            calls = _opacity_calls(client, layer_id)
            assert len(calls) == 1
            assert calls[0].args[1] == pytest.approx(0.25)
