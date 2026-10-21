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


@dataclass(frozen=True)
class LoopAck:
    """The latest LOOP line of a player (§4.2)."""

    ver: int
    passes: int
    num: int
    den: int
    mode: str


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

    def note_line(self, line: bytes) -> None:
        """Record a CAPS or LOOP line (the stdout reader; also used by tests)."""
        if CAPS_TAG in line:
            self.caps = parse_caps(line)
            Logger.info(f"Player capabilities: {sorted(self.caps)}")
            return
        ack = parse_loop_ack(line)
        if ack is None:
            return
        if ack.mode == "wrap":
            self.last_wrap_ver = max(self.last_wrap_ver, ack.ver)
        current = self.loop_ack
        if current is None or ack.ver >= current.ver:
            self.loop_ack = ack  # one reference assignment: readers see old or new

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
