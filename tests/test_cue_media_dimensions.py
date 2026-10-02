# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""A video cue's pixel size comes from the project, not from ffprobe (869fat84r).

The engine ran ``ffprobe`` for a video file's width and height on the first
arm of that file since the engine started. A cue selection arms the selected
chain under the command lock, so a GO sent right after it (power-bridge
``/gocue``, Companion) waited for the probes: 400 ms late on the Medina sala1
project. The editor now stores ``pixel_width`` / ``pixel_height`` and the
file's ``file_size`` in the project's ``Media``, as it stores the duration.

The engine uses the stored values without a subprocess. It probes, as before,
only when they are missing or invalid, or when ``file_size`` differs from its
own copy of the file (a file replaced under the same name), and says so once
per file.

Design: cuems-RELATIONS Plans/2026-10-01-engine-late-go-media-probe.md §3.3.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cuemsutils.cues import VideoCue

PH = "cuemsengine.players.PlayerHandler"


@pytest.fixture
def handler(tmp_path):
    """PLAYER_HANDLER on a temporary media folder holding a 1000-byte
    clip.mp4, with an empty probe cache and no "already warned" files."""
    from cuemsengine.players.PlayerHandler import PLAYER_HANDLER

    media = tmp_path / "media"
    media.mkdir()
    (media / "clip.mp4").write_bytes(b"x" * 1000)
    saved_folder = PLAYER_HANDLER._media_folder
    with PLAYER_HANDLER._lock:
        saved_cache = dict(PLAYER_HANDLER._media_dims_cache)
        saved_warned = set(PLAYER_HANDLER._media_dims_warned)
        PLAYER_HANDLER._media_dims_cache.clear()
        PLAYER_HANDLER._media_dims_warned.clear()
    PLAYER_HANDLER._media_folder = str(media)
    yield PLAYER_HANDLER
    PLAYER_HANDLER._media_folder = saved_folder
    with PLAYER_HANDLER._lock:
        PLAYER_HANDLER._media_dims_cache.clear()
        PLAYER_HANDLER._media_dims_cache.update(saved_cache)
        PLAYER_HANDLER._media_dims_warned.clear()
        PLAYER_HANDLER._media_dims_warned.update(saved_warned)


def _probe_ok(*args, **kwargs):
    out = MagicMock()
    out.returncode = 0
    out.stdout = "1280,720\n"
    return out


def _cue(**stored):
    """A VideoCue whose Media carries *stored* the way a parsed project does:
    the parsers assign keys raw, never through Media's setters, and an older
    cuemsutils has no setters for these keys at all."""
    cue = VideoCue()
    cue.media = {"file_name": "clip.mp4", "duration": "00:00:10.000"}
    for key, value in stored.items():
        dict.__setitem__(cue.media, key, value)
    return cue


def _dims(handler, cue):
    """cue_media_dimensions with ffprobe 'installed', counting the probes and
    the warnings."""
    with (
        patch(f"{PH}.shutil.which", return_value="/usr/bin/ffprobe"),
        patch(f"{PH}.subprocess.run", side_effect=_probe_ok) as run,
        patch(f"{PH}.Logger") as logger,
    ):
        result = handler.cue_media_dimensions(cue)
    return (
        result,
        run.call_count,
        [str(c.args[0]) for c in logger.warning.call_args_list],
    )


class TestStoredValues:
    def test_stored_dimensions_with_a_matching_size_run_no_subprocess(self, handler):
        cue = _cue(pixel_width=3840, pixel_height=2160, file_size=1000)
        assert _dims(handler, cue) == ((3840, 2160), 0, [])

    def test_stored_dimensions_without_a_size_are_trusted(self, handler):
        cue = _cue(pixel_width=3840, pixel_height=2160)
        assert _dims(handler, cue) == ((3840, 2160), 0, [])

    def test_a_missing_file_does_not_turn_into_a_probe(self, handler):
        """The layer load reports a missing file; the dimensions are not the
        place to discover it."""
        cue = _cue(pixel_width=3840, pixel_height=2160, file_size=1000)
        dict.__setitem__(cue.media, "file_name", "gone.mp4")
        assert _dims(handler, cue) == ((3840, 2160), 0, [])


