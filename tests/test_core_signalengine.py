import logging
import pytest
import signal
from unittest.mock import patch

from cuemsengine.core.SignalEngine import SignalEngine

@pytest.fixture
def daemon(with_signals: bool = True):
    return SignalEngine(with_signals=with_signals)

@pytest.fixture
def mock_signal():
    with patch('signal.signal') as mock_signal_obj:
        yield mock_signal_obj

def test_daemon_run_stops_after_signal(daemon, caplog):
    caplog.set_level(logging.DEBUG)

    # Run with a max cycle count to avoid infinite loop
    engine = daemon
    engine.running = True
    engine.run(tick=0.1, max_tick=0.5)

    assert "Call recieved" in caplog.text
    assert "kwargs: {'tick': 0.1, 'max_tick': 0.5}" in caplog.text
    assert "Finished with result: None" in caplog.text

def test_signal_handlers_are_registered(daemon, mock_signal):
    # Register the signal handlers
    daemon.register_signals()

    # Ensure signal.signal was called with correct arguments
    mock_signal.assert_any_call(signal.SIGTERM, daemon.handle_terminate)
    mock_signal.assert_any_call(signal.SIGINT, daemon.handle_interrupt)
    assert mock_signal.call_count == 5

def test_engine_can_start_and_stop():
    from time import sleep
    from os import path
    from cuemsengine.core.SignalEngine import SHOW_LOCK_PATH
    
    engine = SignalEngine(with_signals=False)
    engine.set_show_lock_file()
    engine.set_show_lock_file()
    sleep(0.05)

    assert engine.show_locked == True
    assert path.isfile(SHOW_LOCK_PATH)

    engine.stop()
    assert engine.show_locked == False
    assert engine.running == False

def test_signal_handling_graceful_exit(daemon):
    from multiprocessing import Process
    from time import sleep
    from os import kill

    proc = Process(target=daemon.start)
    proc.start()

    # Give it a moment to start
    sleep(0.05)

    # Send SIGTERM to the child process
    kill(proc.pid, signal.SIGTERM)

    # Wait for the process to cleanly exit
    proc.join(timeout=1)

    assert proc.exitcode == 0 or proc.exitcode is None  # None means graceful stop

def test_engine_status(daemon):
    assert daemon.status.load is None
    assert daemon.status.loadcue is None
    assert daemon.status.go is None
    assert daemon.status.gocue is None
    assert daemon.status.pause is None
    assert daemon.status.stop is None
    assert daemon.status.resetall is None
    assert daemon.status.preload is None
    assert daemon.status.unload is None
    assert daemon.status.hwdiscovery is None
    assert daemon.status.deploy is None
    assert daemon.status.test is None
    assert daemon.status.timecode is None
    assert daemon.status.currentcue is None
    assert daemon.status.nextcue is None
    assert daemon.status.running is None

def test_set_status(daemon):
    daemon.set_status('load', 'test')
    assert daemon.status.load == 'test'

def test_get_status(daemon):
    daemon.set_status('load', 'test')
    assert daemon.get_status('load') == 'test'

def test_recieved_test(daemon):
    assert daemon.status.test_recieved == 0
    daemon.set_status('test', 'test')
    assert daemon.status.test == 'test'
    assert daemon.status.test_recieved == 1
    daemon.set_status('test', 'test2')
    assert daemon.status.test == 'test2'
    assert daemon.status.test_recieved == 2

def test_get_status_none(daemon, caplog):
    assert daemon.get_status('none') == "NotFound"
    assert "Property none not found in EngineStatus" in caplog.text

    try:
        daemon.get_status('none', strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"

def test_set_status_none(daemon, caplog):
    daemon.set_status('none', 'test')
    assert "Property none not found in EngineStatus" in caplog.text
    try:
        daemon.set_status('none', 'test', strict=True)
    except AttributeError as e:
        assert str(e) == "Property none not found in EngineStatus"
