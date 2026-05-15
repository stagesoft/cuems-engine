# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Reader for /run/cuems/display.conf.

display.conf is written by cuems-generate-display-conf (ExecStartPre of
cuems-videocomposer.service) and read by both the videocomposer (for DRM
modeset + canvas layout) and the engine (for canvas geometry + per-output
canvas regions, replacing the broken `x = index * 1920` heuristic that used
to live in NodeEngine.set_video_outputs).

File format is INI-like:

    canvas_layout=custom

    [output:HDMI-A-1]
    canvas_region=0,0,1920,1080
    resolution=1920x1080         # optional
    refresh=60.0                 # optional

The engine only consumes `canvas_region` today; resolution + refresh are
read by the videocomposer directly.
"""

import configparser
import os
from typing import Tuple


DEFAULT_DISPLAY_CONF = "/run/cuems/display.conf"


class DisplayConfNotFoundError(RuntimeError):
    """display.conf is missing, unreadable, or has no [output:*] sections."""


def read_display_conf(path: str = DEFAULT_DISPLAY_CONF) -> Tuple[dict, Tuple[int, int]]:
    """Parse display.conf and return ``(regions, canvas_size)``.

    Returns a 2-tuple:

    - ``regions``: ``{connector_name: {'x', 'y', 'width', 'height'}}`` with
      pixel-int values.
    - ``canvas_size``: ``(canvas_width, canvas_height)`` computed as
      ``max(x + width, y + height)`` over all regions.

    Raises ``DisplayConfNotFoundError`` if the file is missing or has no
    ``[output:*]`` sections.
    """
    if not os.path.isfile(path):
        raise DisplayConfNotFoundError(
            f"display.conf not found at {path}; "
            "videocomposer must run first (its ExecStartPre generates it)"
        )

    parser = configparser.ConfigParser()
    parser.optionxform = str  # preserve key case for forward-compat keys

    # Drop the file's global preamble (anything before the first [section]):
    # display.conf carries top-level keys like `canvas_layout=custom` that
    # ConfigParser would reject as MissingSectionHeaderError. Only [output:*]
    # sections matter here; global keys are VC-side concerns.
    with open(path) as f:
        body = f.read()
    if body.lstrip().startswith("["):
        sectioned = body.lstrip()
    elif "\n[" in body:
        sectioned = body[body.find("\n[") + 1:]
    else:
        sectioned = ""
    if sectioned:
        parser.read_string(sectioned)

    regions: dict = {}
    for section in parser.sections():
        if not section.startswith("output:"):
            continue
        connector = section[len("output:"):]
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

    canvas_w = max(r["x"] + r["width"] for r in regions.values())
    canvas_h = max(r["y"] + r["height"] for r in regions.values())
    return regions, (canvas_w, canvas_h)
