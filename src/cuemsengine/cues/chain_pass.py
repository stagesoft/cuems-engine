# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The pure part of the Auto-continue rule (1amfwm7jnqf).

cuems-RELATIONS `Plans/2026-11-18-autocontinue-cumulative-waits.md` (rev 9.1,
Design §1, §3, §5); its executable model is
`baselines/autocontinue-cumulative/model/chain_model.py`, and where this module
transcribes it, it names the function. No engine imports: the engine's cues
are read by duck typing (`prewait` / `postwait` with `.milliseconds_exact`,
`post_go`, `_target_object`, `enabled`).

- the two advance modes: ``sequential`` ("en serie") adds prewait + postwait,
  ``parallel`` ("en paralelo", the 2026-08-14 rule) adds 0;
- :func:`layout`: one pass laid out from the script alone (the model's
  ``time_chain``); it reads no flag and no locality;
- :class:`Pass`: what go() mints for one entry into a chain;
- the flag as every node sees it (D31 d): :func:`ui_toggle`,
  :func:`action_toggle`, :func:`common_enabled`, :func:`retire`, with the
  records a node keeps on a cue;
- :class:`StepOrder`: a node does what more than one node does in the order
  of the instants at which it is due;
- :func:`as_enabled`, :func:`cue_enabled`, :func:`normalise_enabled`: a cue's
  ``enabled`` as a real bool, whatever the script reader left in it (a
  saved-disabled DmxCue is read as the string ``'False'``, which is truthy).
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from cuemsutils.log import Logger

SEQUENTIAL = "sequential"  # "en serie": a cue's prewait + postwait advance the next
PARALLEL = "parallel"  # "en paralelo": every cue of the chain arrives together
MODES = (SEQUENTIAL, PARALLEL)

#: D31 (d): what more than one node does with a flag counts a UI toggle from
#: its send time + W (Ion, 2026-11-23: "500ms es aceptable").
W_MS = 500.0
#: Design §5: a step that waits this long for another logs one WARNING ...
STEP_WARN_S = 0.2
#: ... and gives up after this long, with an ERROR (what arm() gives an arm in
#: flight): a hung handler must not freeze a node's show.
STEP_GIVE_UP_S = 5.0
#: A chain longer than this is cut (a pathological script).
MAX_LAYOUT = 1024
#: How many retired records a cue keeps to detect a late read.
_RETIRED_KEPT = 64
_STEP_POLL_S = 0.005


def _ms(tc) -> float:
    exact = getattr(tc, "milliseconds_exact", None)
    if exact is None:
        exact = getattr(tc, "milliseconds", 0) or 0
    return float(exact)


def _check_mode(mode) -> str:
    if mode not in MODES:
        raise ValueError(f"unknown chain mode {mode!r} (one of {', '.join(MODES)})")
    return mode


def advance_ms(cue, mode: str = SEQUENTIAL) -> float:
    """What a cue adds to the arrival of the cue after it (the model's
    ``advance``): prewait + postwait in ``sequential``, 0 in ``parallel``.
    Every cue counts, enabled or not (D26)."""
    if _check_mode(mode) == PARALLEL:
        return 0.0
    return _ms(cue.prewait) + _ms(cue.postwait)


def layout(entry, anchor_ms: float, mode: str = SEQUENTIAL) -> list:
    """The layout of one pass: ``[(cue, arrival_ms)]`` from ``entry`` along its
    ``post_go="go"`` links (``_target_object``), ending after the first cue
    that is not ``go`` or where the chain would reach a cue a second time
    (the model's ``time_chain``). It reads no flag and no locality: the same
    on every node, whatever is enabled (D26)."""
    _check_mode(mode)
    out, arrival, cue, seen = [], float(anchor_ms), entry, set()
    while cue is not None and id(cue) not in seen and len(out) < MAX_LAYOUT:
        seen.add(id(cue))
        out.append((cue, arrival))
        if getattr(cue, "post_go", None) != "go":
            break
        arrival += advance_ms(cue, mode)
        cue = getattr(cue, "_target_object", None)
    return out


