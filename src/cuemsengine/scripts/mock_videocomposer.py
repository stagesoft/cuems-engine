#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

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
import os
import signal
import sys
import threading

from cuemsutils.log import Logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

# The capability file the node engine reads at every load (869ejxng3 §4.2):
# the mock speaks the same protocol as the real videocomposer, so it says so.
# Its unit has no RuntimeDirectory: it creates /run/cuems itself, removes a
# leftover at start and its own file at exit (I16j).
CAPS_PATH = os.environ.get("CUEMS_VC_CAPS_FILE", "/run/cuems/videocomposer.caps")
CAPS_TOKENS = ("loop_period",)


def write_caps(path: str = CAPS_PATH) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            f.write(f"pid={os.getpid()}\n")
            for token in CAPS_TOKENS:
                f.write(f"{token}\n")
        os.replace(tmp, path)
        return True
    except OSError as e:
        Logger.warning(f"[mock-videocomposer] caps file {path} not written: {e}")
        return False


def remove_caps(path: str = CAPS_PATH) -> None:
    try:
        with open(path) as f:
            first = f.readline().strip()
        if first == f"pid={os.getpid()}":
            os.unlink(path)
    except OSError:
        pass


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
        "--host",
        type=str,
        default="0.0.0.0",
        help="Bind host (default: 0.0.0.0)",
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
    write_caps()
    try:
        server.serve_forever()
    finally:
        remove_caps()
    Logger.info("[mock-videocomposer] stopped")
    sys.exit(0)


if __name__ == "__main__":
    main()
