# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

import gc
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Store references to cleanup functions
_cleanup_functions = []

# WATCHDOG: last-resort guard against a hang in the cleanup phase.
#
# There used to be a second guard here: an absolute 60s wall-clock cap that
# called os._exit(1), commented "should never hit this". The full suite takes
# ~160s, so it fired on EVERY complete run, killing pytest at ~25% with no
# summary and no traceback — that, not any test defect, is why the suite
# "had to be run per file".
#
# Both guards existed to paper over the pynng teardown abort (ClickUp
# 869ed00ya): stopping the NNG comms threads before interpreter exit is now
# handled properly by _stop_comms_threads() below, so the cap is gone.
#
# What remains only covers the cleanup phase, and exits NON-ZERO. The old
# cleanup guard exited 0, which turned a teardown abort into a green run —
# a hang must be visible, not hidden.
_CLEANUP_TIMEOUT_S = float(os.environ.get("CUEMS_TEST_CLEANUP_TIMEOUT", "30"))
_pytest_finished = False
_cleanup_start_time = None


def _watchdog():
    """Background thread that force-exits if the cleanup phase hangs."""
    while True:
        time.sleep(0.5)

        if _cleanup_start_time:
            cleanup_time = time.time() - _cleanup_start_time
            if cleanup_time > _CLEANUP_TIMEOUT_S:
                print(
                    f"\n⚠️  WATCHDOG: cleanup took {cleanup_time:.1f}s "
                    f"(limit {_CLEANUP_TIMEOUT_S:.0f}s), force exiting"
                )
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(1)


_watchdog_thread = threading.Thread(target=_watchdog, daemon=True, name="Watchdog")
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


@pytest.fixture(autouse=True)
def _no_mdns_lookup():
    """Make controller.local resolution fail instantly instead of timing out.

    BaseEngine.get_controller_ip() resolves CONTROLLER_HOST via
    socket.gethostbyname(). On any machine without an mDNS responder for
    controller.local that call blocks for the resolver timeout — measured at
    5.01s on the dev box — and BaseEngine is constructed in dozens of fixtures,
    so it dominated the suite runtime (~5.1s per BaseEngine fixture setup).

    Failing fast is also the honest default: with no responder, the real
    behaviour is exactly this, and get_controller_ip() falls back to the
    network_map <ip>. Tests that exercise the mDNS path patch the same target
    inside the test body, and that inner patch takes precedence over this one.
    """
    with patch(
        "cuemsengine.core.BaseEngine.socket.gethostbyname",
        side_effect=socket.gaierror("mDNS disabled in tests"),
    ):
        yield


def _stop_comms_threads():
    """Stop every live AsyncCommsThread before the interpreter tears down.

    pynng registers an atexit hook that calls nng_fini(), freeing NNG's global
    state. CPython does not join daemon threads before running atexit hooks, so
    any comms thread still alive — or any suspended arecv_msg() coroutine still
    waiting to be garbage-collected — lands in freed NNG internals and aborts
    the process with "panic: pthread_mutex_lock: Invalid argument"
    (ClickUp 869ed00ya, exit 134 after a fully green run).

    Production code stops these threads via NodeEngine/ControllerEngine
    stop_comms(). Tests construct hubs and comms threads directly and never go
    through that path, so the suite needs the same discipline here.
    """
    try:
        from cuemsengine.comms.AsyncCommsThread import AsyncCommsThread
    except Exception:
        return

    for thread in threading.enumerate():
        if isinstance(thread, AsyncCommsThread) and thread.is_alive():
            try:
                thread.stop(timeout=5)
            except Exception as e:
                print(f"Error stopping comms thread {thread.name}: {e}")


def _free_orphan_nng_aios():
    """Free any pynng aio still alive, while NNG itself is still up.

    Stopping the comms threads is not enough. A test that abandons a suspended
    arecv_msg()/asend() coroutine leaves its pynng AIOHelper alive with
    ``self.aio`` set. Nothing frees it until the interpreter's final GC — which
    runs AFTER pynng's atexit nng_fini() has already destroyed NNG's global
    state, so AIOHelper.__del__ -> nng_aio_free() aborts the process
    (ClickUp 869ed00ya, "panic: pthread_mutex_lock: Invalid argument" via
    nni_aio_free -> nni_aio_fini).

    Collecting first lets ordinary garbage finalize cleanly; whatever survives
    is freed explicitly here. _free() sets aio = None, so the later __del__
    becomes a no-op and interpreter shutdown stays quiet.
    """
    gc.collect()

    freed = 0
    for obj in gc.get_objects():
        if type(obj).__name__ != "AIOHelper":
            continue
        try:
            if getattr(obj, "aio", None) is None:
                continue
            obj._free()
            freed += 1
        except Exception:
            pass

    if freed:
        print(f"Freed {freed} orphaned pynng aio(s) before interpreter shutdown")


@pytest.fixture(scope="session", autouse=True)
def cleanup_on_exit():
    """
    Session-level fixture that ensures cleanup happens even on interruption
    """
    global _pytest_finished, _cleanup_start_time

    yield

    # Mark that tests are done, now in cleanup phase
    _cleanup_start_time = time.time()

    # Both must happen before pynng's atexit nng_fini() frees NNG's globals.
    _stop_comms_threads()
    _free_orphan_nng_aios()

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