class TestFallbackToTheProbe:
    @pytest.mark.parametrize(
        "media",
        [
            {},
            {"pixel_width": 1920},
            {"pixel_height": 1080},
            {"pixel_width": 0, "pixel_height": 1080},
            {"pixel_width": -1920, "pixel_height": 1080},
            {"pixel_width": True, "pixel_height": 1080},
            {"pixel_width": "1920", "pixel_height": "1080"},
            {"pixel_width": None, "pixel_height": None},
        ],
        ids=[
            "absent",
            "width-only",
            "height-only",
            "zero",
            "negative",
            "bool",
            "str",
            "none",
        ],
    )
    def test_missing_or_invalid_values_probe_and_warn(self, handler, media):
        result, probes, warnings = _dims(handler, _cue(**media))
        assert result == (1280, 720)
        assert probes == 1
        assert len(warnings) == 1
        assert "No stored dimensions for clip.mp4" in warnings[0]

    def test_the_warning_is_given_once_per_file(self, handler):
        _dims(handler, _cue())
        handler._media_dims_cache.clear()  # force a second probe
        _, probes, warnings = _dims(handler, _cue())
        assert probes == 1
        assert warnings == []

    def test_a_size_mismatch_probes_and_names_both_sizes(self, handler):
        cue = _cue(pixel_width=1920, pixel_height=1080, file_size=999)
        result, probes, warnings = _dims(handler, cue)
        assert result == (1280, 720)
        assert probes == 1
        assert len(warnings) == 1
        assert "clip.mp4" in warnings[0]
        assert "999" in warnings[0] and "1000" in warnings[0]

    def test_a_media_mapping_without_the_keys_probes(self, handler):
        """An older cuemsutils, or a plain dict: no keys at all."""
        cue = _cue()
        for key in [k for k in cue.media if k != "file_name"]:
            dict.__delitem__(cue.media, key)
        result, probes, _ = _dims(handler, cue)
        assert (result, probes) == ((1280, 720), 1)


# ---------------------------------------------------------------------------
# The two call sites use it: stored values reach get_layer_scale, no probe.
# ---------------------------------------------------------------------------


def _working_output():
    output = MagicMock()
    output.get_layer_placement.return_value = (0, 0)
    output.get_layer_scale.return_value = (0.5, 0.5)
    return output


class TestCallSites:
    def test_arm_scales_with_the_stored_values_and_never_probes(self, handler):
        from cuemsengine.cues.arm_cue import arm_videoCue

        cue = _cue(pixel_width=3840, pixel_height=2160, file_size=1000)
        output = _working_output()
        with (
            patch.object(handler, "get_video_client", return_value=MagicMock()),
            patch.object(
                handler, "get_all_cue_output_names", return_value=["output-0"]
            ),
            patch.object(handler, "resolve_video_output_for_cue", return_value=output),
            patch.object(handler, "register_layer"),
            patch.object(
                handler, "media_dimensions", side_effect=AssertionError("probed")
            ),
            patch(f"{PH}.subprocess.run", side_effect=AssertionError("subprocess")),
            patch("cuemsengine.cues.arm_cue.Logger"),
        ):
            arm_videoCue(cue)
        output.get_layer_scale.assert_called_with(3840, 2160)

    def test_run_scales_with_the_stored_values_and_never_probes(self, handler):
        from cuemsengine.cues.run_cue import run_videoCue

        cue = _cue(pixel_width=3840, pixel_height=2160, file_size=1000)
        cue._layer_ids = [f"{cue.id}_0"]
        cue._osc = MagicMock()
        cue._placement_failed = []
        output = _working_output()
        mtc = MagicMock()
        mtc.main_tc.framerate = 25
        with (
            patch.object(
                handler, "get_all_cue_output_names", return_value=["output-0"]
            ),
            patch.object(handler, "resolve_video_output_for_cue", return_value=output),
            patch.object(
                handler, "media_dimensions", side_effect=AssertionError("probed")
            ),
            patch(f"{PH}.subprocess.run", side_effect=AssertionError("subprocess")),
            patch("cuemsengine.cues.run_cue.Logger"),
        ):
            run_videoCue(cue, mtc, frozen_mtc_ms=1000.0)
        output.get_layer_scale.assert_called_with(3840, 2160)

    def test_stored_and_probed_values_give_the_same_scale(self, handler):
        """The same numbers reach get_layer_scale either way, so the picture
        cannot change size because the values were stored."""
        stored, _, _ = _dims(
            handler, _cue(pixel_width=1280, pixel_height=720, file_size=1000)
        )
        probed, probes, _ = _dims(handler, _cue())
        assert probes == 1
        assert stored == probed
