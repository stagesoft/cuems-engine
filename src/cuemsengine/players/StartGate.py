# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
"""The engine's half of a self-gated audio start (CAPS ``selfgate``, 869feynrj).

cuems-RELATIONS ``Plans/2026-11-03-audio-first-pass-head-869feynrj.md`` §4.2,
§4.3, §4.5e, §8; executable spec ``baselines/869feynrj-model/cancel_model.py``.

A ``selfgate`` player starts ITSELF at sample 0 once it follows MTC, so the
engine commits ``/mtcfollow 1`` early (the follow commit, ~F before the start)
and every path that cancels a pass the player may already be following sends
``/cancelstart <seq> <fade_ms>``. This module owns what is per player:

- ``may_follow`` (set on every ``/mtcfollow 1`` sent, cleared on
  ``/mtcfollow 0``, ``/cancelstart`` and a kill), the pass the last follow
  commit belongs to, and the per-player ``/cancelstart`` sequence;
- the **cancel records** {seq, cue, pass, kind, t_sent}: kind ``cancel`` (a
  pass the engine had not revealed) or ``stop_of_playing`` (STOP, D10; the
  other stops of a playing cue, D12). The player's ``[OK] CANCEL <seq> <state>
  <ms>`` closes the record with that seq; ``play`` on a ``cancel`` record is the
  WARNING "started <ms> ms before its cancel; stopped (faded)";
- one watchdog per node engine: no ack within 100 ms while the player is
  alive -> one re-send with the same seq; no ack within another 100 ms ->
  ERROR. A newer follow commit on the player closes its older records, and a
  re-send whose pass is no longer the player's committed one is dropped, so a
  re-send never fades a newer pass (review 4 M1). Killing the player closes its
  records first (PlayerHandler), so a player that is gone never raises a false
  ERROR;
- the fade deadline: the disconnect of a player waits transit + one period +
  ``fade_ms`` + margin after the last ``/cancelstart`` (D12, review 4 m4), so a
  stop fades instead of clicking;
- the START lines: a start more than 3 samples late is a WARNING (operator GOs
  and chain cues) or an INFO plus one WARNING per cue per load (the seeded
  paths Phase B fixes: go_at_end, ActionCue play/fade_in) (§4.5e); a follow
  commit with no START by start + period + latency gets ``/mtcfollow 1``
  re-sent once, with a WARNING (§8, a lost follow);
- the LATENCY lines, handed to the node engine (§4.5d).

Locking: one lock of its own, always the innermost (never held while another
lock is taken). Callers that decide under ``CueHandler._lock`` call the send
methods inside that section, so the decision, the record and the datagram are
one step, and every send to a player goes out in the order of the decisions.
"""

from dataclasses import dataclass, field
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Callable

from cuemsutils.log import Logger

from ..cues import loop_mode
from .Player import CancelAck, LatencyLine, Player, StartLine

DEFAULT_FADE_MS = 5
ACK_TIMEOUT_S = 0.100
WATCHDOG_TICK_S = 0.010
# The disconnect waits FADE_TRANSIT_MS + one period + fade_ms + FADE_MARGIN_MS
# after a /cancelstart: >= 25 ms at fade 5 and 512 frames at 48 kHz.
FADE_TRANSIT_MS = 2.0
FADE_MARGIN_MS = 8.0
# A player that printed no LATENCY line yet: 512 frames at 48 kHz.
DEFAULT_PERIOD_MS = 512 * 1000.0 / 48000
DEFAULT_LATENCY_MS = 1536 * 1000.0 / 48000
# G1's tolerance (soxr's constant offset is ~2 samples): a START target above
# this many samples lost part of the head (§4.5e).
LATE_START_TOLERANCE_SAMPLES = 3
# The lost-follow check (§8) runs at start + period + latency + this: the START
# line leaves the player's log ring within 10 ms and reaches the reader at once.
START_CHECK_SLACK_MS = 30.0


@dataclass
class CancelRecord:
    """One ``/cancelstart`` the engine sent (§4.3 "Cancel records")."""

    seq: int
    cue_id: str
    pass_id: tuple | None
    kind: str  # "cancel" | "stop_of_playing"
    fade_ms: int
    t_sent: float
    client: object = field(repr=False, default=None)
    resent: bool = False
    t_resent: float | None = None


@dataclass
class _StartCheck:
    """A follow commit whose START line is due (§8)."""

    player: object
    client: object
    cue_id: str
    pass_id: tuple
    deadline: float


def _alive(player) -> bool:
    """True while the player's process runs."""
    process = getattr(player, "p", None)
    if process is None:
        return False
    try:
        return process.poll() is None
    except Exception:
        return False


