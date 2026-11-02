# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The videocomposer's capability file (plan 869ejxng3 + 1amfwm7e6cw, §4.2).

The videocomposer writes ``/run/cuems/videocomposer.caps`` at start
(``pid=<n>``, then one token per line; this release ``loop_period``) and
unlinks it at exit. The node engine reads it at start and at every project
load, and runs looping VideoCues in wrap mode only when ``loop_period`` is
there; otherwise legacy (today's per-pass re-anchor, on P when known).

A file is ignored (WARNING ``stale caps file``) when its pid is gone
(``kill(pid, 0)`` → ``ESRCH``; ``EPERM`` means alive: the mock runs as root,
the engines as ``cuems``, L8) or when ``/proc/<pid>/cmdline`` (readable across
users) does not name a videocomposer (the mock included), so a file left by a
crash cannot make an old binary look capable after a downgrade (J14, K11).
No ``dpkg-query`` (F20).
"""

import errno
import os

from cuemsutils.log import Logger

DEFAULT_CAPS_PATH = "/run/cuems/videocomposer.caps"
LOOP_PERIOD = "loop_period"


def caps_path() -> str:
    return os.environ.get("CUEMS_VC_CAPS_FILE", DEFAULT_CAPS_PATH)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM
    return True


def _names_videocomposer(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read()
    except OSError:
        return False
    return b"videocomposer" in cmdline


def read_videocomposer_caps(path: str | None = None) -> frozenset:
    """The tokens of a live videocomposer's caps file, or an empty set.

    Missing file: empty (an old videocomposer, or none running) without a log
    line; the caller decides whether that is worth a WARNING. A stale or
    malformed file: WARNING and empty.
    """
    path = path or caps_path()
    try:
        with open(path) as f:
            lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return frozenset()
    except OSError as e:
        Logger.warning(f"videocomposer caps file {path} unreadable ({e})")
        return frozenset()
    if not lines or not lines[0].startswith("pid="):
        Logger.warning(f"videocomposer caps file {path} malformed (no pid= line)")
        return frozenset()
    try:
        pid = int(lines[0][4:])
    except ValueError:
        Logger.warning(f"videocomposer caps file {path} malformed ({lines[0]!r})")
        return frozenset()
    if pid <= 0 or not _pid_alive(pid) or not _names_videocomposer(pid):
        Logger.warning(
            f"stale caps file {path} (pid {pid} is not a running videocomposer): "
            "ignored, looping video cues run in legacy mode"
        )
        return frozenset()
    return frozenset(lines[1:])
