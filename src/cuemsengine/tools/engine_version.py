# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The engine's own version, read once (1amfwm7jnqf, D16).

The Debian package version (every rc6-N tag says 0.1.0rc6 to importlib, I8),
else the Python package's, else ``unknown``. A node sends it in every
``armed_ready``; the controller compares it with its own, and every node puts
it in its ``Chain pass`` lines.
"""

from __future__ import annotations

import subprocess

_cached: str | None = None


def _read() -> str:
    try:
        r = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", "cuems-engine"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = r.stdout.strip() if r.returncode == 0 else ""
        if version:
            return version
    except Exception:
        pass
    try:
        from importlib.metadata import version as _v

        return f"{_v('cuemsengine')} (python package)"
    except Exception:
        return "unknown"


def engine_version() -> str:
    """The version string, read on the first call and kept."""
    global _cached
    if _cached is None:
        _cached = _read()
    return _cached
