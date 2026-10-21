# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The loop period P of the media a node loops (plan 869ejxng3 + 1amfwm7e6cw
rev 3.14, §4.1, D14).

Where a node gets P from, in order:

1. the ``indexes/<name>.period`` sidecar the editor wrote at upload (or in its
   pre-load media refresh) and the load's media sync carried here, valid while
   the file's size and mtime match: no probe at all;
2. this node's persistent cache (``/var/cache/cuems/loop-periods.json``, keyed
   by path + size + mtime, never cleared on unload or at boot);
3. a probe inside the load with ``cuemsutils.tools.media_sidecars.loop_period``
   (the one implementation the editor uses too), within the load's budget:
   15 s in total, 10 s per file. A file that misses it runs legacy for this
   load (reported in ``armed_ready``); its probe is finished in the background
   at low priority and cached, so the next load has it.

The engine never writes a sidecar: ``media/indexes/`` mirrors the controller's.
"""

import json
import os
import tempfile
from threading import Lock, Thread
from time import monotonic

from cuemsutils.log import Logger
from cuemsutils.tools import media_sidecars
from cuemsutils.tools.media_sidecars import Period, PeriodError, PeriodTimeout

DEFAULT_CACHE_PATH = "/var/cache/cuems/loop-periods.json"
LOAD_BUDGET_S = 15.0
FILE_BUDGET_S = 10.0
INT32_MAX = 2**31 - 1


class LoopPeriodCache:
    """``{"<path>|<size>|<mtime>": <Period JSON>}`` on disk, written atomically.

    An unreadable or corrupt file is a WARNING and counts as empty; a cache
    that cannot be written is a WARNING (once) and stays in memory.
    """

    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get(
            "CUEMS_LOOP_PERIOD_CACHE", DEFAULT_CACHE_PATH
        )
        self._lock = Lock()
        self._data: dict | None = None
        self._write_warned = False

    @staticmethod
    def key(media_path: str) -> str | None:
        try:
            st = os.stat(media_path)
        except OSError:
            return None
        return f"{media_path}|{st.st_size}|{int(st.st_mtime)}"

    def _loaded(self) -> dict:
        if self._data is None:
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self._data = data if isinstance(data, dict) else {}
            except FileNotFoundError:
                self._data = {}
            except (OSError, ValueError) as e:
                Logger.warning(
                    f"loop period cache {self.path} unreadable ({e}); starting empty"
                )
                self._data = {}
        return self._data

    def get(self, media_path: str) -> Period | None:
        key = self.key(media_path)
        if key is None:
            return None
        with self._lock:
            text = self._loaded().get(key)
        if text is None:
            return None
        try:
            return Period.from_json(text)
        except (ValueError, TypeError, KeyError):
            return None

    def put(self, media_path: str, period: Period) -> None:
        key = self.key(media_path)
        if key is None:
            return
        with self._lock:
            data = self._loaded()
            for old in [
                k for k in data if k.rsplit("|", 2)[0] == media_path and k != key
            ]:
                del data[old]  # the file changed: its old entries are dead
            data[key] = period.to_json()
            self._write(data)

    def _write(self, data: dict) -> None:
        try:
            d = os.path.dirname(self.path)
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".loop-periods.")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError as e:
            if not self._write_warned:
                self._write_warned = True
                Logger.warning(
                    f"loop period cache {self.path} not writable ({e}); kept in memory"
                )


def media_loop_period(media_path: str, budget_s: float | None, cache: LoopPeriodCache):
    """``(Period | None, source)``: from the sidecar, the cache or a probe.

    Raises ``PeriodTimeout`` when the probe misses *budget_s*; any other
    failure returns ``(None, "error: …")``.
    """
    p = media_sidecars.read_period(media_path)
    if p is not None:
        return p, "sidecar"
    p = cache.get(media_path)
    if p is not None:
        return p, "cache"
    try:
        p = media_sidecars.loop_period(media_path, budget_s=budget_s)
    except PeriodTimeout:
        raise
    except PeriodError as e:
        return None, f"error: {e}"
    cache.put(media_path, p)
    return p, f"probed in {p.probe_s:.2f} s"


def _finish_in_background(paths: list, cache: LoopPeriodCache) -> Thread | None:
    """Finish the probes a load's budget cut, one file at a time, at low priority,
    so the next load has their periods. The current load stays legacy."""
    if not paths:
        return None

    def run():
        for path in paths:
            try:
                cache.put(path, media_sidecars.loop_period(path, low_priority=True))
                Logger.info(
                    f"loop period of {os.path.basename(path)} cached for the next load"
                )
            except Exception as e:
                Logger.warning(
                    f"loop period of {os.path.basename(path)} still unknown: {e}"
                )

    t = Thread(target=run, name="loop-period-finish", daemon=True)
    t.start()
    return t


def probe_loop_periods(
    cues,
    media_path_fn,
    cache: LoopPeriodCache,
    total_budget_s: float = LOAD_BUDGET_S,
    file_budget_s: float = FILE_BUDGET_S,
    clock=monotonic,
    cancel=None,
) -> list:
    """Give every cue of *cues* its ``_loop_period`` (a ``Period`` or ``None``).

    Returns the ids of the cues left without one (budget miss, failure, a period
    beyond int32): they run legacy on this node for this load. One INFO line per
    cue, one WARNING per failure. A file used by several cues is probed once.
    Once *cancel* (an ``Event``) is set nothing more is assigned: the load has
    reported its modes in ``armed_ready`` and they never change after it.
    """
    start = clock()
    legacy, misses, seen = [], [], {}
    for cue in cues:
        cue._loop_period = None
    for cue in cues:
        if cancel is not None and cancel.is_set():
            break
        name = cue.media.file_name
        path = media_path_fn(name)
        if path in seen:
            p, source = seen[path]
        else:
            left = total_budget_s - (clock() - start)
            try:
                if left <= 0:
                    raise PeriodTimeout("load budget exhausted")
                p, source = media_loop_period(path, min(file_budget_s, left), cache)
            except PeriodTimeout:
                p, source = None, "budget"
                misses.append(path)
            seen[path] = (p, source)
        if p is not None and p.num > INT32_MAX:
            Logger.error(
                f"loop period of {name} ({p.num} samples) exceeds the int32 wire "
                f"range: cue {cue.id} loops in legacy mode"
            )
            p = None
        if p is None:
            legacy.append(str(cue.id))
            if source == "budget":
                Logger.warning(
                    f"loop period for {cue.id} ({name}) missed the load budget: "
                    "legacy loop (a gap per pass) on this node for this load"
                )
            else:
                Logger.warning(
                    f"loop period for {cue.id} ({name}) unknown ({source}): legacy loop"
                )
            continue
        if cancel is not None and cancel.is_set():
            break
        cue._loop_period = p
        size = p.size
        Logger.info(
            f"loop period for {cue.id}: {p.num}/{p.den} = {p.ms:.3f} ms "
            f"(file {name}, {size} bytes, {source})"
        )
    _finish_in_background(list(dict.fromkeys(misses)), cache)
    return legacy
