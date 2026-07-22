#!/usr/bin/env python3
"""
Test runner script for CPU usage tests.
This script provides an easy way to run CPU usage tests with different options.
"""

import sys
import subprocess
import argparse
from pathlib import Path

def run_tests(test_pattern="test_cpu_usage.py", markers=None, verbose=False, coverage=False):
    """Run the CPU usage tests with specified options"""
    
    # Build pytest command
    cmd = ["python", "-m", "pytest"]
    
    # Add test file pattern
    cmd.append(f"tests/{test_pattern}")
    
    # Add markers if specified
    if markers:
        cmd.extend(["-m", markers])
    
    # Add verbose flag
    if verbose:
        cmd.append("-v")
    
    # Add coverage if requested
    if coverage:
        cmd.extend(["--cov=src/cuemsengine", "--cov-report=term-missing"])
    
    # Add other useful flags
    cmd.extend([
        "--tb=short",  # Short traceback format
        "--durations=10",  # Show 10 slowest tests
        "--strict-markers",  # Enforce marker definitions
    ])
    
    print(f"Running command: {' '.join(cmd)}")
    print("-" * 60)
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print("-" * 60)
        print("Tests completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print("-" * 60)
        print(f"Tests failed with exit code: {e.returncode}")
        return False
    except KeyboardInterrupt:
        print("\nTests interrupted by user")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Run CPU usage tests for BaseEngine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all CPU tests
  python run_cpu_tests.py
  
  # Run only fast tests (exclude slow ones)
  python run_cpu_tests.py --markers "not slow"
  
  # Run only integration tests
  python run_cpu_tests.py --markers "integration"
  
  # Run with coverage
  python run_cpu_tests.py --coverage
  
  # Run specific test file
  python run_cpu_tests.py --test-file test_cpu_usage.py
        """
    )
    
    parser.add_argument(
        "--test-file",
        default="test_cpu_usage.py",
        help="Test file pattern to run (default: test_cpu_usage.py)"
    )
    
    parser.add_argument(
        "--markers",
        help="Pytest markers to include/exclude (e.g., 'not slow', 'integration')"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Run tests in verbose mode"
    )
    
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Generate coverage report"
    )
    
    parser.add_argument(
        "--list-tests",
        action="store_true",
        help="List available tests without running them"
    )
    
    args = parser.parse_args()
    
    if args.list_tests:
        print("Available CPU usage tests:")
        print("-" * 40)
        print("test_base_engine_idle_cpu_usage")
        print("test_base_engine_continuous_operation_cpu_usage")
        print("test_base_engine_memory_usage")
        print("test_base_engine_cpu_spike_handling")
        print("test_base_engine_long_running_stability")
        print("test_base_engine_cleanup_cpu_usage")
        print("\nMarkers:")
        print("- slow: Long-running tests")
        print("- integration: Integration tests")
        print("- cuems: CUEMS engine tests")
        return
    
    # Check if we're in the right directory
    if not Path("tests").exists():
        print("Error: Please run this script from the project root directory")
        print("Current directory:", Path.cwd())
        sys.exit(1)
    
    # Check if pytest is available
    try:
        import pytest
    except ImportError:
        print("Error: pytest is not installed. Please install it first:")
        print("pip install pytest")
        sys.exit(1)
    
    # Check if psutil is available
    try:
        import psutil
    except ImportError:
        print("Error: psutil is not installed. Please install it first:")
        print("pip install psutil")
        sys.exit(1)
    
    print("CUEMS Engine CPU Usage Tests")
    print("=" * 40)
    
    success = run_tests(
        test_pattern=args.test_file,
        markers=args.markers,
        verbose=args.verbose,
        coverage=args.coverage
    )
    
    if success:
        print("\nAll tests passed! 🎉")
        sys.exit(0)
    else:
        print("\nSome tests failed! ❌")
        sys.exit(1)

if __name__ == "__main__":
    main() 
