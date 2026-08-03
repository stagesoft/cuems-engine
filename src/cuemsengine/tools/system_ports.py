# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

import subprocess

from cuemsutils.log import Logger


def get_used_ports() -> set[int]:
    """
    Recover every local port currently bound on this host, TCP and UDP.

    Uses `ss -tuln` — deliberately *without* `-p`. The owning PID is of no use
    to the port allocator, and asking for it is actively harmful: `ss` hides
    the whole `users:(...)` field for sockets owned by another user, and the
    previous implementation only recorded a port when it could also read a
    `pid=` out of that field. As a non-owner it therefore returned nothing at
    all rather than a partial list, leaving the allocator blind to every
    socket it did not own (869ed9wf7).

    Returns:
        set[int]: Local ports currently bound. Empty if `ss` is unavailable —
        that degrades the allocator to its previous behaviour rather than
        taking the engine down.
    """
    try:
        result = subprocess.run(
            ["ss", "-tuln"], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        Logger.warning(f"Could not list system ports with 'ss': {e}")
        return set()

    ports = set()
    for line in result.stdout.splitlines():
        # Netid State Recv-Q Send-Q <Local Address:Port> <Peer Address:Port>
        parts = line.split()
        if len(parts) < 5 or parts[0] == "Netid":
            continue
        # rpartition handles both "0.0.0.0:5353" and "[::]:22"; the wildcard
        # "*:*" and any other non-numeric tail fall through the isdigit test.
        port = parts[4].rpartition(":")[2]
        if port.isdigit():
            ports.add(int(port))
    return ports


def is_port_in_use(port: int) -> bool:
    """
    Check if a specific port is currently bound on this host.

    Args:
        port (int): The port number to check

    Returns:
        bool: True if port is in use, False otherwise

    Example:
        >>> if is_port_in_use(8080):
        ...     print("Port 8080 is in use")
    """
    return port in get_used_ports()
