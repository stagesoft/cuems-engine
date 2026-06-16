# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Routing coverage for VideoCueOutput custom regions.

Tests the engine-side fork that resolves `<uuid>_custom_<n>` output_names by
synthesizing a VideoOutput from the cue's inline canvas_region, instead of
looking the suffix up in _video_outputs (which would KeyError).

Kept deliberately narrow — no attempt to mock the full arm/run pipeline;
the shared resolve_video_output_for_cue method is the surface under test.
"""

import sys
from unittest.mock import Mock

import pytest

# Defend against the same problematic import that other engine tests guard.
sys.modules.setdefault('cuemsutils.tools.Osc_nodes_hub', Mock())

from cuemsengine.players.PlayerHandler import PlayerHandler
from cuemsengine.players.VideoPlayer import VideoOutput


NODE_UUID = "0367f391-ebf4-48b2-9f26-000000000001"
OTHER_NODE = "0367f391-ebf4-48b2-9f26-000000000099"

CANVAS_W, CANVAS_H = 1920, 1080


@pytest.fixture
def handler():
    """Fresh PlayerHandler state for each test.

    PlayerHandler is a singleton; reset_all + re-seed in each test to
    keep tests independent.
    """
    h = PlayerHandler()
    h.reset_all()
    h.add_node_uuid(NODE_UUID)
    # Seed one alias VideoOutput so _resolve_canvas_dimensions has a source.
    h._video_outputs["0"] = VideoOutput(
        name="0",
        canvas_width=CANVAS_W,
        canvas_height=CANVAS_H,
        canvas_region={"x": 0, "y": 0, "width": CANVAS_W, "height": CANVAS_H},
        width=CANVAS_W,
        height=CANVAS_H,
    )
    yield h
    h.reset_all()


def _alias_output(node=NODE_UUID):
    """Dict-shaped alias output (no canvas_region)."""
    return {"output_name": f"{node}_0", "output_geometry": {}}


def _custom_output(node=NODE_UUID, n=0, x=0.1, y=0.1, w=0.5, h=0.5):
    """Dict-shaped custom VideoCueOutput (inline canvas_region)."""
    return {
        "output_name": f"{node}_custom_{n}",
        "output_geometry": {},
        "canvas_region": {"x": x, "y": y, "width": w, "height": h},
    }


def _cue(outputs):
    """Minimal cue stand-in: just needs an `outputs` attribute."""
    return Mock(spec=["outputs", "id"], outputs=outputs, id="cue-uuid")


# ---------------------------------------------------------------------------
# make_custom_video_output
# ---------------------------------------------------------------------------

def test_make_custom_video_output_converts_to_pixels(handler):
    """Normalized (0.1,0.1,0.5,0.5) on 1920x1080 -> pixel (192,108,960,540)."""
    vo = handler.make_custom_video_output(
        _custom_output(x=0.1, y=0.1, w=0.5, h=0.5)
    )
    assert vo.canvas_region == {
        "x": 192, "y": 108, "width": 960, "height": 540,
    }
    assert vo.canvas_width == CANVAS_W
    assert vo.canvas_height == CANVAS_H


def test_make_custom_video_output_matches_video_output_kwargs(handler):
    """Regression against 0.5 // 2 == 0: placement must be non-zero."""
    vo = handler.make_custom_video_output(
        _custom_output(x=0.25, y=0.25, w=0.5, h=0.5)
    )
    x, y = vo.get_layer_placement()
    # Region center is at (0.5, 0.5) normalized = (960, 540) pixels;
    # canvas center is (960, 540). Offset from center should be (0, 0).
    # Shift to test something non-trivial:
    vo2 = handler.make_custom_video_output(
        _custom_output(x=0.0, y=0.0, w=0.5, h=0.5)
    )
    x2, y2 = vo2.get_layer_placement()
    # Region center at (480, 270); canvas center at (960, 540);
    # return (region_cx - canvas_cx, canvas_cy - region_cy) = (-480, 270).
    assert (x2, y2) == (-480, 270)


def test_resolve_canvas_dimensions_requires_aliases(handler):
    """With no aliases registered, factory raises a clear RuntimeError."""
    handler._video_outputs = {}
    with pytest.raises(RuntimeError, match="Cannot resolve canvas dimensions"):
        handler.make_custom_video_output(_custom_output())


# ---------------------------------------------------------------------------
# resolve_video_output_for_cue — alias + custom paths
# ---------------------------------------------------------------------------

def test_resolve_alias_returns_cached_video_output(handler):
    cue = _cue([_alias_output()])
    vo = handler.resolve_video_output_for_cue(cue, "0")
    assert vo is handler._video_outputs["0"]


def test_resolve_custom_synthesizes_from_inline_region(handler):
    cue = _cue([_alias_output(), _custom_output(x=0.1, y=0.1, w=0.5, h=0.5)])
    vo = handler.resolve_video_output_for_cue(cue, "custom_0")
    # Not the cached alias — a fresh synthesized instance.
    assert vo is not handler._video_outputs["0"]
    assert vo.canvas_region == {
        "x": 192, "y": 108, "width": 960, "height": 540,
    }


def test_resolve_custom_matches_by_full_output_name(handler):
    """On a multi-node cue, we must pick this node's custom, not index 0."""
    cue = _cue([
        _custom_output(node=OTHER_NODE, x=0.0, y=0.0, w=1.0, h=1.0),
        _custom_output(node=NODE_UUID,  x=0.25, y=0.25, w=0.5, h=0.5),
    ])
    vo = handler.resolve_video_output_for_cue(cue, "custom_0")
    # If positional indexing were used, we'd get the other-node region
    # (x=0, y=0, 1920, 1080). Correct lookup yields this node's region.
    assert vo.canvas_region == {
        "x": int(0.25 * CANVAS_W),
        "y": int(0.25 * CANVAS_H),
        "width": int(0.5 * CANVAS_W),
        "height": int(0.5 * CANVAS_H),
    }


def test_resolve_custom_missing_cue_output_raises_key_error(handler):
    """If the cue has no matching VideoCueOutput for the suffix, KeyError."""
    cue = _cue([_alias_output()])  # no custom entry
    with pytest.raises(KeyError, match="No VideoCueOutput match"):
        handler.resolve_video_output_for_cue(cue, "custom_0")


def test_resolve_alias_still_raises_on_unknown_suffix(handler):
    """Preserve existing behavior: unknown numeric suffix -> KeyError."""
    cue = _cue([_alias_output()])
    with pytest.raises(KeyError):
        handler.resolve_video_output_for_cue(cue, "42")


def test_resolve_custom_does_not_touch_video_outputs_map(handler):
    """Custom path should NEVER dict-lookup the suffix in _video_outputs."""
    cue = _cue([_custom_output()])
    before = dict(handler._video_outputs)
    handler.resolve_video_output_for_cue(cue, "custom_0")
    assert handler._video_outputs == before  # unchanged


# ---------------------------------------------------------------------------
# Higher-index customs (schema allows any <n>; engine is prefix-driven)
# ---------------------------------------------------------------------------

def test_resolve_custom_any_index(handler):
    cue = _cue([_custom_output(n=3, x=0.5, y=0.0, w=0.5, h=0.5)])
    vo = handler.resolve_video_output_for_cue(cue, "custom_3")
    assert vo.canvas_region == {"x": 960, "y": 0, "width": 960, "height": 540}
