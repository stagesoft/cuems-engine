#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""
Mock cuems-dmxplayer replacement for headless/cloud deployments.

Accepts the same CLI as cuems-dmxplayer, starts an OSC UDP server on the
assigned port, logs all received DMX commands, and stays alive until /quit or
SIGTERM.
"""

import argparse
import signal
import sys
import threading

from cuemsutils.log import Logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer


def main():
    parser = argparse.ArgumentParser(
        description="Mock cuems-dmxplayer for headless deployments"
    )
    parser.add_argument("--port", type=int, required=True, help="OSC UDP port")
    parser.add_argument("--uuid", type=str, required=True, help="Player node UUID")
    args, _ = parser.parse_known_args()

    Logger.info(f"[mock-dmxplayer] starting -- port={args.port} uuid={args.uuid}")

    dispatcher = Dispatcher()
    server_ref = []

    def log_handler(address, *osc_args):
        Logger.info(f"[mock-dmxplayer] OSC {address} {list(osc_args)}")

    def quit_handler(address, *osc_args):
        Logger.info(f"[mock-dmxplayer] OSC {address} -- shutting down")
        if server_ref:
            threading.Thread(target=server_ref[0].shutdown, daemon=True).start()

    dispatcher.map("/quit", quit_handler)
    for endpoint in (
        "/frame",
        "/mtc_time",
        "/start_offset",
        "/fade_time",
        "/check",
        "/stoponlost",
        "/mtcfollow",
    ):
        dispatcher.map(endpoint, log_handler)
    dispatcher.set_default_handler(
        lambda address, *a: Logger.info(f"[mock-dmxplayer] OSC {address} {list(a)}")
    )

    server = BlockingOSCUDPServer(("0.0.0.0", args.port), dispatcher)
    server_ref.append(server)

    def handle_signal(signum, frame):
        Logger.info(f"[mock-dmxplayer] signal {signum}, shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    Logger.info(f"[mock-dmxplayer] listening on port {args.port}")
    server.serve_forever()
    Logger.info("[mock-dmxplayer] stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