def _period_ms(player) -> float:
    lat = getattr(player, "latency", None)
    if isinstance(lat, LatencyLine) and lat.rate > 0:
        return lat.period_ms
    return DEFAULT_PERIOD_MS


def _latency_ms(player) -> float:
    lat = getattr(player, "latency", None)
    if isinstance(lat, LatencyLine) and lat.rate > 0:
        return lat.frames * 1000.0 / lat.rate
    return DEFAULT_LATENCY_MS


def fade_wait_ms(player, fade_ms: int = DEFAULT_FADE_MS) -> float:
    """How long a disconnect waits after a /cancelstart (D12)."""
    return FADE_TRANSIT_MS + _period_ms(player) + float(fade_ms) + FADE_MARGIN_MS


class StartGate:
    """Per-player follow / cancel state, the cancel records and their watchdog.

    One instance per process (START_GATE). ``autostart=False`` keeps the
    watchdog thread from starting; tests then call scan(now) themselves.
    """

    def __init__(self, autostart: bool = True):
        self._lock = Lock()
        self._open: set = set()  # players with open cancel records
        self._fading: set = set()  # players with a fade deadline
        self._checks: list[_StartCheck] = []
        self._thread: Thread | None = None
        self.autostart = autostart
        self.node_name = "this node"
        self._seeded_warned: set = set()
        self._latency_listener: Callable | None = None

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------
    def set_node_name(self, name: str) -> None:
        self.node_name = str(name)

    def set_latency_listener(self, fn: Callable | None) -> None:
        """fn(player, LatencyLine), called from the player's stdout reader
        for every LATENCY line (outside this module's lock)."""
        self._latency_listener = fn

    def reset_for_load(self) -> None:
        """A new load: the once-per-load WARNING may be said again."""
        with self._lock:
            self._seeded_warned.clear()
            self._checks = []

    def reset_for_tests(self) -> None:
        with self._lock:
            self._open.clear()
            self._fading.clear()
            self._checks = []
            self._seeded_warned.clear()

    # ------------------------------------------------------------------
    # sends
    # ------------------------------------------------------------------
    def commit_follow(self, cue, player, client, gen) -> bool:
        """The follow commit (§4.2 step 2): ``/mtcfollow 1`` to a selfgate
        player. The caller decided it under CueHandler._lock (not stopped,
        this pass's generation, the start sent) and calls this in that same
        section. Closes the player's older cancel records: they belong to an
        earlier pass."""
        with self._lock:
            try:
                client.set_value("/mtcfollow", 1)
            except Exception as e:
                Logger.warning(f"Audio cue {cue.id}: follow commit failed: {e}")
                return False
            player.may_follow = True
            player.follow_pass = (str(cue.id), gen)
            player.follow_cue = cue
            player.starts_since_commit = 0
            if player.cancel_records:
                player.cancel_records.clear()
                self._open.discard(player)
            self._checks = [c for c in self._checks if c.player is not player]
        return True

    def send_follow(
        self, player, client, cue, gen, still_current: Callable | None = None
    ) -> bool:
        """A ``/mtcfollow 1`` to a selfgate player outside a follow commit:
        the reveal's fallback when the commit did not happen. Sent under this
        lock after ``still_current`` is re-checked (a pass stopped or replaced
        meanwhile sends nothing), and the player marked as following this
        pass, so every later stop reaches it with ``/cancelstart``. Returns
        True if sent."""
        with self._lock:
            if still_current is not None and not still_current():
                return False
            client.set_value("/mtcfollow", 1)
            if isinstance(player, Player):
                player.may_follow = True
                if gen is not None:
                    player.follow_pass = (str(cue.id), gen)
                    player.follow_cue = cue
                    player.starts_since_commit = 0
                    if player.cancel_records:
                        player.cancel_records.clear()
                        self._open.discard(player)
        return True

    def follow_off(self, player, client, still_current: Callable | None = None):
        """``/mtcfollow 0`` (the legacy end of a pass) and may_follow cleared.

        ``still_current`` is re-checked under this lock right before the send:
        a pass superseded meanwhile sends nothing, so it can never undo the
        new pass's follow commit (whose ``/mtcfollow 1`` goes out under the
        same lock). Returns True if sent."""
        with self._lock:
            if still_current is not None and not still_current():
                return False
            client.set_value("/mtcfollow", 0)
            if player is not None:
                player.may_follow = False
        return True

    def cancel(
        self, cue, player, client, kind: str, fade_ms: int = DEFAULT_FADE_MS
    ) -> CancelRecord | None:
        """``/cancelstart <seq> <fade_ms>`` to a player that may follow, and
        its record (§4.3). Returns None (nothing sent) when the player does
        not follow. The caller decided it under CueHandler._lock and calls
        this in that same section."""
        with self._lock:
            if player is None or client is None or not player.may_follow:
                return None
            player.cancel_seq += 1
            rec = CancelRecord(
                seq=player.cancel_seq,
                cue_id=str(cue.id),
                pass_id=player.follow_pass,
                kind=kind,
                fade_ms=int(fade_ms),
                t_sent=monotonic(),
                client=client,
            )
            player.cancel_records[rec.seq] = rec
            player.may_follow = False
            player.fade_deadline = max(
                player.fade_deadline,
                rec.t_sent + fade_wait_ms(player, fade_ms) / 1000.0,
            )
            self._fading.add(player)
            self._open.add(player)
            self._checks = [c for c in self._checks if c.player is not player]
            try:
                client.set_value("/cancelstart", [rec.seq, rec.fade_ms])
            except Exception as e:
                # The record stays open: the watchdog re-sends it.
                Logger.warning(
                    f"Audio cue {cue.id}: /cancelstart {rec.seq} not sent: {e}"
                )
            self._ensure_watchdog()
        Logger.info(
            f"Audio cue {cue.id}: /cancelstart seq {rec.seq} ({kind}, "
            f"fade {rec.fade_ms} ms)"
        )
        return rec

    def close_records(self, player, why: str = "player released") -> int:
        """Close every open record of a player that is being disarmed,
        disconnected or killed (it can no longer answer), and clear its
        may_follow. Returns how many were open."""
        if not isinstance(player, Player):
            return 0
        with self._lock:
            n = len(player.cancel_records)
            if n:
                player.cancel_records.clear()
            self._open.discard(player)
            # Its own fade_deadline still holds its disconnect (fade_wait_s);
            # only STOP's pending_fade_wait_s reads this set, before any kill.
            self._fading.discard(player)
            player.may_follow = False
            self._checks = [c for c in self._checks if c.player is not player]
        if n:
            Logger.debug(f"Closed {n} open cancel record(s): {why}")
        return n

    def fade_wait_s(self, player) -> float:
        """Seconds a disconnect of this player must still wait for a fade."""
        if not isinstance(player, Player):
            return 0.0
        return max(0.0, player.fade_deadline - monotonic())

    def pending_fade_wait_s(self) -> float:
        """The longest fade still running on any player (STOP's wait)."""
        now = monotonic()
        with self._lock:
            waits = []
            for player in list(self._fading):
                left = (getattr(player, "fade_deadline", 0.0) or 0.0) - now
                if left > 0:
                    waits.append(left)
                else:
                    self._fading.discard(player)
        return max(waits, default=0.0)

    def expect_start(self, cue, player, client, now: float | None = None) -> None:
        """At the reveal of a follow-committed pass: a START line is due by
        start + one period + latency (§8). The watchdog re-sends
        ``/mtcfollow 1`` once if none came."""
        if player is None or client is None:
            return
        now = monotonic() if now is None else now
        deadline = (
            now
            + (_period_ms(player) + _latency_ms(player) + START_CHECK_SLACK_MS) / 1000.0
        )
        with self._lock:
            if player.follow_pass is None or player.starts_since_commit > 0:
                return
            self._checks.append(
                _StartCheck(player, client, str(cue.id), player.follow_pass, deadline)
            )
            self._ensure_watchdog()

    # ------------------------------------------------------------------
    # the stdout reader
    # ------------------------------------------------------------------
    def on_line(self, player, kind: str, parsed) -> None:
        """Player.selfgate_hook: a START, CANCEL or LATENCY line."""
        if kind == "cancel" and isinstance(parsed, CancelAck):
            self._on_cancel_ack(player, parsed)
        elif kind == "start" and isinstance(parsed, StartLine):
            self._on_start(player, parsed)
        elif kind == "latency" and isinstance(parsed, LatencyLine):
            listener = self._latency_listener
            if listener is not None:
                listener(player, parsed)

    def _on_cancel_ack(self, player, ack: CancelAck) -> None:
        with self._lock:
            rec = player.cancel_records.pop(ack.seq, None)
            if not player.cancel_records:
                self._open.discard(player)
        if rec is None:
            Logger.debug(
                f"[OK] CANCEL {ack.seq} {ack.state} with no open record (closed "
                "by a kill, a newer commit or an earlier ack)"
            )
            return
        if rec.resent:
            Logger.info(
                f"Audio cue {rec.cue_id}: /cancelstart seq {rec.seq} "
                f"acknowledged after its re-send ({ack.state})"
            )
        if rec.kind == "cancel" and ack.state == "play":
            Logger.warning(
                f"Audio cue {rec.cue_id} started {ack.ms} ms before its cancel; "
                "stopped (faded)"
            )

    def _on_start(self, player, start: StartLine) -> None:
        with self._lock:
            player.starts_since_commit += 1
            cue = player.follow_cue
            seeded = bool(getattr(cue, "_pass_seeded", False))
            cue_id = str(getattr(cue, "id", getattr(player, "uuid", "?")))
            first_seeded = False
            if seeded and start.target > LATE_START_TOLERANCE_SAMPLES:
                if cue_id not in self._seeded_warned:
                    self._seeded_warned.add(cue_id)
                    first_seeded = True
        if start.target <= LATE_START_TOLERANCE_SAMPLES:
            Logger.debug(
                f"Audio cue {cue_id} started on time (START target "
                f"{start.target} samples at {start.rate} Hz)"
            )
            return
        text = (
            f"cue {cue_id} on node {self.node_name} started "
            f"{start.late_ms:.1f} ms late (head lost: START target "
            f"{start.target} samples at {start.rate} Hz)"
        )
        if not seeded:
            Logger.warning(text)
            return
        Logger.info(f"{text}; a seeded start (go_at_end / ActionCue play)")
        if first_seeded:
            Logger.warning(
                f"cue {cue_id} on node {self.node_name}: its seeded starts "
                "(go_at_end / ActionCue play) begin late and lose their head "
                "(Phase B); further ones are logged at INFO until the next load"
            )

    # ------------------------------------------------------------------
    # the watchdog
    # ------------------------------------------------------------------
    def _ensure_watchdog(self) -> None:
        """Start the scan thread if it is not running. Call with the lock."""
        if not self.autostart:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = Thread(target=self._run, name="StartGateWatchdog", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            sleep(WATCHDOG_TICK_S)
            try:
                self.scan()
            except Exception as e:
                Logger.error(f"Start gate watchdog: {e}")
            with self._lock:
                if not self._open and not self._checks:
                    self._thread = None
                    return

    def scan(self, now: float | None = None) -> None:
        """One watchdog pass over the open records and the START checks."""
        now = monotonic() if now is None else now
        errors, warnings, infos = [], [], []
        with self._lock:
            for player in list(self._open):
                if not _alive(player):
                    player.cancel_records.clear()
                    self._open.discard(player)
                    continue
                for rec in list(player.cancel_records.values()):
                    if not rec.resent:
                        if now - rec.t_sent < ACK_TIMEOUT_S:
                            continue
                        if rec.pass_id != player.follow_pass:
                            del player.cancel_records[rec.seq]
                            infos.append(
                                f"Audio cue {rec.cue_id}: /cancelstart seq "
                                f"{rec.seq} not re-sent, a newer pass owns the "
                                "player"
                            )
                            continue
                        rec.resent = True
                        rec.t_resent = now
                        try:
                            rec.client.set_value("/cancelstart", [rec.seq, rec.fade_ms])
                        except Exception as e:
                            infos.append(f"re-send failed: {e}")
                        warnings.append(
                            f"Audio cue {rec.cue_id}: no ack of /cancelstart "
                            f"seq {rec.seq} in {ACK_TIMEOUT_S * 1000:.0f} ms; "
                            "re-sent"
                        )
                    elif now - rec.t_resent >= ACK_TIMEOUT_S:
                        del player.cancel_records[rec.seq]
                        errors.append(
                            f"Audio cue {rec.cue_id}: /cancelstart seq {rec.seq} "
                            f"({rec.kind}) not acknowledged after its re-send; "
                            "the player may still be following"
                        )
                if not player.cancel_records:
                    self._open.discard(player)
            keep = []
            for check in self._checks:
                if now < check.deadline:
                    keep.append(check)
                    continue
                player = check.player
                if (
                    player.follow_pass != check.pass_id
                    or player.starts_since_commit > 0
                    or not player.may_follow
                    or not _alive(player)
                ):
                    continue
                try:
                    check.client.set_value("/mtcfollow", 1)
                except Exception as e:
                    infos.append(f"/mtcfollow re-send failed: {e}")
                warnings.append(
                    f"Audio cue {check.cue_id}: no START line by its start + "
                    "period + latency (a lost /mtcfollow 1?); re-sent "
                    "/mtcfollow 1, the start will be late"
                )
            self._checks = keep
        for text in errors:
            Logger.error(text)
        for text in warnings:
            Logger.warning(text)
        for text in infos:
            Logger.info(text)


def player_selfgate(player) -> bool:
    return loop_mode.player_selfgate(player)


START_GATE = StartGate()
Player.selfgate_hook = START_GATE.on_line