class Pass:
    """One entry into a chain (operator GO, Auto follow, ``play`` /
    ``fade_in``, a relayed follow), minted by go() in its commit section and
    written on every cue of its layout (``cue._pass``).

    epoch: the chain epoch (CueHandler._chain_epoch) of this entry.
    anchor_ms: its trigger on the MTC axis.
    layout: ``[(cue, arrival_ms)]`` (:func:`layout`).
    root_seq: the UI toggles the node had received when the GO this pass
        descends from arrived (D31 d, addition 3); a pass a follow or a
        loop-back starts inherits its parent's.
    """

    def __init__(self, epoch, anchor_ms, layout, root_seq=0, mode=SEQUENTIAL):
        self.epoch = epoch
        self.anchor_ms = float(anchor_ms) if anchor_ms is not None else None
        self.layout = list(layout)
        self.root_seq = int(root_seq or 0)
        self.mode = mode
        #: the node's pass number, for the journal (set by whoever logs it)
        self.no = epoch

    @property
    def entry(self):
        return self.layout[0][0] if self.layout else None

    def arrival_of(self, cue):
        """The arrival of ``cue`` in this pass (by identity), or None."""
        for c, arrival in self.layout:
            if c is cue:
                return arrival
        return None

    def position_of(self, cue):
        for k, (c, _) in enumerate(self.layout):
            if c is cue:
                return k
        return None

    def __repr__(self):
        entry = self.entry
        return (
            f"Pass({self.epoch}, anchor={self.anchor_ms}, "
            f"entry={getattr(entry, 'id', entry)}, {len(self.layout)} cues)"
        )


# ---------------------------------------------------------------------------
# a cue's enabled as a bool
# ---------------------------------------------------------------------------

_ENABLED_TRUE = frozenset({"true", "1", "yes", "on"})
_ENABLED_FALSE = frozenset({"false", "0", "no", "off"})
_ENABLED_MISSING = object()
#: the cues (or values) already warned about, so each warns once
_ENABLED_WARNED: set = set()


def as_enabled(value, cue_id=None) -> bool:
    """``value`` (a cue's ``enabled``) as a bool. A bool passes; None is
    True; a string is read strictly (``true/false/1/0/yes/no/on/off``, any
    case); an int 0 / 1 is its bool. Anything else is True, as the editor
    means a cue it has not disabled, with one WARNING per cue.

    The script reader leaves the text of the XML in some cues (a DmxCue saved
    disabled has ``enabled == 'False'``), and ``bool('False')`` is True."""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _ENABLED_TRUE:
            return True
        if word in _ENABLED_FALSE:
            return False
    elif isinstance(value, int) and value in (0, 1):
        return bool(value)
    key = str(cue_id) if cue_id is not None else repr(value)
    if key not in _ENABLED_WARNED:
        _ENABLED_WARNED.add(key)
        Logger.warning(
            f"cue {cue_id}: enabled is {value!r}, which is not a yes or a no;"
            " the cue is taken as enabled"
        )
    return True


def cue_enabled(cue, default: bool = True) -> bool:
    """The cue's ``enabled`` as a bool (:func:`as_enabled`); ``default`` when
    the cue has none."""
    value = getattr(cue, "enabled", _ENABLED_MISSING)
    if value is _ENABLED_MISSING:
        return default
    return as_enabled(value, getattr(cue, "id", None))


