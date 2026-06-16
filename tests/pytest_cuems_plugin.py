# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""
Pytest plugin for CUEMS engine testing.

This plugin provides automatic cleanup of background processes, threads,
and other resources when tests are interrupted with Ctrl+C or fail unexpectedly.
"""

import pytest
import signal
import sys
import threading
import multiprocessing
import os
from typing import List, Callable

# Global registry for cleanup functions
_active_engines = []
_active_processes = []
_active_threads = []
_cleanup_hooks = []

class CuemsTestCleaner:
    """Manages cleanup of CUEMS test resources"""
    
    @classmethod
    def register_engine(cls, engine):
        """Register an engine instance for cleanup"""
        _active_engines.append(engine)
        return engine
    
    @classmethod
    def register_process(cls, process):
        """Register a process for cleanup"""
        _active_processes.append(process)
        return process
    
    @classmethod
    def register_thread(cls, thread):
        """Register a thread for cleanup"""
        _active_threads.append(thread)
        return thread
    
    @classmethod
    def add_cleanup_hook(cls, func: Callable):
        """Add a custom cleanup function"""
        _cleanup_hooks.append(func)
    
    @classmethod
    def cleanup_all(cls):
        """Clean up all registered resources"""
        print("\n=== CUEMS Test Cleanup Started ===")
        
        # Call custom cleanup hooks first
        for hook in _cleanup_hooks:
            try:
                hook()
            except Exception as e:
                print(f"Error in cleanup hook: {e}")
        
        # Stop all engines
        for engine in _active_engines:
            try:
                if hasattr(engine, 'stop_all') and callable(engine.stop_all):
                    engine.stop_all()
                elif hasattr(engine, 'stop') and callable(engine.stop):
                    engine.stop()
                print(f"Stopped engine: {engine.__class__.__name__}")
            except Exception as e:
                print(f"Error stopping engine {engine.__class__.__name__}: {e}")
        
        # Terminate all registered processes
        for process in _active_processes:
            try:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)
                    if process.is_alive():
                        process.kill()
                    print(f"Terminated process: {process.name}")
            except Exception as e:
                print(f"Error terminating process {process.name}: {e}")
        
        # Join all registered threads
        for thread in _active_threads:
            try:
                if thread.is_alive():
                    thread.join(timeout=1)
                    print(f"Joined thread: {thread.name}")
            except Exception as e:
                print(f"Error joining thread {thread.name}: {e}")
        
        # Clean up any remaining multiprocessing children
        for child in multiprocessing.active_children():
            try:
                child.terminate()
                child.join(timeout=1)
                if child.is_alive():
                    child.kill()
                print(f"Cleaned up orphan process: {child.name}")
            except Exception as e:
                print(f"Error cleaning orphan process: {e}")
        
        # Force cleanup daemon threads
        for thread in threading.enumerate():
            if thread != threading.current_thread() and thread.daemon:
                print(f"Daemon thread still running: {thread.name}")
        
        print("=== CUEMS Test Cleanup Complete ===")
        
        # Clear registries
        _active_engines.clear()
        _active_processes.clear()
        _active_threads.clear()
        _cleanup_hooks.clear()

def signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) by cleaning up all resources"""
    print(f"\nReceived signal {signum}, performing emergency cleanup...")
    CuemsTestCleaner.cleanup_all()
    sys.exit(1)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

@pytest.fixture
def cuems_cleaner():
    """Fixture providing access to the CUEMS test cleaner"""
    return CuemsTestCleaner

@pytest.fixture(scope="session", autouse=True)
def cuems_session_cleanup():
    """Session-level automatic cleanup"""
    yield
    # Cleanup at end of session
    CuemsTestCleaner.cleanup_all()

@pytest.fixture(autouse=True)
def cuems_test_isolation():
    """Ensure each test starts with a clean state"""
    # Clear any leftover registrations from previous tests
    _active_engines.clear()
    _active_processes.clear() 
    _active_threads.clear()
    _cleanup_hooks.clear()
    
    yield
    
    # Clean up after each test
    CuemsTestCleaner.cleanup_all()

def pytest_runtest_teardown(item, nextitem):
    """Called after each test run"""
    # Additional cleanup after each test
    CuemsTestCleaner.cleanup_all()

def pytest_keyboard_interrupt(excinfo):
    """Called when Ctrl+C is pressed during test execution"""
    print("\nKeyboard interrupt detected, cleaning up...")
    CuemsTestCleaner.cleanup_all()

def pytest_exception_interact(node, call, report):
    """Called when test raises an exception"""
    if report.failed:
        print(f"\nTest failed: {node.name}, performing cleanup...")
        CuemsTestCleaner.cleanup_all()

# Make the plugin discoverable
def pytest_configure(config):
    """Configure the plugin"""
    config.addinivalue_line(
        "markers", "cuems: mark test as using CUEMS engines (automatic cleanup)"
    ) 
