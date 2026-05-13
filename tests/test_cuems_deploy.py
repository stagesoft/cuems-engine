# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Unit tests for CuemsDeploy.

Covers:
- controller_ip direct path (preferred)
- hostname + avahi fallback path (legacy)
- disabled state when no IP is available
- timeout handling (connect + I/O + subprocess.run backstop)
- rsync command flags
- log file path defaults
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from cuemsengine.tools.CuemsDeploy import CuemsDeploy


@pytest.fixture
def deploy():
    """Default-enabled deploy manager with a valid controller IP."""
    return CuemsDeploy(controller_ip='10.0.0.1')


def test_constructor_with_controller_ip_is_enabled():
    d = CuemsDeploy(controller_ip='10.0.0.1')
    assert d.enabled is True
    assert d.main_ip == '10.0.0.1'
    assert d.address == 'rsync://cuems_library_rsync@10.0.0.1/cuems'


def test_constructor_with_none_ip_is_disabled():
    d = CuemsDeploy(controller_ip=None)
    assert d.enabled is False
    assert d.main_ip is None
    assert d.address is None


def test_constructor_with_false_is_disabled():
    """Regression: avahi-resolve used to return literal False on failure,
    constructing URL 'rsync://...@False/cuems'. Verify we no longer build
    a URL from a falsy value."""
    d = CuemsDeploy(controller_ip=False)
    assert d.enabled is False
    assert d.address is None


def test_constructor_with_empty_string_is_disabled():
    d = CuemsDeploy(controller_ip='')
    assert d.enabled is False
    assert d.address is None


def test_constructor_with_hostname_falls_back_to_avahi():
    with patch.object(CuemsDeploy, '_avahi_resolve', return_value='192.168.1.10'):
        d = CuemsDeploy(controller_ip=None, hostname='controller.local')
        assert d.enabled is True
        assert d.main_ip == '192.168.1.10'


def test_constructor_hostname_avahi_failure_is_disabled():
    with patch.object(CuemsDeploy, '_avahi_resolve', return_value=None):
        d = CuemsDeploy(controller_ip=None, hostname='nonexistent.local')
        assert d.enabled is False


def test_controller_ip_takes_precedence_over_hostname():
    """controller_ip is the preferred path; hostname must not be resolved
    when controller_ip is provided (avoids unnecessary avahi calls)."""
    with patch.object(CuemsDeploy, '_avahi_resolve') as mock_resolve:
        d = CuemsDeploy(controller_ip='10.0.0.1', hostname='controller.local')
        assert d.main_ip == '10.0.0.1'
        mock_resolve.assert_not_called()


def test_sync_files_returns_false_when_disabled():
    """Disabled manager must not invoke rsync."""
    d = CuemsDeploy(controller_ip=None)
    with patch('subprocess.run') as mock_run:
        result = d.sync_files('proj', 'project')
        assert result is False
        mock_run.assert_not_called()


def test_sync_command_includes_timeout_flags(deploy, tmp_path):
    """Both --contimeout and --timeout must be passed to rsync."""
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    with patch('subprocess.run') as mock_run:
        completed = MagicMock()
        completed.check_returncode = MagicMock()
        completed.stderr = b''
        mock_run.return_value = completed

        deploy._sync(str(log_file))

        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert '--contimeout=2' in cmd
        assert '--timeout=5' in cmd
        # Tolerate missing files on the source (script.xml-only projects).
        assert '--ignore-missing-args' in cmd
        # Python-level backstop
        assert kwargs.get('timeout') == 15


def test_sync_handles_subprocess_timeout(deploy, tmp_path):
    """If rsync hangs past 15s, subprocess.TimeoutExpired must be caught
    and translated into a clean False."""
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='rsync', timeout=15)):
        result = deploy._sync(str(log_file))
        assert result is False
        assert any('timed out' in e for e in deploy.errors)


def test_sync_handles_rsync_error_exit(deploy, tmp_path):
    """A non-zero rsync exit must produce False with captured stderr."""
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    err = subprocess.CalledProcessError(
        returncode=10, cmd='rsync',
        stderr=b'rsync: connection refused\nrsync: error final\n',
    )
    with patch('subprocess.run', side_effect=err):
        result = deploy._sync(str(log_file))
        assert result is False
        assert any('connection refused' in e for e in deploy.errors)


def test_sync_handles_empty_stderr(deploy, tmp_path):
    """Defensive: stderr may be empty (no trailing line to pop)."""
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    err = subprocess.CalledProcessError(returncode=1, cmd='rsync', stderr=b'')
    with patch('subprocess.run', side_effect=err):
        result = deploy._sync(str(log_file))
        assert result is False


def test_default_log_file_is_under_run_cuems():
    """Log file moved out of /tmp to avoid cross-uid ownership conflicts."""
    d = CuemsDeploy(controller_ip='10.0.0.1')
    assert d.log_file.startswith('/run/cuems/'), \
        f'expected /run/cuems/ prefix, got {d.log_file!r}'
