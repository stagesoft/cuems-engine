# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import multiprocessing
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

# Store references to cleanup functions
_cleanup_functions = []

# WATCHDOG: Force exit if cleanup hangs after test completion
_test_start_time = time.time()
_pytest_finished = False
_cleanup_start_time = None


def _watchdog():
    """Background thread that force-exits if cleanup hangs"""
    while True:
        time.sleep(0.5)

        # If cleanup started, give it 5 seconds max
        if _cleanup_start_time:
            cleanup_time = time.time() - _cleanup_start_time
            if cleanup_time > 5:
                print(
                    f"\n⚠️  WATCHDOG: Cleanup took {cleanup_time:.1f}s, force"
                    f"exiting"
                )
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(0)

        # Absolute max runtime: 40 seconds (should never hit this)
        runtime = time.time() - _test_start_time
        if runtime > 40:
            print(
                f"\n⚠️  WATCHDOG: Total runtime {runtime:.0f}s exceeded,"
                f"force exiting"
            )
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)


_watchdog_thread = threading.Thread(
    target=_watchdog, daemon=True, name="Watchdog"
)
_watchdog_thread.start()


def add_cleanup_function(func):
    """Register a cleanup function to be called on test interruption"""
    _cleanup_functions.append(func)


def signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) by calling all registered cleanup functions"""
    print("\nReceived interrupt signal, cleaning up...")

    # Call all registered cleanup functions
    for cleanup_func in _cleanup_functions:
        try:
            cleanup_func()
        except Exception as e:
            print(f"Error during cleanup: {e}")

    # Terminate all daemon threads
    for thread in threading.enumerate():
        if thread != threading.current_thread() and thread.daemon:
            print(f"Terminating daemon thread: {thread.name}")
            # For daemon threads, we can't force terminate them gracefully
            # but setting daemon=True should make them exit when main exits

    # Terminate any remaining multiprocessing processes
    for process in multiprocessing.active_children():
        print(f"Terminating process: {process.name}")
        process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            print(f"Force killing process: {process.name}")
            process.kill()

    print("Cleanup complete, exiting...")
    sys.exit(1)


# Register the signal handler for SIGINT (Ctrl+C)
signal.signal(signal.SIGINT, signal_handler)


@pytest.fixture(scope="session", autouse=True)
def cleanup_on_exit():
    """
    Session-level fixture that ensures cleanup happens even on interruption
    """
    global _pytest_finished, _cleanup_start_time

    yield

    # Mark that tests are done, now in cleanup phase
    _cleanup_start_time = time.time()

    # Do quick cleanup
    for cleanup_func in _cleanup_functions:
        try:
            cleanup_func()
        except:
            pass

    # Mark finished (watchdog will wait 2 more seconds then kill if needed)
    _pytest_finished = True

    # Give threads a moment to finish
    time.sleep(0.5)


@pytest.fixture
def engine_cleanup():
    """
    Fixture to ensure engine instances are properly cleaned up - AGGRESSIVE
    MODE
    """
    import threading

    engines = []

    def force_kill_threads():
        """Force kill all daemon threads"""
        for thread in threading.enumerate():
            if thread != threading.current_thread() and thread.is_alive():
                if hasattr(thread, "_stop"):
                    try:
                        thread._stop()
                    except:
                        pass

    def aggressive_cleanup(engine):
        """Aggressively cleanup engine with no mercy"""
        try:
            # Stop communications thread first
            if hasattr(engine, "communications_thread"):
                comm = engine.communications_thread
                comm.stop_requested = True
                if hasattr(comm, "event_loop") and comm.event_loop:
                    try:
                        comm.event_loop.stop()
                    except:
                        pass
                if (
                    hasattr(comm, "ocsquery_queue_loop")
                    and comm.ocsquery_queue_loop.is_alive()
                ):
                    # Don't wait, just mark as stopped
                    pass

            # Stop OSCQuery
            if hasattr(engine, "oscquery_server"):
                try:
                    engine.oscquery_server.remove_device()
                except:
                    pass

            if hasattr(engine, "oscquery_client"):
                try:
                    del engine.oscquery_client
                except:
                    pass

            # Quick stop calls without waiting
            if hasattr(engine, "stop"):
                try:
                    engine.stop()
                except:
                    pass

            if hasattr(engine, "stop_all"):
                try:
                    engine.stop_all()
                except:
                    pass

        except Exception:
            pass  # Suppress all errors

    def register_engine(engine):
        """Register an engine for cleanup"""
        engines.append(engine)
        return engine

    yield register_engine

    # AGGRESSIVE CLEANUP - don't wait for anything
    for engine in engines:
        aggressive_cleanup(engine)

    # Force kill any remaining threads
    force_kill_threads()


@pytest.fixture
def process_cleanup():
    """Fixture to track and cleanup multiprocessing.Process instances"""
    processes = []

    def register_process(process):
        """Register a process for cleanup"""
        processes.append(process)

        def cleanup_process():
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()

        add_cleanup_function(cleanup_process)
        return process

    yield register_process

    # Cleanup all processes at the end of the test
    for process in processes:
        try:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
        except Exception:
            pass


# Add project root to Python path (existing functionality)
project_root = Path(__file__).parent.parent
src_path = str(project_root / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
