# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import signal
import socket
from contextlib import contextmanager


def _free_port(sock_type: int) -> int:
    """Bind port 0 and read back what the kernel assigned."""
    with socket.socket(socket.AF_INET, sock_type) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_tcp_port() -> int:
    """Return a TCP port the kernel currently considers free.

    Deliberately does NOT go through PORT_HANDLER — see free_udp_port().

    Returns:
        int: A port that was free at the moment of the call.
    """
    return _free_port(socket.SOCK_STREAM)


def free_udp_port() -> int:
    """Return a UDP port the kernel currently considers free.

    PORT_HANDLER cannot be trusted for this in tests. It only excludes ports
    *this process* handed out, and the one mechanism that would widen that —
    `add_system_ports()`, which production's NodeEngine does call at startup —
    parses `ss -tulnp` and only records a port when it can also read a `pid=`.
    `ss` hides that field for sockets owned by another user, so as the test
    user it returns nothing at all and the allocator stays blind.

    On a host running CUEMS the live engines hold OSC ports drawn from the very
    same 9190-9999 range, so PORT_HANDLER hands out ports that are already
    bound and the OSC device fails with "Network error" — intermittently, in
    proportion to how many ports a test allocates.

    Returns:
        int: A port that was free at the moment of the call.

    Note:
        Inherently advisory — the port is released before the caller binds it.
        Good enough for tests, where the alternative is an allocator that
        cannot see the rest of the machine at all.
    """
    return _free_port(socket.SOCK_DGRAM)


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
