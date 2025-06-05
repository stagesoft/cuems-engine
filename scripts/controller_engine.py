#!/usr/bin/env python3

from cuemsengine.ControllerEngine import ControllerEngine
from cuemsengine.core.daemon import run_daemon

def main():
    # Create and run engine
    engine = ControllerEngine()
    run_daemon(engine, 'controller_engine')

if __name__ == '__main__':
    main()
