# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

import os
from dataclasses import dataclass
from subprocess import PIPE, STDOUT, Popen
from threading import Event, Thread
from time import sleep

from cuemsutils.log import Logger, logged

# The line a CUEMS player prints on stdout once it is fully started (the
# cuems-audioplayer calls its SIGUSR1 handler from main() right after the
# AudioPlayer object is built and its stream runs: "to let everyone know that
# we are running"). Matched as a substring: the line starts with the player's
# logger slug, e.g. b"[Cuems:d<uuid>] [OK] RUNNING!\n".
READY_LINE = b"[OK] RUNNING!"

# 869ejxng3 + 1amfwm7e6cw (plan §4.2). A capable cuems-audioplayer prints, each
# line in one write(2):
#   b"[<slug>] [OK] CAPS: loop varispeed\n"            before RUNNING
#   b"[<slug>] [OK] LOOP <ver> <passes> <num> <den> <mode>\n"
# on every /loop it receives (the receipt, carrying the PREVIOUS mode) and
# whenever its effective mode changes; mode is pending | once | wrap | off and
# ver counts the mode changes. The line with the highest ver wins.
CAPS_TAG = b"[OK] CAPS:"
LOOP_TAG = b"[OK] LOOP "
LOOP_MODES = ("pending", "once", "wrap", "off")

# 869feynrj (cuems-RELATIONS Plans/2026-11-03-audio-first-pass-head-869feynrj.md
# §4.1d-g), CAPS ``selfgate`` only, each line in one write:
#   b"[<slug>] [OK] START <start_ms_mod_day> <target_samples> <file_rate>[ snap]\n"
# at the first start since each /mtcfollow 1 received in HOLD (target <= 0:
# on time, sample 0 at its frame; > 0: that many file samples late, the head
# lost, or kept when the player snapped a start <= 2 ms past sample 0 to
# sample 0: the trailing "snap", 869feynrj step 5);
#   b"[<slug>] [OK] CANCEL <seq> <hold|play|pastend> <ms_of_output>\n"
# the ack of every /cancelstart, echoing its seq;
#   b"[<slug>] [OK] LATENCY <frames> <rate> <period_frames>[ override]\n"
# before RUNNING and again on a latency change: the output latency the
# player compensates in its start target.
START_TAG = b"[OK] START "
CANCEL_TAG = b"[OK] CANCEL "
LATENCY_TAG = b"[OK] LATENCY "
CANCEL_STATES = ("hold", "play", "pastend")


@dataclass(frozen=True)
class LoopAck:
    """The latest LOOP line of a player (§4.2)."""

    ver: int
    passes: int
    num: int
    den: int
    mode: str


@dataclass(frozen=True)
class StartLine:
    """A START line (§4.1e): the player's first start since a follow."""

    start_ms: int  # the cue start, MTC ms modulo 24 h
    target: int  # signed file samples: <= 0 on time, > 0 late
    rate: int  # the file's sample rate
    snap: bool = False  # late but snapped to sample 0: the head kept

    @property
    def late_ms(self) -> float:
        """How late the start is, in ms (0 when on time)."""
        if self.target <= 0 or self.rate <= 0:
            return 0.0
        return self.target * 1000.0 / self.rate


@dataclass(frozen=True)
class CancelAck:
    """A CANCEL line (§4.1d): the ack of one /cancelstart."""

    seq: int
    state: str  # hold | play | pastend
    ms: int  # ms of content output since the start (0 for hold)


@dataclass(frozen=True)
class LatencyLine:
    """A LATENCY line (§4.1g): the output latency the player compensates."""

    frames: int
    rate: int
    period: int
    override: bool = False

    @property
    def out_latency_ms(self) -> float:
        """Latency + one JACK period, in ms (§4.5d, review 4 m1)."""
        if self.rate <= 0:
            return 0.0
        return (self.frames + self.period) * 1000.0 / self.rate

    @property
    def period_ms(self) -> float:
        return self.period * 1000.0 / self.rate if self.rate > 0 else 0.0


def _fields(line: bytes, tag: bytes) -> list | None:
    i = line.find(tag)
    if i < 0:
        return None
    return line[i + len(tag) :].decode("utf8", "replace").split()


