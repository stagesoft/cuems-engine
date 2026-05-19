# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>

"""Unit tests for CuemsDeploy.

Covers:
- controller_ip direct path (preferred)
- hostname + avahi fallback path (legacy)
- disabled state when no IP is available
- stream supervision: startup-deadline + inactivity watchdogs
- rsync command flags
- log file path defaults
- on_progress callback wiring
- _parse_progress shape
"""

import selectors
import subprocess
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cuemsengine.tools.CuemsDeploy import CuemsDeploy


# ─────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────


class _FakeStream:
    """File-object-ish wrapper with a stable fileno()."""
    def __init__(self, fd: int):
        self._fd = fd
    def fileno(self) -> int:
        return self._fd


class _ScriptedSelector:
    """Drop-in replacement for selectors.DefaultSelector for tests.

    events is a list of (action, payload) tuples processed in order:
       ('select', [fd, ...])  → .select() returns READ events for fds
       ('select', [])         → .select() returns [] (watchdog fires)
    """
    def __init__(self, events):
        self._events = list(events)
        self._registered = {}  # fileobj → (fd, data)

    def register(self, fileobj, _evt, data):
        self._registered[fileobj] = (fileobj.fileno(), data)

    def unregister(self, fileobj):
        self._registered.pop(fileobj, None)

    def get_map(self):
        return self._registered

    def select(self, timeout=None):
        if not self._events:
            return []
        action, payload = self._events.pop(0)
        assert action == 'select', action
        keys = []
        for fd in payload:
            fileobj = next(
                fo for fo, (fdv, _) in self._registered.items() if fdv == fd
            )
            _, data = self._registered[fileobj]
            keys.append((
                SimpleNamespace(fd=fd, fileobj=fileobj, data=data),
                selectors.EVENT_READ,
            ))
        return keys

    def close(self):
        pass


def _make_proc(rc: int, stdout_fd: int = 100, stderr_fd: int = 101):
    """Build a Popen-shaped mock whose pipes have stable fds."""
    proc = MagicMock()
    proc.stdout = _FakeStream(stdout_fd)
    proc.stderr = _FakeStream(stderr_fd)
    # poll() returns None until wait() has been called; then returns rc
    proc._returncode = None
    def _wait(timeout=None):
        proc._returncode = rc
        return rc
    proc.wait.side_effect = _wait
    proc.poll.side_effect = lambda: proc._returncode
    proc.terminate.return_value = None
    proc.kill.return_value = None
    return proc


def _scripted_os_read(fd_chunks: dict[int, deque]):
    """Build an os.read patch backed by per-fd chunk deques."""
    def _read(fd, _n):
        q = fd_chunks.get(fd)
        if q is None or not q:
            return b''
        return q.popleft()
    return _read


def _shrink_watchdogs(monkeypatch, startup=0.05, inactivity=0.05):
    """Speed up tests so watchdog branches fire promptly."""
    import cuemsengine.tools.CuemsDeploy as mod
    monkeypatch.setattr(mod, '_STARTUP_DEADLINE_S', startup)
    monkeypatch.setattr(mod, '_INACTIVITY_S', inactivity)


# ─────────────────────────────────────────────────────────────────────────
# Constructor / addressing
# ─────────────────────────────────────────────────────────────────────────


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
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.Popen') as mock_popen:
        result = d.sync_files('proj', 'project')
        assert result is False
        mock_popen.assert_not_called()


def test_sync_files_fails_fast_when_project_mandatory_file_missing():
    """Option A: pre-check mandatory paths, then skip rsync transfer if absent."""
    d = CuemsDeploy(controller_ip='10.0.0.1')
    with patch.object(d, '_check_mandatory_sources', return_value=(False, [
        '/projects/proj/script.xml'
    ])) as check_mandatory, \
         patch.object(d, '_sync') as sync_mock:
        result = d.sync_files('proj', 'project')

    assert result is False
    check_mandatory.assert_called_once()
    sync_mock.assert_not_called()
    assert any('mandatory project files are missing' in e for e in d.errors), d.errors


