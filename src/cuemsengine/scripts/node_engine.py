#!/usr/bin/env python3
"""
CLI entry point for cuems-engine NodeEngine

Supports two modes:
1. Foreground mode (default): Runs in foreground, RECOMMENDED for systemd services
2. Daemon mode (--daemon flag): Traditional Unix daemon - BROKEN with NNG

IMPORTANT: DO NOT USE --daemon with systemd services!
=====================================================
The --daemon flag uses python-daemon's DaemonContext which performs:
- Double fork (only main thread survives, other threads are lost)
- Closes ALL file descriptors (corrupts NNG internal sockets)
- Resets signal handlers (breaks NNG thread communication)

These operations corrupt pynng/NNG internal state, causing connections
to disconnect approximately 0.43 seconds after establishment.

Systemd service configuration MUST use foreground mode:
    ExecStart=/usr/lib/cuems/bin/node-engine
    (NOT: ExecStart=/usr/lib/cuems/bin/node-engine --daemon)

The --daemon flag is preserved only for edge cases outside of systemd
where traditional Unix daemon behavior is absolutely required.
"""

import signal
import argparse

from cuemsutils.log import Logger
from cuemsengine.NodeEngine import NodeEngine
from cuemsutils.daemon import run_daemon


def run_manual():
    """Run node engine in manual/development mode (foreground)"""
    Logger.info("Starting CUEMS Node Engine in MANUAL mode (foreground)")
    
    # Create and start engine
    engine = NodeEngine()
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
    """
    Run node engine in daemon mode.
    
    WARNING: BROKEN with NNG/pynng!
    python-daemon's DaemonContext.open() will:
    1. Double-fork (loses all threads except main)
    2. Close all file descriptors (corrupts NNG sockets)
    3. Reset signal handlers (breaks NNG internals)
    
    Result: NNG connections disconnect after ~0.43 seconds.
    Use foreground mode for systemd services instead.
    """
    Logger.warning("DAEMON MODE: python-daemon will corrupt NNG state! Connections will fail after ~0.43s")
    Logger.info("Starting CUEMS Node Engine in DAEMON mode")
    
    # Create engine and run as daemon
    engine = NodeEngine()
    run_daemon(engine, 'node_engine')


def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(
        description='CUEMS Node Engine',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in foreground mode (RECOMMENDED for systemd services)
  %(prog)s
  
  # Run as daemon (DEPRECATED - causes NNG connection issues)
  %(prog)s --daemon
        """
    )
    
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='[DEPRECATED] Run as daemon. WARNING: Incompatible with NNG! Use foreground mode for systemd.'
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

