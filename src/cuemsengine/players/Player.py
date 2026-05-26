# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import os
from subprocess import PIPE, STDOUT, CalledProcessError, Popen
from threading import Thread
from time import sleep

from cuemsutils.log import Logger, logged


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

    def run(self):
        raise NotImplementedError

    @logged
    def call_subprocess(self, call_args):
        """Calls a subprocess with the given arguments.

        Automatically handles exceptions and updates status/error attributes.
        Sets status to 'running' on success, 'failed' on error.
        """
        try:
            my_env = os.environ.copy()
            my_env["DISPLAY"] = ":0"
            self.p = Popen(call_args, stdout=PIPE, stderr=STDOUT, env=my_env)
            self.pid = self.p.pid

            stdout_lines_iterator = iter(self.p.stdout.readline, b"")
            while self.p.poll() is None:
                for line in stdout_lines_iterator:
                    Logger.debug(f"Subprocess output: {line}")
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
        from time import sleep

        elapsed = 0.0
        interval = 0.01
        while self.pid is None and elapsed < timeout:
            # Check if the thread is still alive
            if not self.is_alive():
                error_msg = f"Player thread died during startup"
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
