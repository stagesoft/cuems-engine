#!/usr/bin/env python3

import daemon as daemon
import sys
from pathlib import Path
from typing import Any

from cuemsutils.log import Logger

def run_daemon(engine_instance: Any, pid_name: str) -> None:
    """
    Run an engine instance as a daemon
    
    Args:
        engine_instance: Instance of an engine (NodeEngine or ControllerEngine)
        pid_name: Name to use for the PID file (without extension)
    """
    # Ensure log directory exists
    Path('/var/log/cuems').mkdir(parents=True, exist_ok=True)
    
    # Create daemon context
    context = daemon.DaemonContext(
        working_directory='/',
        umask=0o002,
        pidfile=Path(f'/var/run/cuems/{pid_name}.pid'),
        files_preserve=[sys.stdout, sys.stderr]
    )
    
    # Start daemon
    with context:
        try:
            engine_instance.start()
        except Exception as e:
            Logger.error(f"Engine failed: {e}")
            sys.exit(1)
