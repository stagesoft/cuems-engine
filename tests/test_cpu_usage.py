import pytest
import time
import psutil
import threading
from unittest.mock import patch, MagicMock
from pathlib import Path

from cuemsengine.core.BaseEngine import BaseEngine
from cuemsengine.ControllerEngine import ControllerEngine
from cuemsengine.NodeEngine import NodeEngine

from .fixtures import mock_config_manager, env_config_path

class TestBaseEngineCPUUsage:
    """Test class for monitoring CPU usage of BaseEngine instances"""
    
    @pytest.fixture
    def mock_config_manager(self):
        """Mock ConfigManager to avoid file system dependencies"""
        with patch('cuemsengine.core.BaseEngine.ConfigManager') as mock_cm:
            mock_instance = MagicMock()
            mock_instance.node_conf = {
                'uuid': 'test-uuid-123456789012',
                'mtc_port': 'Midi Through Port-0'
            }
            mock_instance.tmp_path = '/tmp'
            mock_instance.is_alive.return_value = True
            mock_instance.getName.return_value = 'TestConfigManager'
            mock_cm.return_value = mock_instance
            yield mock_instance
    
    @pytest.fixture
    def mock_mtc_listener(self):
        """Mock MtcListener to avoid hardware dependencies"""
        with patch('cuemsengine.core.BaseEngine.MtcListener') as mock_mtc:
            mock_instance = MagicMock()
            mock_instance.timecode.return_value = '00:00:00:00'
            mock_instance.run = MagicMock()
            mock_instance.stop = MagicMock()
            mock_instance.join = MagicMock()
            mock_mtc.return_value = mock_instance
            yield mock_instance
    
    @pytest.fixture
    def base_engine(self, env_config_path):
        """Create a BaseEngine instance with mocked dependencies"""
        # Create engine with minimal initialization to avoid external dependencies
        engine = NodeEngine(with_cm=False, with_mtc=True, with_signals=False)
        return engine
    
    def get_process_cpu_percent(self, process, duration=1.0):
        """Get CPU percentage for a process over a specified duration"""
        cpu_percent = process.cpu_percent(interval=duration)
        return cpu_percent
    
    def monitor_cpu_usage(self, process, duration=5.0, interval=0.5):
        """Monitor CPU usage over time and return statistics"""
        cpu_readings = []
        start_time = time.time()
        
        while time.time() - start_time < duration:
            cpu_percent = self.get_process_cpu_percent(process, interval)
            cpu_readings.append(cpu_percent)
            time.sleep(interval)
        
        if cpu_readings:
            return {
                'min': min(cpu_readings),
                'max': max(cpu_readings),
                'avg': sum(cpu_readings) / len(cpu_readings),
                'readings': cpu_readings,
                'duration': duration
            }
        return {'min': 0, 'max': 0, 'avg': 0, 'readings': [], 'duration': duration}
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_base_engine_idle_cpu_usage(self, base_engine, engine_cleanup):
        """Test CPU usage when BaseEngine is idle (minimal activity)"""
        # Register engine for cleanup
        engine_cleanup(base_engine)
        # base_engine.start()
        
        current_process = psutil.Process()
        
        # Get baseline CPU usage before engine operations
        baseline_cpu = self.get_process_cpu_percent(current_process, 1.0)
        

        # Monitor CPU usage while engine is idle
        idle_cpu_stats = self.monitor_cpu_usage(current_process, duration=3.0)
        
        # Verify that idle CPU usage is reasonable (should be low)
        assert idle_cpu_stats['avg'] < 10.0, f"Idle CPU usage too high: {idle_cpu_stats['avg']}%"
        assert idle_cpu_stats['max'] < 20.0, f"Peak idle CPU usage too high: {idle_cpu_stats['max']}%"
        
        # Log the results for debugging
        print(f"\nIdle CPU Usage Stats:")
        print(f"  Baseline: {baseline_cpu:.2f}%")
        print(f"  Average: {idle_cpu_stats['avg']:.2f}%")
        print(f"  Min: {idle_cpu_stats['min']:.2f}%")
        print(f"  Max: {idle_cpu_stats['max']:.2f}%")
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_base_engine_continuous_operation_cpu_usage(self, base_engine, engine_cleanup):
        """Test CPU usage during continuous engine operations"""
        # Register engine for cleanup
        engine_cleanup(base_engine)
        
        current_process = psutil.Process()
        
        # Start monitoring in background
        cpu_stats = {'data': None}
        monitoring_complete = threading.Event()
        
        def monitor_cpu():
            cpu_stats['data'] = self.monitor_cpu_usage(current_process, duration=10.0)
            monitoring_complete.set()
        
        monitor_thread = threading.Thread(target=monitor_cpu, daemon=True)
        monitor_thread.start()
        
        # Simulate some engine operations
        start_time = time.time()
        operation_count = 0
        
        while not monitoring_complete.is_set() and (time.time() - start_time) < 12.0:
            # Simulate periodic engine operations
            if hasattr(base_engine, 'status'):
                base_engine.set_status('test_property', f'value_{operation_count}')
                operation_count += 1
            
            # Small delay to simulate work
            time.sleep(0.1)
        
        # Wait for monitoring to complete
        monitoring_complete.wait(timeout=2.0)
        
        if cpu_stats['data']:
            stats = cpu_stats['data']
            
            # Verify that CPU usage during operations is reasonable
            assert stats['avg'] < 50.0, f"Operation CPU usage too high: {stats['avg']}%"
            assert stats['max'] < 80.0, f"Peak operation CPU usage too high: {stats['max']}%"
            
            # Log the results
            print(f"\nOperation CPU Usage Stats:")
            print(f"  Average: {stats['avg']:.2f}%")
            print(f"  Min: {stats['min']:.2f}%")
            print(f"  Max: {stats['max']:.2f}%")
            print(f"  Operations performed: {operation_count}")
        else:
            assert False, "CPU monitoring thread did not complete"
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_base_engine_memory_usage(self, base_engine, engine_cleanup):
        """Test memory usage of BaseEngine instance"""
        # Register engine for cleanup
        engine_cleanup(base_engine)
        
        current_process = psutil.Process()
        
        # Get initial memory usage
        initial_memory = current_process.memory_info().rss / 1024 / 1024  # MB
        
        # Perform some operations
        for i in range(100):
            if hasattr(base_engine, 'status'):
                base_engine.set_status(f'property_{i}', f'value_{i}')
        
        # Get final memory usage
        final_memory = current_process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Verify memory usage is reasonable
        assert final_memory < 500, f"Memory usage too high: {final_memory:.2f} MB"
        assert memory_increase < 100, f"Memory increase too high: {memory_increase:.2f} MB"
        
        print(f"\nMemory Usage:")
        print(f"  Initial: {initial_memory:.2f} MB")
        print(f"  Final: {final_memory:.2f} MB")
        print(f"  Increase: {memory_increase:.2f} MB")
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_base_engine_cpu_spike_handling(self, base_engine, engine_cleanup):
        """Test how BaseEngine handles CPU spikes and recovers"""
        # Register engine for cleanup
        engine_cleanup(base_engine)
        
        current_process = psutil.Process()
        
        # Monitor baseline CPU
        baseline_stats = self.monitor_cpu_usage(current_process, duration=2.0)
        
        # Simulate a CPU-intensive operation
        def cpu_intensive_work():
            # Simulate some CPU-intensive work
            start = time.time()
            while time.time() - start < 1.0:
                _ = sum(i * i for i in range(1000))
        
        # Run CPU-intensive work in a thread
        work_thread = threading.Thread(target=cpu_intensive_work)
        work_thread.start()
        work_thread.join()
        
        # Monitor CPU recovery
        recovery_stats = self.monitor_cpu_usage(current_process, duration=3.0)
        
        # Verify CPU usage recovers to reasonable levels
        assert recovery_stats['avg'] <= baseline_stats['avg'] * 2, \
            f"CPU usage did not recover properly: {recovery_stats['avg']}% vs baseline {baseline_stats['avg']}%"
        
        print(f"\nCPU Spike Recovery Test:")
        print(f"  Baseline average: {baseline_stats['avg']:.2f}%")
        print(f"  Recovery average: {recovery_stats['avg']:.2f}%")
        if baseline_stats['avg'] > 0:
            print(f"  Recovery ratio: {recovery_stats['avg'] / baseline_stats['avg']:.2f}")
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_base_engine_long_running_stability(self, base_engine, engine_cleanup):
        """Test CPU usage stability over a longer period"""
        # Register engine for cleanup
        engine_cleanup(base_engine)
        
        current_process = psutil.Process()
        
        # Monitor CPU usage over a longer period
        long_term_stats = self.monitor_cpu_usage(current_process, duration=15.0, interval=1.0)
        
        # Verify long-term stability
        assert long_term_stats['max'] - long_term_stats['min'] < 30.0, \
            f"CPU usage too volatile: range {long_term_stats['max'] - long_term_stats['min']}%"
        
        # Check for any extreme outliers
        readings = long_term_stats['readings']
        if readings:
            mean = sum(readings) / len(readings)
            outliers = [r for r in readings if abs(r - mean) > mean * 2]
            assert len(outliers) < len(readings) * 0.1, \
                f"Too many CPU usage outliers: {len(outliers)} out of {len(readings)}"
        
        print(f"\nLong-term Stability Test:")
        print(f"  Duration: {long_term_stats['duration']:.1f} seconds")
        print(f"  Average: {long_term_stats['avg']:.2f}%")
        print(f"  Min: {long_term_stats['min']:.2f}%")
        print(f"  Max: {long_term_stats['max']:.2f}%")
        print(f"  Range: {long_term_stats['max'] - long_term_stats['min']:.2f}%")
        print(f"  Outliers: {len(outliers) if 'outliers' in locals() else 0}")
    
    def test_base_engine_cleanup_cpu_usage(self, base_engine, engine_cleanup):
        """Test that CPU usage returns to normal after engine cleanup"""
        # Register engine for cleanup
        engine_cleanup(base_engine)
        
        current_process = psutil.Process()
        
        # Get CPU usage before cleanup
        before_cleanup = self.get_process_cpu_percent(current_process, 1.0)
        
        # Perform cleanup
        base_engine.stop_all()
        
        # Wait a moment for cleanup to complete
        time.sleep(1.0)
        
        # Get CPU usage after cleanup
        after_cleanup = self.get_process_cpu_percent(current_process, 1.0)
        
        # Verify cleanup doesn't cause excessive CPU usage
        assert after_cleanup < 20.0, f"CPU usage after cleanup too high: {after_cleanup}%"
        
        print(f"\nCleanup CPU Usage:")
        print(f"  Before cleanup: {before_cleanup:.2f}%")
        print(f"  After cleanup: {after_cleanup:.2f}%")
        print(f"  Difference: {after_cleanup - before_cleanup:.2f}%")
