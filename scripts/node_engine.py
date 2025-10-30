#!/usr/bin/env python3

from cuemsengine.NodeEngine import NodeEngine
from cuemsutils.daemon import run_daemon

def main():
    # Create and run engine
    engine = NodeEngine()
    run_daemon(engine, 'node_engine')

if __name__ == '__main__':
    main()
