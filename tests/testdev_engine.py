#!/usr/bin/env python3

import pytest

from cuemsengine.ControllerEngine import ControllerEngine
from cuemsutils.daemon import run_daemon
from time import sleep
from .fixtures import env_config_path, mock_library_path

# SKIP THIS TEST - It starts a real daemon that may not terminate properly
# and can crash the system. This test is dangerous and should not run.
@pytest.mark.skip(reason="DANGEROUS: Starts real daemon that may not terminate properly, causing system crashes")
def test_controller_engine(env_config_path, mock_library_path):
    """SKIPPED: This test starts a real daemon without proper cleanup.
    
    WARNING: This test has been disabled because it:
    - Starts a real daemon process that may not terminate
    - Sleeps for 10 seconds
    - Always fails (assert False)
    - Can leave processes running and crash the system
    
    If you need to test daemon functionality, use proper cleanup fixtures
    and ensure processes terminate correctly.
    """
    engine = ControllerEngine(with_mtc=False)
    engine.load_project('empty_test')

    run_daemon(engine, 'controller_engine')
    sleep(10)
    engine.stop()

    assert False
