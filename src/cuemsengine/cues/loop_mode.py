# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Wrap mode for looping AudioCues and VideoCues (plan 869ejxng3 + 1amfwm7e6cw
rev 3.14, §4.2, §4.4, §4.5): the player wraps the loop itself on one period P,
gapless, and follows MTC by varispeed; the videocomposer wraps the layer on the
same P (Phase B, the helpers at the end of this module); the engine only
re-sends ``/loop`` (and, for video, ``/loop/period``) per pass.

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


# --------------------------------------------------------------------------
# Video (Phase B, §4.4/§4.5): the videocomposer wraps a looping layer on the
# same P as the audio player, given as /loop [1, passes] + /loop/period
# [num, den, realFrames], when its caps file names ``loop_period`` and the
# file's band is 1 or 2. Band 3 (> 2 frames and > 1 % between P and the video's
# own length) runs legacy: re-anchored on the video's own length, WARNING at
# load (an operator error under the guarantee).

VC_LOOP_PERIOD = "loop_period"
BAND_HOLD = 1  # |Pf - realFrames| <= 2 frames: hold or cut at the loop cut
BAND_STRETCH = 2  # > 2 frames and <= 1 %: stretched over the pass
BAND_LEGACY = 3  # > 2 frames and > 1 %: no period, legacy


def parse_fps(fps) -> tuple | None:
    """``"num/den"`` (r_frame_rate) as a pair of positive ints, or None."""
    try:
        n, d = str(fps).split("/")
        n, d = int(n), int(d)
    except (ValueError, TypeError, AttributeError):
        return None
    return (n, d) if n > 0 and d > 0 else None


def video_band(period: Period) -> tuple | None:
    """``(band, stretch %)`` of a VideoCue's period against its realFrames, in
    integer rationals as the videocomposer computes it; None without a frame
    count or a frame rate (the cue then runs legacy)."""
    rate = parse_fps(getattr(period, "fps", None))
    frames = getattr(period, "real_frames", None)
    if rate is None or not frames or frames <= 0:
        return None
    a = period.num * rate[0]  # Pf = a / b frames
    b = period.den * rate[1]
    diff = abs(a - frames * b)
    stretch = 100.0 * (a / b - frames) / frames
    if diff <= 2 * b:
        return BAND_HOLD, stretch
    if 100 * diff > frames * b:
        return BAND_LEGACY, stretch
    return BAND_STRETCH, stretch


def video_own_length_ms(period: Period) -> float | None:
    """The video stream's own length (realFrames / fps) in ms, or None."""
    rate = parse_fps(getattr(period, "fps", None))
    frames = getattr(period, "real_frames", None)
    if rate is None or not frames:
        return None
    return frames * rate[1] * 1000.0 / rate[0]


def video_passes(cue) -> int:
    """The pass count on the wire: ``loop`` when finite, -1 when forever."""
    loop = int(cue.loop)
    return loop if loop >= 1 else -1


def video_wrap_eligible(cue, video_caps) -> bool:
    """Wrap mode for a VideoCue: it loops, is not a CueList child, the
    videocomposer is capable and its band (given at load) is 1 or 2."""
    return (
        cue.loop != 1
        and not in_cuelist(cue)
        and VC_LOOP_PERIOD in (video_caps or ())
        and period_of(cue) is not None
        and getattr(cue, "_video_band", None) in (BAND_HOLD, BAND_STRETCH)
    )


def video_loop_args(cue) -> list:
    """``/loop`` for a VideoCue in wrap mode: [1, passes]."""
    return [1, video_passes(cue)]


def video_period_args(period: Period) -> list:
    """``/loop/period``: [num, den, realFrames]."""
    return [int(period.num), int(period.den), int(period.real_frames)]


def video_legacy_pass_ms(cue) -> float | None:
    """The per-pass re-anchor length of a VideoCue in legacy mode: P for band
    1/2 (an old videocomposer), the video's own length in band 3, None (the
    stored media duration) without a period."""
    p = period_of(cue)
    if p is None:
        return None
    if getattr(cue, "_video_band", None) == BAND_LEGACY:
        return video_own_length_ms(p)
    if getattr(cue, "_video_band", None) in (BAND_HOLD, BAND_STRETCH):
        return p.ms
    return None


def send_video_wrap(cue, layer_ids) -> None:
    """``/loop [1, passes]`` then ``/loop/period`` to every layer (before
    ``/mtcfollow 1`` at GO; again every pass, H10)."""
    period = period_of(cue)
    for layer_id in layer_ids:
        path = f"/videocomposer/layer/{layer_id}"
        try:
            cue._osc.set_value(f"{path}/loop", video_loop_args(cue))
            cue._osc.set_value(f"{path}/loop/period", video_period_args(period))
        except Exception as e:
            Logger.error(f"Video cue {cue.id} layer {layer_id}: wrap sends failed: {e}")