def parse_start(line: bytes) -> StartLine | None:
    """A START line, or None when it is not one (or malformed)."""
    parts = _fields(line, START_TAG)
    if parts is None or len(parts) < 3:
        return None
    try:
        snap = len(parts) >= 4 and parts[3] == "snap"
        return StartLine(int(parts[0]), int(parts[1]), int(parts[2]), snap)
    except ValueError:
        return None


def parse_cancel(line: bytes) -> CancelAck | None:
    """A CANCEL line, or None when it is not one (or malformed)."""
    parts = _fields(line, CANCEL_TAG)
    if parts is None or len(parts) < 3 or parts[1] not in CANCEL_STATES:
        return None
    try:
        return CancelAck(int(parts[0]), parts[1], int(parts[2]))
    except ValueError:
        return None


def parse_latency(line: bytes) -> LatencyLine | None:
    """A LATENCY line, or None when it is not one (or malformed)."""
    parts = _fields(line, LATENCY_TAG)
    if parts is None or len(parts) < 3:
        return None
    try:
        frames, rate, period = (int(x) for x in parts[:3])
    except ValueError:
        return None
    if rate <= 0:
        return None
    return LatencyLine(frames, rate, period, "override" in parts[3:])


def parse_caps(line: bytes) -> frozenset:
    """The tokens of a CAPS line, or an empty set."""
    i = line.find(CAPS_TAG)
    if i < 0:
        return frozenset()
    return frozenset(line[i + len(CAPS_TAG) :].decode("utf8", "replace").split())


def parse_loop_ack(line: bytes) -> LoopAck | None:
    """A LOOP line as a LoopAck, or None when it is not one (or malformed)."""
    i = line.find(LOOP_TAG)
    if i < 0:
        return None
    parts = line[i + len(LOOP_TAG) :].decode("utf8", "replace").split()
    if len(parts) < 5 or parts[4] not in LOOP_MODES:
        return None
    try:
        ver, passes, num, den = (int(x) for x in parts[:4])
    except ValueError:
        return None
    return LoopAck(ver, passes, num, den, parts[4])