def test_sync_files_project_does_single_sync_after_mandatory_precheck():
    """Option A keeps one transfer process after mandatory checks pass."""
    d = CuemsDeploy(controller_ip='10.0.0.1')
    with patch.object(d, '_check_mandatory_sources', return_value=(True, [])) as check_mandatory, \
         patch.object(d, '_sync', return_value=True) as sync_mock:
        result = d.sync_files('proj', 'project')

    assert result is True
    check_mandatory.assert_called_once()
    sync_mock.assert_called_once()


def test_check_mandatory_sources_probes_once_for_all_paths():
    """Mandatory precheck should run one probe with the full path set."""
    d = CuemsDeploy(controller_ip='10.0.0.1')
    run_result = SimpleNamespace(returncode=0, stderr=b'')
    mandatory_paths = [
        '/projects/proj/script.xml',
        '/projects/proj/settings.xml',
    ]
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.run',
               return_value=run_result) as run_mock:
        ok, missing = d._check_mandatory_sources(mandatory_paths)

    assert ok is True
    assert missing == []
    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd[0] == 'rsync'
    assert '-r' in cmd
    assert '--list-only' in cmd
    assert any(str(part).startswith('--files-from=') for part in cmd)


def test_check_mandatory_sources_extracts_missing_subset():
    """Missing paths are extracted from a single probe stderr payload."""
    d = CuemsDeploy(controller_ip='10.0.0.1')
    stderr = (
        b'rsync: [sender] link_stat "/projects/proj/settings.xml" failed: '
        b'No such file or directory (2)\n'
    )
    run_result = SimpleNamespace(returncode=23, stderr=stderr)
    mandatory_paths = [
        '/projects/proj/script.xml',
        '/projects/proj/settings.xml',
    ]
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.run',
               return_value=run_result):
        ok, missing = d._check_mandatory_sources(mandatory_paths)

    assert ok is False
    assert missing == ['/projects/proj/settings.xml']


def test_default_log_file_is_under_run_cuems():
    """Log file moved out of /tmp to avoid cross-uid ownership conflicts."""
    d = CuemsDeploy(controller_ip='10.0.0.1')
    assert d.log_file.startswith('/run/cuems/'), \
        f'expected /run/cuems/ prefix, got {d.log_file!r}'


# ─────────────────────────────────────────────────────────────────────────
# Rsync command flags
# ─────────────────────────────────────────────────────────────────────────


def test_sync_command_includes_supervision_flags(deploy, tmp_path):
    """rsync must be invoked with the stream-supervision flag set."""
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    proc = _make_proc(rc=0)
    # Immediately EOF both pipes → loop exits → wait() returns 0
    selector = _ScriptedSelector([
        ('select', [proc.stdout.fileno(), proc.stderr.fileno()]),
    ])
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.Popen',
               return_value=proc) as mock_popen, \
         patch('cuemsengine.tools.CuemsDeploy.selectors.DefaultSelector',
               return_value=selector), \
         patch('cuemsengine.tools.CuemsDeploy.fcntl.fcntl'), \
         patch('cuemsengine.tools.CuemsDeploy.os.read',
               side_effect=_scripted_os_read({
                   proc.stdout.fileno(): deque([b'']),
                   proc.stderr.fileno(): deque([b'']),
               })):
        deploy._sync(str(log_file))

    args, _ = mock_popen.call_args
    cmd = args[0]
    assert cmd[0] == 'rsync'
    # rsync's own per-syscall inactivity guard is the primary kill switch.
    assert '--contimeout=2' in cmd
    assert '--timeout=5' in cmd
    # Tolerate missing files on the source (script.xml-only projects).
    assert '--ignore-missing-args' in cmd
    # Stream supervision: progress2 + suppressed per-file names.
    assert '--info=progress2,name0' in cmd
    # We dropped the -q (quiet) flag in favour of streaming.
    assert '-rq' not in cmd
    assert '-q' not in cmd


