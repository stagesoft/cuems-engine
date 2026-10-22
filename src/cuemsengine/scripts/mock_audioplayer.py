#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""
Mock cuems-audioplayer replacement for headless/cloud deployments.

Accepts the same CLI as cuems-audioplayer, starts an OSC UDP server on the
assigned port, logs all received commands, and stays alive until /quit or
SIGTERM. Like the real player it opens the JACK client Audio_Player-<uuid>
with ports "outport 0" and "outport 1" and prints "[OK] RUNNING!", so the
engine wires it into the mixer instead of timing out (see mock_jack).
"""

import argparse
import signal
import sys
import threading

from cuemsutils.log import Logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from cuemsengine.scripts.mock_jack import open_jack_client, report_ready


def _make_handler(name: str):
    def handler(address, *args):
        Logger.info(f"[mock-audioplayer] OSC {address} {list(args)}")

    handler.__name__ = name
    return handler


def _quit_handler(server_ref: list, address, *args):
    Logger.info(f"[mock-audioplayer] OSC {address} -- shutting down")
    if server_ref:
        threading.Thread(target=server_ref[0].shutdown, daemon=True).start()


def main():
    parser = argparse.ArgumentParser(
        description="Mock cuems-audioplayer for headless deployments"
    )
    parser.add_argument("--port", type=int, required=True, help="OSC UDP port")
    parser.add_argument("--uuid", type=str, default=None, help="Player UUID")
    parser.add_argument("media", nargs="?", default=None, help="Media file path")
    args, _ = parser.parse_known_args()

    Logger.info(
        f"[mock-audioplayer] starting -- port={args.port} uuid={args.uuid}"
        f"media={args.media}"
    )

    dispatcher = Dispatcher()
    server_ref = []

    dispatcher.map("/quit", lambda address, *a: _quit_handler(server_ref, address, *a))
    for endpoint in (
        "/load",
        "/play",
        "/stop",
        "/vol0",
        "/vol1",
        "/volmaster",
        "/mtcfollow",
        "/offset",
        "/check",
        "/stoponlost",
    ):
        dispatcher.map(endpoint, _make_handler(endpoint))
    dispatcher.set_default_handler(
        lambda address, *a: Logger.info(f"[mock-audioplayer] OSC {address} {list(a)}")
    )

    server = BlockingOSCUDPServer(("0.0.0.0", args.port), dispatcher)
    server_ref.append(server)

    # Same client and port names as cuems-audioplayer (main.cpp, RtAudio).
    client_name = f"Audio_Player-{args.uuid}" if args.uuid else "Audio_Player"
    jack_client = open_jack_client(  # noqa: F841 -- keeps the ports alive
        client_name, outputs=("outport 0", "outport 1")
    )

    def handle_signal(signum, frame):
        Logger.info(f"[mock-audioplayer] signal {signum}, shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    Logger.info(f"[mock-audioplayer] listening on port {args.port}")
    report_ready()
    server.serve_forever()
    Logger.info("[mock-audioplayer] stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