class Player(Thread):
    """Base class for all players in the system.
    Holds the common methods and attributes for all players.
    Extends the Thread class.
    Can call a subprocess, kill it and start the Thread.

    IMPORTANT: The run method must be implemented in the child classes.

    """

    # 869feynrj: called by the stdout reader with (player, kind, parsed) for
    # every START / CANCEL / LATENCY line; kind is "start", "cancel" or
    # "latency". Set by players.StartGate at import (the engine's cancel
    # records and late-start rules live there). Never raises into the reader.
    selfgate_hook = None

    def __init__(self, daemon: bool = True):
        """
        Initializes the Player object and a Thread object with the daemon
        attribute set to True.

        Args:
            daemon (bool, optional): Sets the daemon attribute of the Thread
            object. Defaults to True.
        """
        super().__init__(daemon=daemon)
        self.p = None
        self.pid = None
        self.firstrun = True
        self.started = False
        self.status = "starting"  # 'starting', 'running', 'failed'
        self.error = None
        # Set when the subprocess prints READY_LINE. An audio arm waits on it
        # before wiring the player to the mixer: the player's JACK ports exist
        # before it has finished starting, and wiring them that early leaves
        # RtAudio's own auto-connect to system:playback in place (869fbyjzx).
        # Known limit: waiting for it makes an audio arm ~0.47 s cold, so a GO
        # that comes sooner after the arm began is still late. Plan B (arm
        # before the hand-off) is described in AudioMixer.connect_player_to_
        # outputs and the 869fbyjzx plan; it is not built.
        self.ready = Event()
        # What the subprocess announced on stdout (§4.2), reset per run.
        self.caps = frozenset()
        self.loop_ack = None  # LoopAck: the line with the highest ver
        self.last_wrap_ver = (
            -1
        )  # ver of the latest "wrap" line (an "off" counts only above it)
        self.reset_selfgate_state()

    def reset_selfgate_state(self) -> None:
        """The 869feynrj per-player state (§4.2, §4.3), reset per run.

        Lives on the PLAYER, not on the cue (review #10): a player still
        following from an earlier pass self-starts on a new start whatever
        the new pass does. Guarded by players.StartGate's lock."""
        # Set on every /mtcfollow 1 sent, cleared on /mtcfollow 0, on
        # /cancelstart and when the player is killed.
        self.may_follow = False
        # The pass the last follow commit belongs to: (cue id, go generation).
        self.follow_pass = None
        self.follow_cue = None
        self.starts_since_commit = 0
        # /cancelstart sequence (per player) and the open cancel records.
        self.cancel_seq = 0
        self.cancel_records = {}
        # Monotonic time before which a disconnect must not cut the player:
        # transit + one period + fade_ms + margin after the last /cancelstart
        # (D12, review 4 m4).
        self.fade_deadline = 0.0
        self.last_start = None  # StartLine
        self.latency = None  # LatencyLine

    def note_line(self, line: bytes) -> None:
        """Record a CAPS, LOOP, START, CANCEL or LATENCY line (the stdout
        reader; also used by tests)."""
        if CAPS_TAG in line:
            self.caps = parse_caps(line)
            Logger.info(f"Player capabilities: {sorted(self.caps)}")
            return
        for kind, parse in (
            ("start", parse_start),
            ("cancel", parse_cancel),
            ("latency", parse_latency),
        ):
            parsed = parse(line)
            if parsed is not None:
                self._selfgate_line(kind, parsed)
                return
        ack = parse_loop_ack(line)
        if ack is None:
            return
        if ack.mode == "wrap":
            self.last_wrap_ver = max(self.last_wrap_ver, ack.ver)
        current = self.loop_ack
        if current is None or ack.ver >= current.ver:
            self.loop_ack = ack  # one reference assignment: readers see old or new

    def _selfgate_line(self, kind: str, parsed) -> None:
        if kind == "start":
            self.last_start = parsed
        elif kind == "latency":
            self.latency = parsed
        hook = Player.selfgate_hook
        if hook is None:
            return
        try:
            hook(self, kind, parsed)
        except Exception as e:
            Logger.error(f"Player {kind} line could not be handled: {e}")

    def run(self):
        raise NotImplementedError

    @logged
    def call_subprocess(self, call_args):
        """Calls a subprocess with the given arguments.

        Automatically handles exceptions and updates status/error attributes.
        Sets status to 'running' on success, 'failed' on error.
        """
        try:
            # This run starts not ready: an Event left set by an earlier run of
            # the same Player object would pass the audio wiring's gate at once.
            self.ready.clear()
            self.caps = frozenset()
            self.loop_ack = None
            self.last_wrap_ver = -1
            self.reset_selfgate_state()
            my_env = os.environ.copy()
            my_env["DISPLAY"] = ":0"
            self.p = Popen(call_args, stdout=PIPE, stderr=STDOUT, env=my_env)
            self.pid = self.p.pid

            stdout_lines_iterator = iter(self.p.stdout.readline, b"")
            while self.p.poll() is None:
                for line in stdout_lines_iterator:
                    Logger.debug(f"Subprocess output: {line}")
                    if READY_LINE in line:
                        self.ready.set()
                    elif b"[OK] " in line:
                        self.note_line(line)
                # Prevent CPU spinning when subprocess has no output
                sleep(0.01)

            self.status = "running"
        except Exception as e:
            self.status = "failed"
            self.error = e
            Logger.error(f"Failed to start player subprocess: {e}")
            Logger.exception(e)
            raise

    @logged
    def kill(self):
        """Kills the subprocess."""
        if self.p:
            self.p.kill()
            self.started = False

    @logged
    def start(self, timeout: float = 5.0):
        """Starts the player and waits for it to initialize.

        Args:
            timeout: Maximum time to wait for player to start (seconds)

        Raises:
            RuntimeError: If player fails to start within timeout or thread
            dies
        """
        # Start the thread
        if self.firstrun:
            super().start()
            self.firstrun = False
        elif not self.is_alive():
            super().start()
        self.started = True

        # Wait for player process to start with timeout
        elapsed = 0.0
        interval = 0.01
        while self.pid is None and elapsed < timeout:
            # Check if the thread is still alive
            if not self.is_alive():
                error_msg = "Player thread died during startup"
                if self.error:
                    error_msg += f": {self.error}"
                Logger.error(error_msg)
                raise RuntimeError(error_msg)

            # Check if player failed
            if self.status == "failed":
                error_msg = f"Player failed to start: {self.error}"
                Logger.error(error_msg)
                raise RuntimeError(error_msg)

            sleep(interval)
            elapsed += interval

        # Timeout check
        if self.pid is None:
            error_msg = f"Player failed to start within {timeout}s timeout"
            Logger.error(error_msg)
            self.kill()
            raise RuntimeError(error_msg)
