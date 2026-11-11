# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""Wrap mode for looping AudioCues and VideoCues (plan 869ejxng3 + 1amfwm7e6cw
rev 3.17, §4.1a, §4.2, §4.4, §4.5): the player wraps the loop itself on one period P,
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

import dataclasses
from dataclasses import dataclass
from fractions import Fraction
from time import monotonic

from cuemsutils.log import Logger
from cuemsutils.tools.CTimecode import CTimecode
from cuemsutils.tools.media_sidecars import Period

WRAP_ACK_TIMEOUT_S = 1.0
CAPS_NEEDED = frozenset({"loop", "varispeed"})
CAPS_DAYALIGN = "dayalign"
# 869feynrj (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-869feynrj.md
# §4.1): the player starts itself at sample 0 once following (padded start),
# takes /cancelstart and prints the START / CANCEL / LATENCY lines.
CAPS_SELFGATE = "selfgate"
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


def player_selfgate(player) -> bool:
    """The player self-gates its start and takes ``/cancelstart`` (CAPS
    ``selfgate``, 869feynrj §4.1). Every engine change of that plan that a
    player sees is gated on this: an older player gets today's OSC."""
    caps = getattr(player, "caps", None)
    return isinstance(caps, frozenset) and CAPS_SELFGATE in caps


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
# Which length a cue loops on (D15, rev 3.15–3.17, §4.1a). The period of a
# file (the sidecar, the cache or the probe) carries both track lengths:
# A = the audio track's decoded length (num/den of a file with audio) and
# V = the video track's (realFrames at r_frame_rate). The engine chooses P per
# looping cue at load with two thresholds: T, the *slack* threshold,
# max(2 frames, 80 ms), and S, the *content* threshold, 500 ms. Up to S a
# mismatch is slack and the audio rules; beyond S it is content and the
# longest track rules.
#
#   audio-only / video-only file        -> its track
#   A/V, |A - V| <= T                   -> A for every cue (the video cut or held <= T)
#   A/V, > T, a lone cue                -> its own track (A for audio, V for video)
#   A/V, T < |A - V| <= S, a pair       -> A (the video held or cut <= 0.5 s)
#   A/V, > S, a pair                    -> max(A, V); V quantized to the audio grid
#
# A pair is at least one AudioCue and one VideoCue on the same file, looping,
# not CueList children, starting together (the D7 predicate), over the whole
# project; the grouping lives in NodeEngine, the rule here.

VC_LOOP_PERIOD = "loop_period"
# 869feynrj §4.6: /videocomposer/layer/<id>/visible_at, the self-gated reveal
# on the first presented frame with content time >= 0 (cuems-videocomposer
# utils/CapsFile.h:48, RemoteCommandRouter.cpp:134-136).
VC_VISIBLE_AT = "visible_at"
SLACK_FRAMES = 2
SLACK_FLOOR_MS = 80
PAIR_SLACK_MS = 500  # S; the same value as the videocomposer's HOLD_TAIL_MAX_MS
ORIGIN_AUDIO = "audio"
ORIGIN_VIDEO = "video"
ORIGIN_LONGEST = "longest"


def parse_fps(fps) -> tuple | None:
    """``"num/den"`` (r_frame_rate) as a pair of positive ints, or None."""
    try:
        n, d = str(fps).split("/")
        n, d = int(n), int(d)
    except (ValueError, TypeError, AttributeError):
        return None
    return (n, d) if n > 0 and d > 0 else None


def audio_length(period: Period) -> Fraction | None:
    """A, the audio track's decoded length in seconds, or None for a video-only
    file (whose num/den is already its video length). Read from the period the
    probe gave, never from a chosen one."""
    if getattr(period, "rate", None) is None:
        return None
    return Fraction(int(period.num), int(period.den))


def video_length(period: Period) -> Fraction | None:
    """V, the video track's length (realFrames / fps) in seconds, or None
    without a frame count or a frame rate."""
    rate = parse_fps(getattr(period, "fps", None))
    frames = getattr(period, "real_frames", None)
    if rate is None or not frames or frames <= 0:
        return None
    return Fraction(int(frames) * rate[1], rate[0])


def slack(period: Period) -> Fraction:
    """T in seconds: max(2 frames at the file's fps, 80 ms) (R5)."""
    floor = Fraction(SLACK_FLOOR_MS, 1000)
    rate = parse_fps(getattr(period, "fps", None))
    if rate is None:
        return floor
    return max(Fraction(SLACK_FRAMES * rate[1], rate[0]), floor)


@dataclass(frozen=True)
class LoopChoice:
    """The length one looping cue runs on, and what its shorter track does."""

    period: Period  # what goes on the wire: num/den and realFrames
    origin: str  # audio | video | longest
    paired: bool  # it belongs to a same-file pair beyond T
    audio_ms: float | None
    video_ms: float | None
    tail_ms: float  # >= 0, the period beyond (or short of) this cue's track
    treatment: str  # "" | held | cut | not drawn | silent


