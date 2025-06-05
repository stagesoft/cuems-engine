#!/usr/bin/env python3

import os
import signal
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from cuemsengine.NodeEngine import NodeEngine
from cuemsengine.ControllerEngine import ControllerEngine
from cuemsengine.core.daemon import run_daemon
from cuemsutils.log import Logger

@pytest.fixture
def pid_dir(tmp_path):
    """Create temporary PID directory"""
    pid_dir = tmp_path / 'cuems_test'
    pid_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir

@pytest.fixture
def log_dir(tmp_path):
    """Create temporary log directory"""
    log_dir = tmp_path / 'cuems_test' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir

@pytest.fixture
def mock_daemon():
    """Mock daemon context"""
    with patch('daemon.DaemonContext') as mock:
        mock_context = MagicMock()
        mock.return_value.__enter__.return_value = mock_context
        yield mock

@pytest.fixture
def mock_config_path():
    """Mock ConfigManager to use test XML files"""
    test_conf_path = Path(__file__).parent / '..' / 'dev' / 'test_xml_files'
    
    def mock_conf_path(file):
        return test_conf_path / file
        
    with patch('cuemsengine.tools.ConfigManager.ConfigManager.conf_path', 
               side_effect=mock_conf_path):
        yield test_conf_path

def test_node_engine_deployment(pid_dir, log_dir, mock_daemon, mock_config_path):
    """Test NodeEngine can be deployed as daemon"""
    engine = NodeEngine()
    run_daemon(engine, 'node_engine')
    
    # Verify daemon context was created with correct parameters
    mock_daemon.assert_called_once()
    call_args = mock_daemon.call_args[1]
    assert call_args['pidfile'] == Path('/var/run/cuems/node_engine.pid')
    assert call_args['working_directory'] == '/'
    assert call_args['umask'] == 0o002

def test_controller_engine_deployment(pid_dir, log_dir, mock_daemon, mock_config_path):
    """Test ControllerEngine can be deployed as daemon"""
    engine = ControllerEngine()
    run_daemon(engine, 'controller_engine')
    
    # Verify daemon context was created with correct parameters
    mock_daemon.assert_called_once()
    call_args = mock_daemon.call_args[1]
    assert call_args['pidfile'] == Path('/var/run/cuems/controller_engine.pid')
    assert call_args['working_directory'] == '/'
    assert call_args['umask'] == 0o002

def test_engine_signal_handling(pid_dir, log_dir, mock_daemon, mock_config_path):
    """Test engines handle signals properly"""
    engine = NodeEngine()
    
    with patch.object(engine, 'stop') as mock_stop:
        run_daemon(engine, 'node_engine')
        engine.handle_terminate(signal.SIGTERM, None)
        mock_stop.assert_called_once()

def test_engine_error_handling(pid_dir, log_dir, mock_daemon, mock_config_path):
    """Test engines handle errors properly"""
    engine = NodeEngine()
    
    with patch.object(engine, 'run', side_effect=Exception('Test error')):
        with pytest.raises(SystemExit) as exc_info:
            run_daemon(engine, 'node_engine')
        assert exc_info.value.code == 1

def test_engine_pid_file_creation(pid_dir, log_dir, mock_daemon, mock_config_path):
    """Test PID file is created and contains correct PID"""
    engine = NodeEngine()
    
    with patch('pathlib.Path.mkdir') as mock_mkdir:
        run_daemon(engine, 'node_engine')
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