# ─────────────────────────────────────────────────────────────────────────
# Watchdog paths
# ─────────────────────────────────────────────────────────────────────────


def test_sync_startup_deadline_fires_with_no_output(deploy, tmp_path, monkeypatch):
    """If rsync produces zero output before the startup deadline, kill it
    and surface a clean error — the original 'pre-fork hang' case."""
    _shrink_watchdogs(monkeypatch)
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    proc = _make_proc(rc=0)
    # Selector returns [] every time → startup deadline expires.
    selector = _ScriptedSelector([
        ('select', []),
        ('select', []),
        ('select', []),
    ])
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.Popen',
               return_value=proc), \
         patch('cuemsengine.tools.CuemsDeploy.selectors.DefaultSelector',
               return_value=selector), \
         patch('cuemsengine.tools.CuemsDeploy.fcntl.fcntl'), \
         patch('cuemsengine.tools.CuemsDeploy.os.read', return_value=b''):
        result = deploy._sync(str(log_file))

    assert result is False
    assert any('startup deadline' in e for e in deploy.errors), deploy.errors
    proc.terminate.assert_called()


def test_sync_inactivity_threshold_fires_after_started(deploy, tmp_path, monkeypatch):
    """Post-startup wedge: rsync emits one chunk, then nothing. Watchdog
    must kick in with the inactivity message (not the startup one)."""
    _shrink_watchdogs(monkeypatch)
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    proc = _make_proc(rc=0)
    out_fd = proc.stdout.fileno()
    err_fd = proc.stderr.fileno()
    selector = _ScriptedSelector([
        ('select', [out_fd]),    # one progress chunk
        ('select', []),          # nothing → inactivity fires
        ('select', []),
    ])
    fd_chunks = {
        out_fd: deque([b'         1,024   0%    0.00kB/s    0:00:00\r']),
        err_fd: deque([b'']),
    }
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.Popen',
               return_value=proc), \
         patch('cuemsengine.tools.CuemsDeploy.selectors.DefaultSelector',
               return_value=selector), \
         patch('cuemsengine.tools.CuemsDeploy.fcntl.fcntl'), \
         patch('cuemsengine.tools.CuemsDeploy.os.read',
               side_effect=_scripted_os_read(fd_chunks)):
        result = deploy._sync(str(log_file))

    assert result is False
    assert any('inactivity threshold' in e for e in deploy.errors), deploy.errors


# ─────────────────────────────────────────────────────────────────────────
# Error-exit paths
# ─────────────────────────────────────────────────────────────────────────


def test_sync_handles_rsync_error_exit(deploy, tmp_path):
    """A non-zero rsync exit must produce False with captured stderr,
    and the positional 'rsync error: ...' trailer must be stripped."""
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    proc = _make_proc(rc=10)
    out_fd = proc.stdout.fileno()
    err_fd = proc.stderr.fileno()
    selector = _ScriptedSelector([
        ('select', [err_fd]),                    # stderr message
        ('select', [out_fd, err_fd]),            # both EOF
    ])
    fd_chunks = {
        out_fd: deque([b'']),
        err_fd: deque([
            b'rsync: connection refused\nrsync error: foo at main.c(123)\n',
            b'',
        ]),
    }
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.Popen',
               return_value=proc), \
         patch('cuemsengine.tools.CuemsDeploy.selectors.DefaultSelector',
               return_value=selector), \
         patch('cuemsengine.tools.CuemsDeploy.fcntl.fcntl'), \
         patch('cuemsengine.tools.CuemsDeploy.os.read',
               side_effect=_scripted_os_read(fd_chunks)):
        result = deploy._sync(str(log_file))

    assert result is False
    assert any('connection refused' in e for e in deploy.errors), deploy.errors
    # Trailer dropped: no "rsync error:" line should remain.
    assert not any('rsync error:' in e for e in deploy.errors), deploy.errors


