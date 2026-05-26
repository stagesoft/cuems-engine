# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

#!/usr/bin/env python3
"""
Mock jack-volume replacement for headless/cloud deployments.

Accepts the same CLI as jack-volume, starts an OSC UDP server on the
assigned port, logs all received volume commands, and stays alive until SIGTERM.
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
        description="Mock jack-volume for headless deployments"
    )
    parser.add_argument(
        "-c", dest="client_name", default="mock_mixer", help="JACK client name"
    )
    parser.add_argument("-p", dest="port", type=int, required=True, help="OSC UDP port")
    parser.add_argument(
        "-n", dest="channels", type=int, default=2, help="Number of channels"
    )
    parser.add_argument(
        "-s", dest="server", default=None, help="JACK server name (ignored)"
    )
    args, _ = parser.parse_known_args()

    Logger.info(
        f"[mock-jack-volume] starting -- client={args.client_name} "
        f"port={args.port} channels={args.channels}"
    )

    dispatcher = Dispatcher()
    server_ref = []

    def volume_handler(address, *osc_args):
        Logger.info(f"[mock-jack-volume] OSC {address} {list(osc_args)}")

    def quit_handler(address, *osc_args):
        Logger.info(f"[mock-jack-volume] OSC {address} -- shutting down")
        if server_ref:
            threading.Thread(target=server_ref[0].shutdown, daemon=True).start()

    # Register dynamic volume paths based on client name and channel count
    base = f"/audiomixer/{args.client_name}"
    dispatcher.map(f"{base}/master", volume_handler)
    for i in range(args.channels):
        dispatcher.map(f"{base}/{i}", volume_handler)
    dispatcher.map("/quit", quit_handler)
    dispatcher.set_default_handler(
        lambda address, *a: Logger.info(f"[mock-jack-volume] OSC {address} {list(a)}")
    )

    server = BlockingOSCUDPServer(("0.0.0.0", args.port), dispatcher)
    server_ref.append(server)

    def handle_signal(signum, frame):
        Logger.info(f"[mock-jack-volume] signal {signum}, shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    Logger.info(f"[mock-jack-volume] listening on port {args.port}")
    server.serve_forever()
    Logger.info("[mock-jack-volume] stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
