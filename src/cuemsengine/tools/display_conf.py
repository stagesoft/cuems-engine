# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Reader for /run/cuems/display.conf.

display.conf is written by cuems-generate-display-conf (ExecStartPre of
cuems-videocomposer.service) and read by both the videocomposer (for DRM
modeset + canvas layout) and the engine (for canvas geometry + per-output
canvas regions, replacing the broken `x = index * 1920` heuristic that used
to live in NodeEngine.set_video_outputs).

File format is INI-like:

    canvas_layout=custom
    canvas_size=5760x1080        # optional, overrides bbox

    [output:HDMI-A-1]
    canvas_region=0,0,1920,1080
    resolution=1920x1080         # optional
    refresh=60.0                 # optional

The engine consumes `canvas_region` and the optional global `canvas_size`
override; resolution + refresh are read by the videocomposer directly.
"""

import configparser
import os
import re
from typing import Optional, Tuple

DEFAULT_DISPLAY_CONF = "/run/cuems/display.conf"


class DisplayConfNotFoundError(RuntimeError):
    """display.conf is missing, unreadable, or has no [output:*] sections."""


class DisplayConfValueError(RuntimeError):
    """display.conf is present but contains an invalid value (e.g. a
    canvas_size override that is malformed, non-positive, or smaller than
    the per-output region bounding box)."""


_CANVAS_SIZE_RE = re.compile(r"^\s*canvas_size\s*=\s*(.+?)\s*$", re.MULTILINE)


def _parse_canvas_size_override(preamble: str) -> Optional[Tuple[int, int]]:
    """Scan the file's global preamble for `canvas_size=WIDTHxHEIGHT`.

    Returns ``(w, h)`` if a valid positive-int override is present,
    ``None`` if the key is absent. Raises ``DisplayConfValueError`` for
    malformed or non-positive values.
    """
    match = _CANVAS_SIZE_RE.search(preamble)
    if not match:
        return None
    raw = match.group(1)
    parts = raw.lower().split("x")
    if len(parts) != 2:
        raise DisplayConfValueError(
            f"canvas_size={raw!r} is malformed; expected WIDTHxHEIGHT"
        )
    try:
        w = int(parts[0])
        h = int(parts[1])
    except ValueError:
        raise DisplayConfValueError(f"canvas_size={raw!r} has non-integer components")
    if w <= 0 or h <= 0:
        raise DisplayConfValueError(
            f"canvas_size={raw!r} must be positive (got {w}x{h})"
        )
    return (w, h)


def read_display_conf(
    path: str = DEFAULT_DISPLAY_CONF,
) -> Tuple[dict, Tuple[int, int]]:
    """Parse display.conf and return ``(regions, canvas_size)``.

    Returns a 2-tuple:

    - ``regions``: ``{connector_name: {'x', 'y', 'width', 'height'}}`` with
      pixel-int values.
    - ``canvas_size``: ``(canvas_width, canvas_height)``. If the global
      ``canvas_size=WIDTHxHEIGHT`` key is present in the file's preamble,
      it is used (after validating it is >= the per-region bounding box).
      Otherwise, computed as ``max(x + width, y + height)`` over all regions.

    Raises:

    - ``DisplayConfNotFoundError`` if the file is missing or has no
      ``[output:*]`` sections.
    - ``DisplayConfValueError`` if ``canvas_size=`` is malformed, has
      non-positive values, or is smaller than the per-region bbox.
    """
    if not os.path.isfile(path):
        raise DisplayConfNotFoundError(
            f"display.conf not found at {path}; "
            "videocomposer must run first (its ExecStartPre generates it)"
        )

    with open(path) as f:
        body = f.read()

    # Pre-pass: extract global preamble (everything before the first
    # [section] header) so we can scan it for `canvas_size=`. The
    # ConfigParser path below DISCARDS the preamble — without this
    # pre-pass the override is silently lost.
    if body.lstrip().startswith("["):
        preamble = ""
        sectioned = body.lstrip()
    elif "\n[" in body:
        split_at = body.find("\n[") + 1
        preamble = body[:split_at]
        sectioned = body[split_at:]
    else:
        preamble = body
        sectioned = ""

    canvas_override = _parse_canvas_size_override(preamble)

    parser = configparser.ConfigParser()
    parser.optionxform = str  # preserve key case for forward-compat keys
    if sectioned:
        parser.read_string(sectioned)

    regions: dict = {}
    for section in parser.sections():
        if not section.startswith("output:"):
            continue
        connector = section[len("output:") :]
        raw = parser.get(section, "canvas_region", fallback=None)
        if raw is None:
            continue
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 4:
            continue
        try:
            x, y, w, h = (int(p) for p in parts)
        except ValueError:
            continue
        regions[connector] = {"x": x, "y": y, "width": w, "height": h}

    if not regions:
        raise DisplayConfNotFoundError(
            f"display.conf at {path} has no [output:*] sections with a "
            "valid canvas_region"
        )

    bbox_w = max(r["x"] + r["width"] for r in regions.values())
    bbox_h = max(r["y"] + r["height"] for r in regions.values())

    if canvas_override is not None:
        cw, ch = canvas_override
        if cw < bbox_w or ch < bbox_h:
            raise DisplayConfValueError(
                f"canvas_size={cw}x{ch} is smaller than the per-output "
                f"bounding box {bbox_w}x{bbox_h}; monitors would be cropped"
            )
        return regions, (cw, ch)

    return regions, (bbox_w, bbox_h)