def normalise_enabled(cuelist) -> int:
    """At load: every cue under ``cuelist`` (and the cuelist itself) gets its
    ``enabled`` as a bool, so every later read of ``cue.enabled`` is one.
    Returns how many cues held something else."""
    changed, seen, todo = 0, set(), [cuelist]
    while todo:
        cue = todo.pop()
        if cue is None or id(cue) in seen:
            continue
        seen.add(id(cue))
        value = getattr(cue, "enabled", _ENABLED_MISSING)
        if value is not _ENABLED_MISSING and not isinstance(value, bool):
            try:
                cue.enabled = as_enabled(value, getattr(cue, "id", None))
                changed += 1
            except Exception as e:
                Logger.error(f"cue {getattr(cue, 'id', cue)}: enabled not set ({e})")
        todo.extend(getattr(cue, "contents", None) or [])
    if changed:
        Logger.info(f"{changed} cue(s) had enabled read as text; now a bool")
    return changed


# ---------------------------------------------------------------------------
# the flag as every node sees it (D31 d), and its records
# ---------------------------------------------------------------------------

_FLAG_LOCK = threading.RLock()
#: the cues that hold records on this node (id -> cue)
_WITH_RECORDS: dict = {}


def _records(cue) -> list:
    recs = cue.__dict__.get("_toggle_records") if hasattr(cue, "__dict__") else None
    if recs is None:
        recs = []
        try:
            cue._toggle_records = recs
        except Exception:
            pass
    return recs


def _base(cue) -> bool:
    """The cue's value without its pending records."""
    if not _records(cue):
        return cue_enabled(cue)
    base = getattr(cue, "_toggle_base", _ENABLED_MISSING)
    if base is _ENABLED_MISSING:
        return cue_enabled(cue)
    return as_enabled(base, getattr(cue, "id", None))


def _counts(since, seq, instant, root) -> bool:
    return since < instant or seq <= root


def _count(value, recs, instant, root):
    for seq, since, v in recs:
        if _counts(since, seq, instant, root):
            value = v
    return value


def ui_toggle(cue, value, sent_ms, now_ms, seq) -> bool:
    """A UI toggle reaches this node (the receive hook, in bus order). The flag
    is set at once, whether or not it changes; a record ``(seq, sent + W,
    value)`` is kept on the cue for what more than one node does with it.
    Returns False when the toggle could not be placed by its send time (none,
    or more than W from the node's MTC either way): it then counts from its
    arrival, ``now_ms``, and the caller logs the WARNING."""
    try:
        sent = float(sent_ms) if sent_ms is not None else None
    except (TypeError, ValueError):
        sent = None
    if sent is None or now_ms is None or abs(float(now_ms) - sent) > W_MS:
        place_at_arrival(cue, value, now_ms, seq)
        return False
    _append(cue, value, sent + W_MS, seq)
    return True


def place_at_arrival(cue, value, now_ms, seq) -> None:
    """A toggle that cannot be placed by its send time: it counts from its
    arrival (``now_ms``), as on rc_1; a read for an earlier instant does not
    see it."""
    since = float(now_ms) if now_ms is not None else float("-inf")
    _append(cue, value, since, seq)


def _append(cue, value, since, seq) -> None:
    value = bool(value)
    with _FLAG_LOCK:
        recs = _records(cue)
        if not recs:
            cue._toggle_base = cue_enabled(cue)
        recs.append((int(seq), since, value))
        cue.enabled = value
        _WITH_RECORDS[id(cue)] = cue


def action_toggle(cue, value, instant_ms, root_seq=0) -> bool:
    """An ``enable`` / ``disable`` ActionCue writes the flag at its start, on
    every node: after the UI toggles that count at that instant and before
    the others, which stay pending and keep the last word (S72). Returns the
    flag the cue has afterwards (``cue.enabled``)."""
    value = bool(value)
    with _FLAG_LOCK:
        recs = _records(cue)
        later = [r for r in recs if not _counts(r[1], r[0], instant_ms, root_seq)]
        _check_late(cue, instant_ms, root_seq, later=later)
        cue._toggle_base = value
        recs[:] = later
        live = later[-1][2] if later else value
        cue.enabled = live
        return live


