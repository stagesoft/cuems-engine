# CUEMS Testing Cleanup Mechanisms

This document explains the improved pytest setup that prevents background processes from persisting when tests are interrupted with `Ctrl+C`.

## Problem

Previously, when pytest tests were cancelled using `Ctrl+C`, background processes and threads created by CUEMS engines would continue running, requiring manual cleanup. This was caused by:

1. **Daemon threads** from `MtcListener` and other components
2. **Subprocesses** spawned by `Player` classes
3. **Multiprocessing.Process** instances in tests
4. **Threading** from `OssiaServer` and WebSocket servers
5. **Incomplete cleanup** during test interruption

## Solution

We've implemented a comprehensive cleanup system with multiple layers:

### 1. Signal Handling (`conftest.py`)
- Registers `SIGINT` handler to catch `Ctrl+C`
- Automatically calls cleanup functions for all registered resources
- Terminates daemon threads and multiprocessing children
- Provides graceful shutdown with fallback to force termination

### 2. Pytest Plugin (`pytest_cuems_plugin.py`)
- Custom pytest plugin for CUEMS-specific cleanup
- Automatic registration and cleanup of engines, processes, and threads
- Hooks into pytest's lifecycle events
- Handles test failures and interruptions

### 3. Cleanup Fixtures
- `engine_cleanup`: Automatically manages CUEMS engine instances
- `process_cleanup`: Tracks and cleans up multiprocessing.Process instances
- `cuems_cleaner`: Provides access to the cleanup system

## Usage

### Basic Engine Testing
```python
def test_my_engine(engine_cleanup):
    # Register engine for automatic cleanup
    engine = engine_cleanup(ControllerEngine(with_mtc=False))
    
    # Test your engine
    assert engine.cm is not None
    
    # Cleanup is automatic - no need for manual stop()
```

### Process Testing
```python
def test_with_processes(process_cleanup):
    # Register process for automatic cleanup
    process = process_cleanup(
        multiprocessing.Process(target=worker_func, name="TestWorker")
    )
    process.start()
    
    # Test your process
    assert process.is_alive()
    
    # Cleanup is automatic
```

### Combined Resources
```python
def test_complex_scenario(engine_cleanup, process_cleanup, cuems_cleaner):
    engine = engine_cleanup(NodeEngine(with_mtc=False))
    process = process_cleanup(multiprocessing.Process(target=task))
    
    # Add custom cleanup
    cuems_cleaner.add_cleanup_hook(lambda: print("Custom cleanup"))
    
    # All resources cleaned up automatically
```

### Custom Cleanup Hooks
```python
def test_with_custom_cleanup(cuems_cleaner):
    # Setup custom resources
    my_resource = SomeResource()
    
    # Register cleanup
    cuems_cleaner.add_cleanup_hook(lambda: my_resource.cleanup())
    
    # Test code here
```

## Configuration

### Pytest Configuration
The `pyproject.toml` file includes:
```toml
[tool.pytest.ini_options]
addopts = [
    "-p", "tests.pytest_cuems_plugin",  # Enable cleanup plugin
    # ... other options
]
markers = [
    "cuems: marks tests as using CUEMS engines (automatic cleanup)",
]
timeout = 300  # 5 minutes timeout
```

### Test Markers
Mark tests that use CUEMS components:
```python
@pytest.mark.cuems
def test_engine_functionality(engine_cleanup):
    # Test code
```

## Testing the Cleanup

### Run Demo Tests
```bash
# Run all cleanup demos
pytest tests/test_cleanup_demo.py -v -s

# Run specific demo
pytest tests/test_cleanup_demo.py::test_long_running_with_cleanup -v -s

# Run without slow tests
pytest tests/test_cleanup_demo.py -v -s -m "not slow"
```

### Manual Testing
1. Start the long-running test:
   ```bash
   pytest tests/test_cleanup_demo.py::test_long_running_with_cleanup -v -s
   ```

2. Press `Ctrl+C` during execution

3. Observe the cleanup messages:
   ```
   ^C
   Received interrupt signal, cleaning up...
   === CUEMS Test Cleanup Started ===
   Stopped engine: ControllerEngine
   Terminated process: Worker0
   Terminated process: Worker1
   === CUEMS Test Cleanup Complete ===
   Cleanup complete, exiting...
   ```

4. Verify no background processes remain:
   ```bash
   ps aux | grep -E "(python|cuems)" | grep -v grep
   ```

## Migration Guide

### Updating Existing Tests

1. **Add cleanup fixtures to test functions:**
   ```python
   # Before
   def test_engine():
       engine = ControllerEngine(with_mtc=False)
       # test code
       engine.stop()
   
   # After
   def test_engine(engine_cleanup):
       engine = engine_cleanup(ControllerEngine(with_mtc=False))
       # test code - cleanup is automatic
   ```

2. **Register processes:**
   ```python
   # Before
   def test_with_process():
       process = multiprocessing.Process(target=worker)
       process.start()
       # test code
       process.terminate()
   
   # After
   def test_with_process(process_cleanup):
       process = process_cleanup(multiprocessing.Process(target=worker))
       process.start()
       # test code - cleanup is automatic
   ```

3. **Add markers:**
   ```python
   @pytest.mark.cuems
   def test_cuems_functionality(engine_cleanup):
       # test code
   ```

## Benefits

1. **No More Orphan Processes**: All background processes are properly terminated
2. **Cleaner Test Environment**: Each test starts with a clean slate
3. **Easier Debugging**: No interference from previous test runs
4. **Better CI/CD**: Automated tests won't leave hanging processes
5. **Developer Experience**: No manual process cleanup required

## Troubleshooting

### If Processes Still Persist
1. Check if test uses the cleanup fixtures
2. Verify the plugin is loaded: `pytest --trace-config`
3. Ensure signal handlers aren't overridden
4. Add debug prints to cleanup functions

### For Custom Resources
If you have custom resources that need cleanup:
```python
def test_custom_resource(cuems_cleaner):
    resource = MyCustomResource()
    cuems_cleaner.add_cleanup_hook(resource.cleanup)
    # test code
```

### Debugging Cleanup Issues
Enable verbose logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Related Files

- `tests/conftest.py` - Main signal handling and fixtures
- `tests/pytest_cuems_plugin.py` - Custom pytest plugin
- `tests/test_cleanup_demo.py` - Demonstration tests
- `pyproject.toml` - Pytest configuration
- `tests/test_project_load.py` - Updated to use new fixtures 
