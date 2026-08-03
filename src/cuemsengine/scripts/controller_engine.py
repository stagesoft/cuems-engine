#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""
CLI entry point for cuems-engine ControllerEngine.

Runs in foreground mode, designed for systemd services (Type=simple).
Systemd handles process supervision, logging (journald), and restart.

Example systemd service:
    [Service]
    Type=simple
    ExecStart=/usr/lib/cuems/bin/controller-engine
    Restart=always
"""

import argparse
import signal

from cuemsutils.log import Logger

from cuemsengine.ControllerEngine import ControllerEngine


def main():
    """Main entry point - run ControllerEngine in foreground"""
    parser = argparse.ArgumentParser(
        description="CUEMS Controller Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Runs in foreground mode. Designed for systemd services (Type=simple).
Use Ctrl+C to stop when running manually.
        """,
    )
    parser.parse_args()

    Logger.info("Starting CUEMS Controller Engine")

    engine = ControllerEngine()
    engine.start()

    def handle_signal(signum, frame):
        Logger.info(f"Received signal {signum}, stopping engine...")
        engine.stop_all()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        signal.pause()
    except KeyboardInterrupt:
        Logger.info("Received interrupt signal, stopping engine...")
        engine.stop_all()
    except SystemExit:
        pass
    except Exception as e:
        Logger.error(f"Engine error: {type(e).__name__}: {e}")
        engine.stop_all()
        raise


if __name__ == "__main__":
    main()