def common_enabled(cue, instant_ms, root_seq=0) -> bool:
    """The flag as every node sees it at ``instant_ms``: the cue's value, then
    the last record in bus order that counts there (sent more than W before
    it, or come before the GO the pass descends from: ``seq <= root_seq``)."""
    with _FLAG_LOCK:
        value = _count(_base(cue), list(_records(cue)), instant_ms, root_seq)
        _check_late(cue, instant_ms, root_seq, value=value)
        return bool(value)


def _check_late(cue, instant_ms, root_seq, value=None, later=None) -> None:
    """A read that a retired record would have answered otherwise: ERROR
    (the model counts these; 0 under the rule). Call with _FLAG_LOCK."""
    retired = cue.__dict__.get("_toggle_retired") if hasattr(cue, "__dict__") else None
    if not retired:
        return
    base0, old = retired
    full = old + list(_records(cue))
    if value is not None:
        if bool(_count(base0, full, instant_ms, root_seq)) == bool(value):
            return
    else:
        later0 = [r for r in full if not _counts(r[1], r[0], instant_ms, root_seq)]
        if later0 == later:
            return
    Logger.error(
        f"late read of {getattr(cue, 'id', cue)}'s flag for the instant "
        f"{float(instant_ms):.0f} ms: a toggle it needed was already retired"
    )


def retire(floor_ms, cues=None) -> int:
    """Fold into each cue's value, in bus order, the records that count from
    before ``floor_ms``: the earliest instant anything on the node can still
    read (Design §3). A record that cannot go yet keeps the ones behind it.
    Returns how many were folded."""
    folded = 0
    with _FLAG_LOCK:
        if cues is None:
            cues = list(_WITH_RECORDS.values())
        for cue in cues:
            recs = (
                cue.__dict__.get("_toggle_records")
                if hasattr(cue, "__dict__")
                else None
            )
            if not recs:
                continue
            base = _base(cue)
            gone = []
            while recs and recs[0][1] < floor_ms:
                rec = recs.pop(0)
                base = rec[2]
                gone.append(rec)
            if not gone:
                continue
            folded += len(gone)
            retired = cue.__dict__.get("_toggle_retired")
            if retired is None:
                retired = [_toggle_base0(cue, gone), []]
            retired[1].extend(gone)
            while len(retired[1]) > _RETIRED_KEPT:
                retired[0] = retired[1].pop(0)[2]
            cue._toggle_retired = retired
            cue._toggle_base = base
            if not recs:
                _WITH_RECORDS.pop(id(cue), None)
    return folded


def _toggle_base0(cue, gone) -> bool:
    return bool(cue.__dict__.get("_toggle_base", gone[0][2]))


def forget(cues=None) -> None:
    """STOP and load: every record is folded into the flag as it stands
    (``cues`` None: every cue that holds one)."""
    with _FLAG_LOCK:
        if cues is None:
            cues = list(_WITH_RECORDS.values())
        for cue in cues:
            _WITH_RECORDS.pop(id(cue), None)
            d = getattr(cue, "__dict__", None)
            if not d:
                continue
            d.pop("_toggle_records", None)
            d.pop("_toggle_retired", None)
            d.pop("_toggle_base", None)


def has_records(cue) -> bool:
    d = getattr(cue, "__dict__", None)
    return bool(d and d.get("_toggle_records"))


# ---------------------------------------------------------------------------
# what a thread is entering, and the step it is doing
# ---------------------------------------------------------------------------

_CTX = threading.local()
_UNSET = object()


