# CPU Usage Tests for BaseEngine

This directory contains comprehensive tests for monitoring CPU usage of running `BaseEngine` instances in the CUEMS Engine system.

## Overview

The CPU usage tests are designed to:
- Monitor CPU consumption during different engine states
- Ensure the engine doesn't consume excessive resources
- Test stability and recovery from CPU spikes
- Monitor memory usage patterns
- Validate cleanup procedures

## Test Structure

### Test Classes

- **`TestBaseEngineCPUUsage`**: Main test class containing all CPU monitoring tests

### Test Methods

1. **`test_base_engine_idle_cpu_usage`**
   - Tests CPU usage when the engine is idle
   - Verifies low resource consumption during minimal activity
   - Duration: ~3 seconds

2. **`test_base_engine_continuous_operation_cpu_usage`**
   - Tests CPU usage during continuous engine operations
   - Simulates periodic status updates and operations
   - Duration: ~10 seconds

3. **`test_base_engine_memory_usage`**
   - Monitors memory consumption during operations
   - Tests for memory leaks or excessive usage
   - Duration: ~5 seconds

4. **`test_base_engine_cpu_spike_handling`**
   - Tests engine recovery after CPU-intensive operations
   - Verifies CPU usage returns to baseline levels
   - Duration: ~5 seconds

5. **`test_base_engine_long_running_stability`**
   - Tests CPU stability over extended periods
   - Identifies any long-term resource consumption issues
   - Duration: ~15 seconds

6. **`test_base_engine_cleanup_cpu_usage`**
   - Tests resource cleanup after engine shutdown
   - Ensures no lingering CPU usage after cleanup
   - Duration: ~3 seconds

## Prerequisites

### Required Dependencies

```bash
# Core testing dependencies
pip install pytest pytest-cov pytest-xdist

# CPU monitoring dependency
pip install psutil

# Development dependencies (if not already installed)
pip install -e ".[dev]"
```

### System Requirements

- Python 3.11+
- Linux system (for accurate psutil measurements)
- Sufficient CPU resources for testing
- No other CPU-intensive processes running

## Running the Tests

### Using the Test Runner Script

```bash
# Run all CPU tests
python tests/run_cpu_tests.py

# Run only fast tests (exclude slow ones)
python tests/run_cpu_tests.py --markers "not slow"

# Run only integration tests
python tests/run_cpu_tests.py --markers "integration"

# Run with verbose output
python tests/run_cpu_tests.py --verbose

# Run with coverage report
python tests/run_cpu_tests.py --coverage

# List available tests
python tests/run_cpu_tests.py --list-tests
```

### Using pytest Directly

```bash
# Run all CPU tests
pytest tests/test_cpu_usage.py -v

# Run specific test
pytest tests/test_cpu_usage.py::TestBaseEngineCPUUsage::test_base_engine_idle_cpu_usage -v

# Run tests with markers
pytest tests/test_cpu_usage.py -m "not slow" -v

# Run tests in parallel (if pytest-xdist is installed)
pytest tests/test_cpu_usage.py -n auto -v
```

## Test Markers

- **`@pytest.mark.slow`**: Tests that take longer to run (>5 seconds)
- **`@pytest.mark.integration`**: Tests that involve multiple components
- **`@pytest.mark.cuems`**: Tests that use CUEMS engines (automatic cleanup)

## Interpreting Results

### CPU Usage Thresholds

- **Idle State**: Should be < 10% average, < 20% peak
- **Active Operations**: Should be < 50% average, < 80% peak
- **Recovery**: Should return to baseline levels after spikes
- **Long-term Stability**: Range should be < 30% (max - min)

### Memory Usage Thresholds

- **Total Memory**: Should be < 500 MB
- **Memory Increase**: Should be < 100 MB during operations

### Test Output

Each test provides detailed output including:
- CPU usage statistics (min, max, average)
- Memory consumption patterns
- Operation counts and durations
- Recovery ratios and stability metrics

## Troubleshooting

### Common Issues

1. **High CPU Usage During Tests**
   - Ensure no other processes are consuming CPU
   - Check system load with `top` or `htop`
   - Verify test environment is clean

2. **Memory Issues**
   - Check for memory leaks in the engine
   - Verify cleanup procedures are working
   - Monitor system memory with `free -h`

3. **Test Failures**
   - Check dependency versions
   - Verify system resources
   - Review test logs for specific error messages

### Debug Mode

Run tests with increased verbosity for debugging:

```bash
pytest tests/test_cpu_usage.py -v -s --tb=long
```

### Performance Profiling

For detailed performance analysis, use pytest-profiling:

```bash
pip install pytest-profiling
pytest tests/test_cpu_usage.py --profile
```

## Customization

### Adjusting Thresholds

Modify the assertion values in test methods to adjust acceptable thresholds:

```python
# Example: Adjust idle CPU threshold
assert idle_cpu_stats['avg'] < 15.0, f"Idle CPU usage too high: {idle_cpu_stats['avg']}%"
```

### Adding New Tests

To add new CPU monitoring tests:

1. Create a new test method in `TestBaseEngineCPUUsage`
2. Use the existing monitoring utilities
3. Add appropriate assertions and logging
4. Include relevant pytest markers

### Monitoring Custom Metrics

Extend the monitoring utilities to track additional metrics:

```python
def monitor_custom_metric(self, process, metric_name, duration=5.0):
    """Monitor custom system metrics"""
    # Implementation here
    pass
```

## Integration with CI/CD

### GitHub Actions Example

```yaml
- name: Run CPU Usage Tests
  run: |
    pip install -e ".[dev]"
    pytest tests/test_cpu_usage.py -m "not slow" --junitxml=cpu-tests.xml
```

### Jenkins Pipeline Example

```groovy
stage('CPU Tests') {
    steps {
        sh 'pip install -e ".[dev]"'
        sh 'pytest tests/test_cpu_usage.py --junitxml=cpu-tests.xml'
    }
    post {
        always {
            junit 'cpu-tests.xml'
        }
    }
}
```

## Contributing

When contributing to CPU usage tests:

1. Follow the existing test patterns
2. Add appropriate markers and documentation
3. Ensure tests are deterministic and reliable
4. Include performance benchmarks if applicable
5. Update this README with new test information

## Support

For issues with CPU usage tests:

1. Check the troubleshooting section
2. Review test logs and output
3. Verify system requirements
4. Open an issue with detailed error information

## License

These tests are part of the CUEMS Engine project and are licensed under the same terms as the main project. 