def _ms(x: Fraction | None) -> float | None:
    return None if x is None else float(x * 1000)


def _with_length(period: Period, num: int, den: int) -> Period:
    if num == period.num and den == period.den:
        return period
    return dataclasses.replace(period, num=int(num), den=int(den))


def choose_period(period: Period, is_video: bool, paired: bool) -> LoopChoice:
    """The D15 choice for one cue (§4.1a) from its file's period as probed.

    *paired*: the cue is in a group with at least one AudioCue and one
    VideoCue on the same file that start together. With P = V on a lone
    VideoCue the layer sees ``Pf = realFrames`` exactly (num = frames × fps
    den, den = fps num); a pair beyond S whose video is the longer gets V
    quantized to the audio sample grid (num = round(V × rate), den = rate), so
    the player's integer wrap and the videocomposer's rational wrap agree (R1).
    """
    a, v = audio_length(period), video_length(period)
    a_ms, v_ms = _ms(a), _ms(v)
    if a is None:  # video-only: num/den is V already
        return LoopChoice(period, ORIGIN_VIDEO, False, None, v_ms, 0.0, "")
    if v is None:  # audio-only, or the video length unknown (R21): the audio rules
        return LoopChoice(period, ORIGIN_AUDIO, False, a_ms, None, 0.0, "")
    diff = abs(a - v)
    pair = paired and diff > slack(period)
    if diff <= slack(period):
        p, origin = a, ORIGIN_AUDIO
        chosen = period
    elif not paired:
        if is_video:
            rate = parse_fps(period.fps)
            p, origin = v, ORIGIN_VIDEO
            chosen = _with_length(period, period.real_frames * rate[1], rate[0])
        else:
            p, origin, chosen = a, ORIGIN_AUDIO, period
    elif diff <= Fraction(PAIR_SLACK_MS, 1000):
        p, origin, chosen = a, ORIGIN_AUDIO, period
    elif a >= v:
        p, origin, chosen = a, ORIGIN_LONGEST, period
    else:
        rate = parse_fps(period.fps)
        sr = int(period.rate)
        fn, fd = rate
        num = (2 * int(period.real_frames) * fd * sr + fn) // (2 * fn)
        p, origin = Fraction(num, sr), ORIGIN_LONGEST
        chosen = _with_length(period, num, sr)
    own = v if is_video else a
    tail = p - own
    tail_ms = abs(float(tail * 1000))
    if tail == 0:
        treatment = ""
    elif not is_video:
        treatment = "silent" if tail > 0 else "cut"
    elif tail < 0:
        treatment = "cut"
    elif tail * 1000 > PAIR_SLACK_MS:
        treatment = "not drawn"
    else:
        treatment = "held"
    return LoopChoice(chosen, origin, pair, a_ms, v_ms, tail_ms, treatment)


def video_own_length_ms(period: Period) -> float | None:
    """The video stream's own length (realFrames / fps) in ms, or None."""
    return _ms(video_length(period))


def video_passes(cue) -> int:
    """The pass count on the wire: ``loop`` when finite, -1 when forever."""
    loop = int(cue.loop)
    return loop if loop >= 1 else -1


def video_wrap_eligible(cue, video_caps) -> bool:
    """Wrap mode for a VideoCue: it loops, is not a CueList child, the
    videocomposer is capable and its period (given at load) carries a video
    frame count and rate. No mismatch ever sends a cue to legacy (D15)."""
    period = period_of(cue)
    return (
        cue.loop != 1
        and not in_cuelist(cue)
        and VC_LOOP_PERIOD in (video_caps or ())
        and period is not None
        and video_length(period) is not None
    )


def vc_visible_at(video_caps) -> bool:
    """The videocomposer takes ``visible_at`` (caps token, 869feynrj §4.6).
    Without it the engine sends today's OSC: ``/visible 1`` at the reveal."""
    return VC_VISIBLE_AT in (video_caps or ())


def video_loop_args(cue) -> list:
    """``/loop`` for a VideoCue in wrap mode: [1, passes]."""
    return [1, video_passes(cue)]


def video_period_args(period: Period) -> list:
    """``/loop/period``: [num, den, realFrames]."""
    return [int(period.num), int(period.den), int(period.real_frames)]


def video_legacy_pass_ms(cue) -> float | None:
    """The per-pass re-anchor length of a VideoCue in legacy mode (an old
    videocomposer, or a CueList child): min(P, V) (R24: an old layer asked for
    frames past its end would seek on every vsync of the tail), None (the
    stored media duration) without a period or a video length."""
    p = period_of(cue)
    v = video_own_length_ms(p) if p is not None else None
    if v is None:
        return None
    return min(p.ms, v)


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
