import signal
import sys
import pytest
import threading
import multiprocessing
from pathlib import Path

# Store references to cleanup functions
_cleanup_functions = []

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
    """Session-level fixture that ensures cleanup happens even on interruption"""
    yield
    # This will run at the end of the test session
    # Call cleanup functions in case they weren't called by signal handler
    for cleanup_func in _cleanup_functions:
        try:
            cleanup_func()
        except Exception:
            pass  # Ignore errors during normal exit cleanup

@pytest.fixture
def engine_cleanup():
    """Fixture to ensure engine instances are properly cleaned up"""
    engines = []
    
    def register_engine(engine):
        """Register an engine for cleanup"""
        engines.append(engine)
        
        # Add engine-specific cleanup function
        def cleanup_engine():
            if hasattr(engine, 'stop') and callable(engine.stop):
                engine.stop()
            if hasattr(engine, 'stop_all') and callable(engine.stop_all):
                engine.stop_all()
        
        add_cleanup_function(cleanup_engine)
        return engine
    
    yield register_engine
    
    # Cleanup all registered engines at the end of the test
    for engine in engines:
        try:
            if hasattr(engine, 'stop') and callable(engine.stop):
                engine.stop()
            if hasattr(engine, 'stop_all') and callable(engine.stop_all):
                engine.stop_all()
        except Exception as e:
            print(f"Error stopping engine: {e}")

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