def test_sync_handles_empty_stderr(deploy, tmp_path):
    """Defensive: rsync may exit non-zero without any stderr at all."""
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    proc = _make_proc(rc=1)
    out_fd = proc.stdout.fileno()
    err_fd = proc.stderr.fileno()
    selector = _ScriptedSelector([
        ('select', [out_fd, err_fd]),            # both EOF immediately
    ])
    fd_chunks = {out_fd: deque([b'']), err_fd: deque([b''])}
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.Popen',
               return_value=proc), \
         patch('cuemsengine.tools.CuemsDeploy.selectors.DefaultSelector',
               return_value=selector), \
         patch('cuemsengine.tools.CuemsDeploy.fcntl.fcntl'), \
         patch('cuemsengine.tools.CuemsDeploy.os.read',
               side_effect=_scripted_os_read(fd_chunks)):
        result = deploy._sync(str(log_file))

    assert result is False
    assert deploy.errors == []


# ─────────────────────────────────────────────────────────────────────────
# on_progress callback
# ─────────────────────────────────────────────────────────────────────────


def test_sync_fires_on_progress_for_progress2_lines(tmp_path):
    """on_progress receives a structured dict for each progress2 update."""
    cb = MagicMock()
    d = CuemsDeploy(controller_ip='10.0.0.1', on_progress=cb)
    log_file = tmp_path / 'rsync_request.log'
    log_file.write_text('')

    proc = _make_proc(rc=0)
    out_fd = proc.stdout.fileno()
    err_fd = proc.stderr.fileno()
    selector = _ScriptedSelector([
        ('select', [out_fd]),
        ('select', [out_fd, err_fd]),
    ])
    # A real-shape progress2 line, \r-terminated.
    progress = (
        b'  2,147,483,648 100%  118.34MB/s    0:00:17 '
        b'(xfr#3, to-chk=0/3)\r'
    )
    fd_chunks = {
        out_fd: deque([progress, b'']),
        err_fd: deque([b'']),
    }
    with patch('cuemsengine.tools.CuemsDeploy.subprocess.Popen',
               return_value=proc), \
         patch('cuemsengine.tools.CuemsDeploy.selectors.DefaultSelector',
               return_value=selector), \
         patch('cuemsengine.tools.CuemsDeploy.fcntl.fcntl'), \
         patch('cuemsengine.tools.CuemsDeploy.os.read',
               side_effect=_scripted_os_read(fd_chunks)):
        result = d._sync(str(log_file))

    assert result is True
    assert cb.call_count == 1
    parsed = cb.call_args[0][0]
    assert parsed['bytes'] == 2_147_483_648
    assert parsed['pct'] == 100
    assert parsed['rate'] == '118.34MB/s'
    assert parsed['eta'] == '0:00:17'
    assert parsed['xfr'] == 3
    assert parsed['remaining'] == 0
    assert parsed['total'] == 3


# ─────────────────────────────────────────────────────────────────────────
# _parse_progress unit tests
# ─────────────────────────────────────────────────────────────────────────


def test_parse_progress_basic_line(deploy):
    parsed = deploy._parse_progress(
        '         32,768   0%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)'
    )
    assert parsed['bytes'] == 32_768
    assert parsed['pct'] == 0
    assert parsed['rate'] == '0.00kB/s'
    assert parsed['eta'] == '0:00:00'
    assert parsed['xfr'] == 1
    assert parsed['remaining'] == 0
    assert parsed['total'] == 1


def test_parse_progress_without_xfr_suffix(deploy):
    parsed = deploy._parse_progress(
        '         32,768   5%    1.50MB/s    0:00:10'
    )
    assert parsed['bytes'] == 32_768
    assert parsed['pct'] == 5
    assert 'xfr' not in parsed


@pytest.mark.parametrize('line', [
    '',
    'Number of files: 1',                      # stats line
    'sending incremental file list',
    'projects/foo/script.xml',                  # file path
    'total size is 1,234  speedup is 1.00',
])
def test_parse_progress_returns_empty_for_non_progress_lines(deploy, line):
    assert deploy._parse_progress(line) == {}
