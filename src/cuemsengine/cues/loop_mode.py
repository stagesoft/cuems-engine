# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Wrap mode for looping AudioCues (plan 869ejxng3 + 1amfwm7e6cw rev 3.14,
§4.2, §4.5): the player wraps the loop itself on one period P, gapless, and
follows MTC by varispeed; the engine only re-sends ``/loop`` per pass.

A cue runs in **wrap mode** when its player printed ``CAPS: loop varispeed``,
it loops (``loop != 1``), it is not a CueList child, and its period P is known
(``cue._loop_period``, given at load). Everything else is **legacy**: today's
per-pass offset re-anchor, on P when P is known (a gap per pass, no cumulative
drift), on the stored media duration otherwise.

The ack rules (L6, M6, J11): ``_player_wraps`` is set by a ``wrap`` LOOP line,
never by the send; no ``wrap`` within 1 s of the reveal, or an ``off`` newer
than the last ``wrap``, is an ERROR and **latches** legacy for the rest of this
GO (``/loop [1]``, the re-sends stopped, a per-pass start on P).

The cue start goes as ``/start_tod`` (the MTC position modulo 24 h, whole ms)
to a player whose CAPS line carries ``dayalign`` (an independent predicate), as
the float ``/offset`` (= -start, the engine's extended ms) to every other player
(cuems-RELATIONS Plans/2026-10-25-mtc-day-align-24h-wrap.md §7.2; ``/offset_i``
is gone).
"""

from time import monotonic

from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.media_sidecars import Period

WRAP_ACK_TIMEOUT_S = 1.0
CAPS_NEEDED = frozenset({"loop", "varispeed"})
CAPS_DAYALIGN = "dayalign"
DAY_MS = 86_400_000


def period_of(cue) -> Period | None:
    """The cue's loop period, given at load, or None."""
    p = getattr(cue, "_loop_period", None)
    return p if isinstance(p, Period) else None


def in_cuelist(cue) -> bool:
    return getattr(cue, "_in_cuelist", False) is True


def player_capable(player) -> bool:
    caps = getattr(player, "caps", None)
    return isinstance(caps, frozenset) and CAPS_NEEDED <= caps


def player_dayalign(player) -> bool:
    """The player converts ``/start_tod`` into its own MTC day (CAPS ``dayalign``)."""
    caps = getattr(player, "caps", None)
    return isinstance(caps, frozenset) and CAPS_DAYALIGN in caps


def start_tod(start_ms: float) -> int:
    """The cue start as MTC position modulo 24 h, whole ms: rounded first, then
    taken modulo the day, so the value is always in [0, 86 399 999]."""
    return round(start_ms) % DAY_MS


def start_message(cue, start_ms: float) -> tuple:
    """The (path, value) carrying the cue start to its player: ``/start_tod`` to a
    ``dayalign`` player, the float ``/offset`` (= -start) otherwise."""
    if getattr(cue, "_audio_dayalign", False) is True:
        return "/start_tod", start_tod(start_ms)
    return "/offset", -start_ms


def tc_at(framerate, ms: float) -> CTimecode:
    """An absolute MTC instant, rounded once from its ms value (G20)."""
    return CTimecode(framerate=framerate, start_seconds=ms / 1000)


def loop_args(cue, period: Period) -> list:
    """``/loop`` for wrap mode: [passes, num, den]; passes <= 0 is forever."""
    return [int(cue.loop), int(period.num), int(period.den)]


def wrap_active(cue) -> bool:
    """Wrap mode was asked for this GO and has not fallen back."""
    return (
        getattr(cue, "_wrap_requested", False) is True
        and getattr(cue, "_wrap_fallback", False) is not True
    )


def check_wrap_ack(cue, player) -> None:
    """Apply the ack rules for a cue in wrap mode; fall back on a timeout or ``off``."""
    if not wrap_active(cue) or player is None:
        return
    ack = getattr(player, "loop_ack", None)
    if ack is not None and ack.mode == "wrap":
        cue._player_wraps = True
    off = (
        ack is not None
        and ack.mode == "off"
        and ack.ver > getattr(player, "last_wrap_ver", -1)
    )
    revealed_at = getattr(cue, "_wrap_reveal_t", None)
    late = (
        not getattr(cue, "_player_wraps", False)
        and revealed_at is not None
        and monotonic() - revealed_at > WRAP_ACK_TIMEOUT_S
    )
    if off:
        fall_back(cue, "the player gave up wrapping (LOOP … off)")
    elif late:
        fall_back(cue, f"no wrap ack within {WRAP_ACK_TIMEOUT_S:.0f} s of the reveal")


def fall_back(cue, reason: str) -> None:
    """Latch legacy for this GO: ``/loop [1]``, then per-pass offsets on P."""
    cue._wrap_fallback = True
    cue._player_wraps = False
    Logger.error(
        f"Audio cue {cue.id}: {reason}; legacy loop from the next pass "
        "(a gap per pass, re-anchored on P)"
    )
    try:
        cue._osc.set_value("/loop", [1])
    except Exception as e:
        Logger.warning(f"Audio cue {cue.id}: /loop [1] failed: {e}")
