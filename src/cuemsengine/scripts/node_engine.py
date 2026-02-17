#!/usr/bin/env python3
"""
CLI entry point for cuems-engine NodeEngine.

Runs in foreground mode, designed for systemd services (Type=simple).
Systemd handles process supervision, logging (journald), and restart.

Example systemd service:
    [Service]
    Type=simple
    ExecStart=/usr/lib/cuems/bin/node-engine
    Restart=always
"""

import signal
import argparse

from cuemsutils.log import Logger
from cuemsengine.NodeEngine import NodeEngine


def main():
    """Main entry point - run NodeEngine in foreground"""
    parser = argparse.ArgumentParser(
        description='CUEMS Node Engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Runs in foreground mode. Designed for systemd services (Type=simple).
Use Ctrl+C to stop when running manually.
        """
    )
    parser.parse_args()
    
    Logger.info("Starting CUEMS Node Engine")
    
    engine = NodeEngine()
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


if __name__ == '__main__':
    main()
