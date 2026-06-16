# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""
Demonstration test file showing the new cleanup mechanisms.

This file demonstrates how to use the new pytest cleanup fixtures
to prevent background processes from persisting after Ctrl+C.
"""

import pytest
import time
import threading
import multiprocessing
from unittest.mock import patch

from cuemsengine import ControllerEngine, NodeEngine


@pytest.mark.cuems
def test_engine_with_automatic_cleanup(engine_cleanup):
    """Demonstrate automatic engine cleanup on test interruption"""
    print("\n=== Testing engine cleanup mechanism ===")
    
    # Create engines with automatic cleanup registration
    controller = engine_cleanup(ControllerEngine(with_mtc=False))
    node = engine_cleanup(NodeEngine(with_mtc=False))
    
    print(f"Created controller engine: {controller.node_name}")
    print(f"Created node engine: {node.node_name}")
    
    # Simulate some work
    time.sleep(0.1)
    
    # These engines will be automatically cleaned up by the fixture
    assert controller.cm is not None
    assert node.cm is not None
    
    print("Engines created successfully - cleanup will be automatic")


@pytest.mark.cuems
def test_process_with_automatic_cleanup(process_cleanup):
    """Demonstrate automatic process cleanup on test interruption"""
    print("\n=== Testing process cleanup mechanism ===")
    
    def worker_function():
        """Simulate a background worker"""
        while True:
            time.sleep(0.1)
    
    # Create a process with automatic cleanup registration
    worker_process = process_cleanup(
        multiprocessing.Process(target=worker_function, name="TestWorker")
    )
    worker_process.start()
    
    print(f"Started worker process: {worker_process.name}")
    assert worker_process.is_alive()
    
    # Simulate some work
    time.sleep(0.1)
    
    print("Process started successfully - cleanup will be automatic")


@pytest.mark.cuems
def test_combined_cleanup(engine_cleanup, process_cleanup, cuems_cleaner):
    """Demonstrate combined cleanup of engines and processes"""
    print("\n=== Testing combined cleanup mechanism ===")
    
    # Create engine with cleanup
    engine = engine_cleanup(ControllerEngine(with_mtc=False))
    
    # Create process with cleanup
    def background_task():
        for i in range(100):
            time.sleep(0.1)
    
    bg_process = process_cleanup(
        multiprocessing.Process(target=background_task, name="BackgroundTask")
    )
    bg_process.start()
    
    # Add custom cleanup hook
    cleanup_called = []
    def custom_cleanup():
        cleanup_called.append(True)
        print("Custom cleanup function called")
    
    cuems_cleaner.add_cleanup_hook(custom_cleanup)
    
    print(f"Engine: {engine.node_name}")
    print(f"Process: {bg_process.name} (alive: {bg_process.is_alive()})")
    
    # All resources will be cleaned up automatically
    assert engine.cm is not None
    assert bg_process.is_alive()
    
    print("Combined resources created - all will be cleaned up automatically")


def test_cleanup_on_exception(engine_cleanup):
    """Demonstrate cleanup when test raises an exception"""
    print("\n=== Testing cleanup on exception ===")
    
    # Create engine that should be cleaned up even if test fails
    engine = engine_cleanup(ControllerEngine(with_mtc=False))
    
    print(f"Created engine: {engine.node_name}")
    
    # Uncomment the next line to test exception handling
    # raise ValueError("This is a test exception")
    
    assert engine.cm is not None
    print("Test completed normally")


@pytest.mark.slow
def test_long_running_with_cleanup(engine_cleanup, process_cleanup):
    """Demonstrate cleanup for long-running tests (try Ctrl+C during this test)"""
    print("\n=== Testing long-running test cleanup ===")
    print("Try pressing Ctrl+C during this test to see cleanup in action")
    
    # Create multiple resources
    engines = []
    processes = []
    
    for i in range(3):
        engine = engine_cleanup(ControllerEngine(with_mtc=False))
        engines.append(engine)
        print(f"Created engine {i}: {engine.node_name}")
    
    def worker(worker_id):
        while True:
            print(f"Worker {worker_id} is working...")
            time.sleep(1)
    
    for i in range(2):
        process = process_cleanup(
            multiprocessing.Process(target=worker, args=(i,), name=f"Worker{i}")
        )
        process.start()
        processes.append(process)
        print(f"Started worker process {i}")
    
    print("\n" + "="*50)
    print("PRESS Ctrl+C NOW TO TEST CLEANUP!")
    print("="*50)
    
    # Simulate long-running work
    for i in range(30):  # 30 seconds
        time.sleep(1)
        print(f"Working... {i+1}/30 seconds")
        
        # Verify resources are still alive
        for engine in engines:
            assert engine.cm is not None
        
        for process in processes:
            if not process.is_alive():
                print(f"Process {process.name} died unexpectedly")
    
    print("Long-running test completed successfully")


if __name__ == "__main__":
    print("Run this with: pytest tests/test_cleanup_demo.py -v -s")
    print("Try pressing Ctrl+C during the long_running test to see cleanup in action") 
