#!/usr/bin/env python3

from cuemsengine.ControllerEngine import ControllerEngine
from cuemsutils.daemon import run_daemon
from time import sleep
from .fixtures import env_config_path, mock_library_path

def test_controller_engine(env_config_path, mock_library_path):
    engine = ControllerEngine(with_mtc=False)
    engine.load_project('empty_test')

    run_daemon(engine, 'controller_engine')
    sleep(10)
    engine.stop()

    assert False
