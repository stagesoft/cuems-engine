# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""
JACK presence and start-up handshake shared by the mock players.

The engine treats an audio player as started when it prints READY_LINE on
stdout (players/Player.py), then routes its JACK ports into the mixer. A mock
that does neither makes every audio arm wait the full RUNNING timeout and log
the cue as SILENT. Registering the same client and port names as the real
binaries lets the engine wire them exactly as on a real node: on a mock box
jackd runs with the dummy driver (jackd-dummy.service), so nothing is heard.
"""

from cuemsutils.log import Logger

# Must match players/Player.py READY_LINE.
READY_LINE = "[OK] RUNNING!"


def open_jack_client(client_name: str, inputs=(), outputs=()):
    """Open a JACK client with the given port names and activate it.

    Returns the client, or None when there is no JACK server (or no `jack`
    module): the mock then keeps working as a log-only OSC endpoint, and the
    engine reports the missing JACK server itself. Keep the returned client
    referenced for the life of the process; its ports go away with it.
    """
    try:
        import jack

        client = jack.Client(client_name, no_start_server=True)
        for name in inputs:
            client.inports.register(name)
        for name in outputs:
            client.outports.register(name)
        client.activate()
    except Exception as e:
        Logger.warning(f"[mock] JACK client {client_name!r} not opened: {e!r}")
        return None
    Logger.info(
        f"[mock] JACK client {client.name!r} registered "
        f"{len(inputs)} input(s) and {len(outputs)} output(s)"
    )
    return client


def report_ready():
    """Print the line the engine waits for before wiring a player's ports."""
    print(READY_LINE, flush=True)