@contextmanager
def entry(why=_UNSET, root=_UNSET, release=_UNSET):
    """Thread context for a go_from / go() made on this thread: ``why`` the
    entry is made (``play``, ``fade_in``, ``follow``; the loop guard),
    ``root`` the pass it descends from had (D31 d, addition 3), ``release``
    the step this thread is doing, released at its deciding point."""
    saved = {k: getattr(_CTX, k, _UNSET) for k in ("why", "root", "release")}
    for k, v in (("why", why), ("root", root), ("release", release)):
        if v is not _UNSET:
            setattr(_CTX, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is _UNSET:
                if hasattr(_CTX, k):
                    delattr(_CTX, k)
            else:
                setattr(_CTX, k, v)


def current_why():
    v = getattr(_CTX, "why", None)
    return None if v is _UNSET else v


def current_root() -> int:
    v = getattr(_CTX, "root", 0)
    return 0 if v is _UNSET or v is None else int(v)


def release_step() -> None:
    """The step this thread is doing has reached its deciding point (a stop
    after its flags and walk, a play when its new pass is minted): what
    waits for it may go. Idempotent; never raises."""
    fn = getattr(_CTX, "release", None)
    if fn is None or fn is _UNSET:
        return
    _CTX.release = None
    try:
        fn()
    except Exception as e:
        Logger.error(f"step release failed: {e}")


# ---------------------------------------------------------------------------
# the node's order of steps (Design §5)
# ---------------------------------------------------------------------------


class StepOrder:
    """The steps a node still has to do for what more than one node does (an
    ActionCue's or a fade's start, a DMX cue's scene send and start, a
    CueList's setup, the decision of a cue with several owners), keyed
    ``(instant, anchor, entry, position, sub)``: the same on every node.

    A thread does its step only when no pending step has a smaller key
    (:meth:`wait_turn`); a step leaves at its deciding point (:meth:`done`),
    and whatever ends its thread leaves it too. A wait logs one WARNING after
    STEP_WARN_S and gives up after STEP_GIVE_UP_S with an ERROR."""

    def __init__(self, clock=None, sleep=None):
        self._clock = clock or time.monotonic
        self._sleep = sleep
        self._cv = threading.Condition()
        self._pending: dict = {}

    def add(self, key, name="") -> None:
        with self._cv:
            self._pending[key] = name

    def done(self, key) -> None:
        with self._cv:
            self._pending.pop(key, None)
            self._cv.notify_all()

    def clear(self) -> None:
        with self._cv:
            self._pending.clear()
            self._cv.notify_all()

    def pending(self) -> list:
        with self._cv:
            return sorted(self._pending)

    def first_before(self, key):
        """(key, name) of the smallest pending step before ``key``, or None."""
        with self._cv:
            return self._first_locked(key)

    def _first_locked(self, key):
        best = None
        for k in self._pending:
            if k == key:
                continue
            try:
                smaller = k < key
            except TypeError:
                smaller = str(k) < str(key)
            if not smaller:
                continue
            try:
                better = best is None or k < best
            except TypeError:
                better = str(k) < str(best)
            if better:
                best = k
        return None if best is None else (best, self._pending[best])

    def any_due_by(self, instant_ms) -> bool:
        """A pending step due at or before ``instant_ms`` (a hand-over enters
        its new pass only after those)."""
        with self._cv:
            return any(k[0] <= instant_ms for k in self._pending)

    def wait_turn(self, key, name=None, abort=None) -> bool:
        """Block until no pending step has a smaller key. True when it is this
        step's turn (or ``abort()`` says the waiter has nothing to do any
        more); False when it gave up after STEP_GIVE_UP_S."""
        t0 = self._clock()
        warned = False
        with self._cv:
            me = name or self._pending.get(key) or str(key)
        while True:
            if abort is not None and abort():
                return True
            with self._cv:
                first = self._first_locked(key)
                if first is None:
                    return True
                other_key, other = first
                waited = self._clock() - t0
                if waited >= STEP_GIVE_UP_S:
                    Logger.error(
                        f"{me} gave up waiting for {other} after "
                        f"{STEP_GIVE_UP_S:.0f} s"
                    )
                    return False
                if not warned and waited >= STEP_WARN_S:
                    warned = True
                    Logger.warning(
                        f"{me} still waiting for {other} (due at "
                        f"{float(other_key[0]):.0f} ms)"
                    )
                if self._sleep is None:
                    self._cv.wait(_STEP_POLL_S)
                    continue
            self._sleep(_STEP_POLL_S)
