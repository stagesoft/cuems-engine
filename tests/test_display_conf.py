# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Coverage for cuemsengine.tools.display_conf.read_display_conf."""

import pytest

from cuemsengine.tools.display_conf import (
    read_display_conf,
    DisplayConfNotFoundError,
    DisplayConfValueError,
)


def _write(tmp_path, content):
    p = tmp_path / "display.conf"
    p.write_text(content)
    return str(p)


def test_single_output_canvas(tmp_path):
    path = _write(tmp_path, """\
canvas_layout=custom

[output:HDMI-A-1]
canvas_region=0,0,1920,1080
""")
    regions, canvas = read_display_conf(path)
    assert regions == {"HDMI-A-1": {"x": 0, "y": 0, "width": 1920, "height": 1080}}
    assert canvas == (1920, 1080)


def test_three_outputs_side_by_side(tmp_path):
    path = _write(tmp_path, """\
canvas_layout=custom

[output:HDMI-A-1]
canvas_region=0,0,1920,1080

[output:DP-2]
canvas_region=1920,0,1920,1080

[output:DP-1]
canvas_region=3840,0,1920,1080
""")
    regions, canvas = read_display_conf(path)
    assert set(regions) == {"HDMI-A-1", "DP-2", "DP-1"}
    assert regions["DP-2"] == {"x": 1920, "y": 0, "width": 1920, "height": 1080}
    assert canvas == (5760, 1080)


def test_non_rectangular_layout_canvas_is_bbox(tmp_path):
    """T-shape: top monitor centered, two below — canvas is the bbox."""
    path = _write(tmp_path, """\
canvas_layout=custom

[output:HDMI-A-1]
canvas_region=960,0,1920,1080

[output:DP-1]
canvas_region=0,1080,1920,1080

[output:DP-2]
canvas_region=1920,1080,1920,1080
""")
    _regions, canvas = read_display_conf(path)
    assert canvas == (3840, 2160)


def test_section_name_case_preserved(tmp_path):
    """Connector names like HDMI-A-1 must round-trip with their original case."""
    path = _write(tmp_path, """\
[output:HDMI-A-1]
canvas_region=0,0,1920,1080
""")
    regions, _canvas = read_display_conf(path)
    assert "HDMI-A-1" in regions
    assert "hdmi-a-1" not in regions


def test_ignores_non_output_sections(tmp_path):
    """Global keys (other than canvas_size) and unknown sections are tolerated."""
    path = _write(tmp_path, """\
canvas_layout=custom
name=test-config

[output:HDMI-A-1]
canvas_region=0,0,1920,1080

[some_other_section]
key=value
""")
    regions, canvas = read_display_conf(path)
    assert list(regions) == ["HDMI-A-1"]
    assert canvas == (1920, 1080)


def test_ignores_malformed_canvas_region(tmp_path):
    """An output without a valid 4-int canvas_region is skipped."""
    path = _write(tmp_path, """\
[output:HDMI-A-1]
canvas_region=0,0,1920,1080

[output:DP-1]
canvas_region=not-a-region

[output:DP-2]
canvas_region=0,0,1920
""")
    regions, _canvas = read_display_conf(path)
    assert set(regions) == {"HDMI-A-1"}


def test_missing_file_raises(tmp_path):
    path = str(tmp_path / "does_not_exist.conf")
    with pytest.raises(DisplayConfNotFoundError, match="not found"):
        read_display_conf(path)


def test_file_without_output_sections_raises(tmp_path):
    """Treat file-present-but-empty same as missing — same operator action."""
    path = _write(tmp_path, "canvas_layout=custom\n")
    with pytest.raises(DisplayConfNotFoundError, match="no \\[output:\\*\\] sections"):
        read_display_conf(path)


def test_extra_keys_ignored(tmp_path):
    """resolution + refresh + blend + enabled are VC-side keys; reader ignores."""
    path = _write(tmp_path, """\
[output:HDMI-A-1]
canvas_region=0,0,3840,2160
resolution=3840x2160
refresh=60.0
enabled=true
""")
    regions, canvas = read_display_conf(path)
    assert regions["HDMI-A-1"]["width"] == 3840
    assert canvas == (3840, 2160)


# ---------------------------------------------------------------------------
# canvas_size override (oversized canvas / letterbox margin)
# ---------------------------------------------------------------------------

def test_canvas_size_override_larger_than_bbox(tmp_path):
    """Operator-set canvas_size larger than monitor bbox is honored."""
    path = _write(tmp_path, """\
canvas_layout=custom
canvas_size=7680x2160

[output:HDMI-A-1]
canvas_region=1920,540,1920,1080
""")
    regions, canvas = read_display_conf(path)
    assert regions["HDMI-A-1"]["x"] == 1920
    assert canvas == (7680, 2160)


def test_canvas_size_equal_to_bbox_accepted(tmp_path):
    """canvas_size exactly matching bbox is fine."""
    path = _write(tmp_path, """\
canvas_size=5760x1080

[output:HDMI-A-1]
canvas_region=0,0,1920,1080

[output:DP-2]
canvas_region=1920,0,1920,1080

[output:DP-1]
canvas_region=3840,0,1920,1080
""")
    _regions, canvas = read_display_conf(path)
    assert canvas == (5760, 1080)


def test_canvas_size_smaller_than_bbox_raises(tmp_path):
    """canvas_size smaller than bbox would crop monitors — reject."""
    path = _write(tmp_path, """\
canvas_size=1000x500

[output:HDMI-A-1]
canvas_region=0,0,1920,1080
""")
    with pytest.raises(DisplayConfValueError, match="smaller than"):
        read_display_conf(path)


def test_canvas_size_zero_raises(tmp_path):
    path = _write(tmp_path, """\
canvas_size=0x0

[output:HDMI-A-1]
canvas_region=0,0,1920,1080
""")
    with pytest.raises(DisplayConfValueError, match="positive"):
        read_display_conf(path)


def test_canvas_size_negative_raises(tmp_path):
    path = _write(tmp_path, """\
canvas_size=-1920x-1080

[output:HDMI-A-1]
canvas_region=0,0,1920,1080
""")
    with pytest.raises(DisplayConfValueError):
        read_display_conf(path)


def test_canvas_size_malformed_raises(tmp_path):
    path = _write(tmp_path, """\
canvas_size=not_a_size

[output:HDMI-A-1]
canvas_region=0,0,1920,1080
""")
    with pytest.raises(DisplayConfValueError, match="malformed|non-integer"):
        read_display_conf(path)


def test_canvas_size_absent_falls_back_to_bbox(tmp_path):
    """No canvas_size key → bbox is used (default behaviour)."""
    path = _write(tmp_path, """\
canvas_layout=custom

[output:HDMI-A-1]
canvas_region=0,0,1920,1080

[output:DP-1]
canvas_region=1920,0,1920,1080
""")
    _regions, canvas = read_display_conf(path)
    assert canvas == (3840, 1080)
