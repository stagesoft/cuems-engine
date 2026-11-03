# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Test-only knobs for the rig rows (869ejxng3 + 1amfwm7e6cw, §6 step 4, K14).

Every knob is read only when ``CUEMS_TEST_KNOBS=1`` is also set, and a node
engine that sees one says so with a WARNING at start, so the knobs ship inert
in the release package:

``CUEMS_TEST_DROP_OSC=<path>:<n>[,<path>:<n>...]``
    drop the n-th ``set_value`` to ``<path>`` (1-based, counted per process),
    e.g. ``/loop:1`` loses the first ``/loop`` datagram (the lost-datagram rows).
``CUEMS_TEST_PROBE_BUDGET_S=<seconds>``
    the load's total loop-period probe budget (default 15 s; the budget-miss row).
``CUEMS_TEST_FORCE_PERIOD=<cue>:<num>:<den>``
    the period ``num / den`` seconds for the cue whose id starts with ``<cue>``
    (the beyond-bound row).
"""

import os
from threading import Lock

from cuemsutils.log import Logger

_lock = Lock()
_counts: dict = {}


def enabled() -> bool:
    return os.environ.get("CUEMS_TEST_KNOBS") == "1"


def _get(name: str):
    if not enabled():
        return None
    value = os.environ.get(name)
    return value if value else None


def announce() -> None:
    """One WARNING naming the active knobs; nothing when none is active."""
    active = [
        f"{n}={os.environ[n]}"
        for n in (
            "CUEMS_TEST_DROP_OSC",
            "CUEMS_TEST_PROBE_BUDGET_S",
            "CUEMS_TEST_FORCE_PERIOD",
        )
        if _get(n)
    ]
    if active:
        Logger.warning(f"TEST KNOBS ACTIVE (CUEMS_TEST_KNOBS=1): {' '.join(active)}")


def _drop_rules() -> dict:
    rules = {}
    raw = _get("CUEMS_TEST_DROP_OSC")
    for item in (raw or "").split(","):
        path, _, n = item.strip().rpartition(":")
        if path and n.isdigit():
            rules.setdefault(path, set()).add(int(n))
    return rules


def drop_osc(path) -> bool:
    """True when this ``set_value`` to *path* must be dropped (and counts it)."""
    if not isinstance(path, str) or not enabled():
        return False
    rules = _drop_rules()
    if path not in rules:
        return False
    with _lock:
        _counts[path] = _counts.get(path, 0) + 1
        n = _counts[path]
    if n in rules[path]:
        Logger.warning(f"TEST KNOB: dropped set_value #{n} to {path}")
        return True
    return False


def probe_budget_s(default: float) -> float:
    raw = _get("CUEMS_TEST_PROBE_BUDGET_S")
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        Logger.warning(f"TEST KNOB: CUEMS_TEST_PROBE_BUDGET_S={raw!r} ignored")
        return default


def forced_period(cue_id):
    """``(num, den)`` forced for *cue_id*, or None."""
    raw = _get("CUEMS_TEST_FORCE_PERIOD")
    if raw is None:
        return None
    try:
        prefix, num, den = raw.split(":")
        num, den = int(num), int(den)
    except ValueError:
        Logger.warning(f"TEST KNOB: CUEMS_TEST_FORCE_PERIOD={raw!r} ignored")
        return None
    if prefix and str(cue_id).startswith(prefix) and num > 0 and den > 0:
        return num, den
    return None


def reset_for_tests() -> None:
    with _lock:
        _counts.clear()
