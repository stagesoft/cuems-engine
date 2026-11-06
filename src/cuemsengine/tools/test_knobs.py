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

869feynrj step 5 (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-
869feynrj.md §7.2):

``CUEMS_TEST_GO_PHASE_SWEEP=<start>:<step>`` (controller, R1)
    each operator GO waits (< 40 ms, before the press is read) until the
    interpolated MTC sits at the current phase of its 40 ms frame; the phase
    starts at <start> ms and advances by <step> ms per GO, modulo 40. A
    deterministic sweep of the press phase (review 4 m8).
``CUEMS_TEST_FORCE_LEAD_MS=<ms>`` (controller, R15 / R16)
    L is <ms> (after the cap; lead_ms in the GO payload carries it).
``CUEMS_TEST_HOLD_COMMAND_LOCK_MS=<ms>`` (node, R10)
    every GO handled sleeps <ms> inside _command_lock, so the GO's handling
    is slower than L.
``CUEMS_TEST_CANCEL_AT=<action>:<o1>[,<o2>,...]`` (node, R4)
    on every operator GO, a cancel of the first local AudioCue of its pass at
    that cue's start + offset (+-1 ms on the interpolated MTC), through the
    path the real command takes; <action> is one of stop, disable, supersede
    (setnextcue + go of the cue), actionstop, actionpause, actionfadeout. With
    several offsets the n-th GO since engine start uses offset[n mod len],
    counted like the phase sweep.
"""

import os
from threading import Lock
from time import sleep
from typing import Callable

from cuemsutils.log import Logger

_lock = Lock()
_counts: dict = {}

KNOB_NAMES = (
    "CUEMS_TEST_DROP_OSC",
    "CUEMS_TEST_PROBE_BUDGET_S",
    "CUEMS_TEST_FORCE_PERIOD",
    "CUEMS_TEST_GO_PHASE_SWEEP",
    "CUEMS_TEST_FORCE_LEAD_MS",
    "CUEMS_TEST_HOLD_COMMAND_LOCK_MS",
    "CUEMS_TEST_CANCEL_AT",
)
FRAME_MS = 40.0  # CUEMS MTC is always 25 fps
CANCEL_ACTIONS = (
    "stop",
    "disable",
    "supersede",
    "actionstop",
    "actionpause",
    "actionfadeout",
)


def enabled() -> bool:
    return os.environ.get("CUEMS_TEST_KNOBS") == "1"


def _get(name: str):
    if not enabled():
        return None
    value = os.environ.get(name)
    return value if value else None


def announce() -> None:
    """One WARNING naming the active knobs; nothing when none is active."""
    active = [f"{n}={os.environ[n]}" for n in KNOB_NAMES if _get(n)]
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


def _float(name: str, minimum: float | None = None) -> float | None:
    raw = _get(name)
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = None
    if value is None or (minimum is not None and value < minimum):
        Logger.warning(f"TEST KNOB: {name}={raw!r} ignored")
        return None
    return value


def go_phase_next() -> float | None:
    """The press phase (ms inside the 40 ms frame) for this operator GO,
    advancing by <step> per call; None when the knob is off."""
    raw = _get("CUEMS_TEST_GO_PHASE_SWEEP")
    if raw is None:
        return None
    try:
        start, step = (float(x) for x in raw.split(":"))
    except ValueError:
        Logger.warning(f"TEST KNOB: CUEMS_TEST_GO_PHASE_SWEEP={raw!r} ignored")
        return None
    with _lock:
        n = _counts.get("__go_phase__", 0)
        _counts["__go_phase__"] = n + 1
    return (start + n * step) % FRAME_MS


def wait_for_phase(read_ms: Callable[[], float]) -> float | None:
    """R1: wait (< one frame) until ``read_ms()`` sits at this GO's phase of
    its 40 ms frame. Returns the phase, or None when the knob is off."""
    phase = go_phase_next()
    if phase is None:
        return None
    wait = (phase - read_ms() % FRAME_MS) % FRAME_MS
    if wait > FRAME_MS - 0.5:  # already on it (float noise): no extra frame
        wait = 0.0
    if wait > 0:
        sleep(wait / 1000.0)
    Logger.warning(f"TEST KNOB: GO phase {phase:.1f} ms")
    return phase


def forced_lead_ms() -> float | None:
    """R15 / R16: L forced to this many ms, or None."""
    return _float("CUEMS_TEST_FORCE_LEAD_MS", minimum=0.0)


def hold_command_lock_ms() -> float | None:
    """R10: how long a GO holds the node's command lock on purpose, or None."""
    return _float("CUEMS_TEST_HOLD_COMMAND_LOCK_MS", minimum=0.0)


def cancel_at() -> tuple[str, float, int, int] | None:
    """R4, once per operator GO: (action, offset ms from the pass's start,
    k, len) -- the offset list taken in turn, k its 1-based index -- or None.
    Each call is one GO: it advances the counter."""
    raw = _get("CUEMS_TEST_CANCEL_AT")
    if raw is None:
        return None
    action, _, listed = raw.partition(":")
    try:
        offsets = [float(x) for x in listed.split(",")]
    except ValueError:
        offsets = []
    if action not in CANCEL_ACTIONS or not offsets:
        Logger.warning(f"TEST KNOB: CUEMS_TEST_CANCEL_AT={raw!r} ignored")
        return None
    with _lock:
        n = _counts.get("__cancel_at__", 0)
        _counts["__cancel_at__"] = n + 1
    k = n % len(offsets)
    return action, offsets[k], k + 1, len(offsets)


def reset_for_tests() -> None:
    with _lock:
        _counts.clear()
