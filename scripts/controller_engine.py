#!/usr/bin/env python3
"""
CLI entry point for cuems-engine ControllerEngine

Supports two modes:
1. Manual/Development mode: Runs in foreground (default)
2. Daemon mode: Runs as system daemon (--daemon flag)
"""

import signal
import argparse

from cuemsutils.log import Logger
from cuemsengine.ControllerEngine import ControllerEngine
from cuemsutils.daemon import run_daemon


def run_manual():
    """Run controller engine in manual/development mode (foreground)"""
    Logger.info("Starting CUEMS Controller Engine in MANUAL mode (foreground)")
    
    # Create and start engine
    engine = ControllerEngine()
    engine.start()
    
    try:
        # Keep the process alive
        signal.pause()
    except KeyboardInterrupt:
        Logger.info("Received interrupt signal, stopping engine...")
        engine.stop_all()
    except Exception as e:
        Logger.error(f"Engine error: {type(e).__name__}: {e}")
        engine.stop_all()
        raise


def run_daemon_mode():
    """Run controller engine in daemon mode (for systemd)"""
    Logger.info("Starting CUEMS Controller Engine in DAEMON mode")
    
    # Create engine and run as daemon
    engine = ControllerEngine()
    run_daemon(engine, 'controller_engine')


def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description='CUEMS Controller Engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in manual/development mode (foreground)
  %(prog)s
  
  # Run as daemon (for systemd service)
  %(prog)s --daemon
        """
    )
    
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run as daemon (for systemd service). Default: run in foreground'
    )
    
    args = parser.parse_args()
    
    if args.daemon:
        # Daemon mode - for systemd
        run_daemon_mode()
    else:
        # Manual mode - for development/testing
        run_manual()


if __name__ == '__main__':
    main()
