# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

#!/usr/bin/env python3
"""
Mock videocomposer replacement for headless/cloud deployments.

Standalone OSC UDP service (NOT launched by the engine -- run it as a systemd
service or manually before starting the engine). Listens on the configured
videocomposer OSC port (default 7000), logs all /videocomposer/* commands,
and stays alive until /videocomposer/quit or SIGTERM.

Usage:
    mock-videocomposer [--port PORT] [--host HOST]

Systemd example:
    [Service]
    Type=simple
    ExecStart=/usr/lib/cuems/bin/mock-videocomposer --port 7000
    Restart=always
"""

import argparse
import signal
import sys
import threading

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from cuemsutils.log import Logger


def main():
    parser = argparse.ArgumentParser(
        description="Mock videocomposer for headless deployments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Runs as a standalone service (NOT launched by the engine).
Start before the engine so OSC packets are received.
        """,
    )
    parser.add_argument(
        "--port", type=int, default=7000, help="OSC UDP port (default: 7000)"
    )
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Bind host (default: 0.0.0.0)"
    )
    args = parser.parse_args()

    Logger.info(f"[mock-videocomposer] starting -- host={args.host} port={args.port}")

    dispatcher = Dispatcher()
    server_ref = []

    def log_handler(address, *osc_args):
        Logger.info(f"[mock-videocomposer] OSC {address} {list(osc_args)}")

    def quit_handler(address, *osc_args):
        Logger.info(f"[mock-videocomposer] OSC {address} -- shutting down")
        if server_ref:
            threading.Thread(target=server_ref[0].shutdown, daemon=True).start()

    # Top-level videocomposer commands
    dispatcher.map("/videocomposer/quit", quit_handler)
    dispatcher.map("/videocomposer/check", log_handler)

    # Display commands
    for endpoint in (
        "/videocomposer/display/list",
        "/videocomposer/display/modes",
        "/videocomposer/display/resolution_mode",
        "/videocomposer/display/mode",
        "/videocomposer/display/region",
        "/videocomposer/display/blend",
        "/videocomposer/display/warp",
        "/videocomposer/display/save",
        "/videocomposer/display/load",
    ):
        dispatcher.map(endpoint, log_handler)

    # Layer commands (static known paths)
    for endpoint in (
        "/videocomposer/layer/load",
        "/videocomposer/layer/unload",
    ):
        dispatcher.map(endpoint, log_handler)

    # Output capture
    dispatcher.map("/videocomposer/output/capture", log_handler)

    # Catch-all for dynamic per-layer endpoints (/videocomposer/layer/<id>/*)
    dispatcher.set_default_handler(
        lambda address, *a: Logger.info(f"[mock-videocomposer] OSC {address} {list(a)}")
    )

    server = BlockingOSCUDPServer((args.host, args.port), dispatcher)
    server_ref.append(server)

    def handle_signal(signum, frame):
        Logger.info(f"[mock-videocomposer] signal {signum}, shutting down")
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    Logger.info(f"[mock-videocomposer] listening on {args.host}:{args.port}")
    server.serve_forever()
    Logger.info("[mock-videocomposer] stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
