# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import signal
import socket
from contextlib import contextmanager


def free_tcp_port() -> int:
    """Return a TCP port the kernel currently considers free.

    Deliberately does NOT go through PORT_HANDLER: that only tracks ports this
    process handed out, so it happily returns a port a *live* service already
    holds — its range even starts at INITIAL_PORT 9190, the controller's
    WebSocket OSC port. Asking the kernel for port 0 and reading back what it
    assigned is the only check that accounts for the rest of the machine.

    Returns:
        int: A port that was free at the moment of the call.

    Note:
        Inherently advisory — the port is released before the caller binds it.
        Good enough for tests, where the alternative is a hardcoded port that
        collides deterministically.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def timeout(seconds):
    """Timeout context manager

    Args:
        seconds: The number of seconds to timeout

    Raises:
        TimeoutError: If the timeout is reached

    Example:
    >>> with timeout(10):
    ...     time.sleep(15)
    ...
    TimeoutError: Timeout after 10 seconds
    """

    def timeout_handler(signum, frame):
        raise TimeoutError(f"Timeout after {seconds} seconds")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
