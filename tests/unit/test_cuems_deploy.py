# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

"""Unit tests for CuemsDeploy.

Covers:
- controller_ip direct path (preferred)
- hostname + avahi fallback path (legacy)
- disabled state when no IP is available
- loop guard (loop not yet bound)
- async watchdog state machine: startup deadline + inactivity threshold
- rsync command flags
- log file path defaults
- on_progress callback wiring
- _parse_progress shape
- async coroutine shapes (post-refactor)
- run_coroutine_threadsafe sync bridge
- _RSYNC_PASSWORD class constant
- _media_files path expansion
"""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cuemsengine.tools.CuemsDeploy import CuemsDeploy


# anyio: restrict to asyncio backend (trio is not installed in this project)
@pytest.fixture
def anyio_backend():
    return "asyncio"


# ─────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────


def _make_stream_reader(chunks):
    """
    Wrap a list of bytes chunks into an async-readable mock stream (T005).
    """
    reader = MagicMock()
    q = iter(chunks)

    async def _read(n):
        return next(q, b"")

    reader.read = _read
    return reader


def _make_async_proc(rc, stdout_chunks, stderr_chunks):
    """Build an asyncio.create_subprocess_exec-shaped mock (T004)."""
    proc = MagicMock()
    proc.returncode = None
    proc.stdout = _make_stream_reader(stdout_chunks)
    proc.stderr = _make_stream_reader(stderr_chunks)

    async def _wait():
        proc.returncode = rc
        return rc

    proc.wait = _wait
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


def _shrink_watchdogs(monkeypatch, startup=0.05, inactivity=0.05):
    """Speed up tests so watchdog branches fire promptly."""
    import cuemsengine.tools.CuemsDeploy as mod

    monkeypatch.setattr(mod, "_STARTUP_DEADLINE_S", startup)
    monkeypatch.setattr(mod, "_INACTIVITY_S", inactivity)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def deploy():
    """Default-enabled deploy manager with a valid controller IP."""
    return CuemsDeploy(controller_ip="10.0.0.1")


@pytest.fixture
def deploy_with_loop():
    """
    Deploy manager with a real background event loop for sync bridge tests.
    """
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    d = CuemsDeploy(controller_ip="10.0.0.1", loop=loop, is_async=True)
    yield d
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)


# ─────────────────────────────────────────────────────────────────────────
# Constructor / addressing
# ─────────────────────────────────────────────────────────────────────────


def test_constructor_with_controller_ip_is_enabled():
    d = CuemsDeploy(controller_ip="10.0.0.1")
    assert d.enabled is True
    assert d.main_ip == "10.0.0.1"
    assert d.address == "rsync://cuems_library_rsync@10.0.0.1/cuems"


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
    d = CuemsDeploy(controller_ip="")
    assert d.enabled is False
    assert d.address is None


def test_constructor_with_hostname_falls_back_to_avahi():
    with patch.object(CuemsDeploy, "_avahi_resolve", return_value="192.168.1.10"):
        d = CuemsDeploy(controller_ip=None, hostname="controller.local")
        assert d.enabled is True
        assert d.main_ip == "192.168.1.10"


def test_constructor_hostname_avahi_failure_is_disabled():
    with patch.object(CuemsDeploy, "_avahi_resolve", return_value=None):
        d = CuemsDeploy(controller_ip=None, hostname="nonexistent.local")
        assert d.enabled is False


def test_controller_ip_takes_precedence_over_hostname():
    """controller_ip is the preferred path; hostname must not be resolved
    when controller_ip is provided (avoids unnecessary avahi calls)."""
    with patch.object(CuemsDeploy, "_avahi_resolve") as mock_resolve:
        d = CuemsDeploy(controller_ip="10.0.0.1", hostname="controller.local")
        assert d.main_ip == "10.0.0.1"
        mock_resolve.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────
# sync_files: disabled and loop-guard paths
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_returns_false_when_disabled():
    """Disabled manager must not invoke rsync — disabled check fires before
    any subprocess call or loop check."""
    d = CuemsDeploy(controller_ip=None)
    result = d.sync_files("proj", "project")
    assert result is False


def test_sync_files_fails_fast_when_project_mandatory_file_missing(
    deploy_with_loop,
):
    """
    Option A: pre-check mandatory paths, then skip rsync transfer if absent.
    """
    d = deploy_with_loop
    with (
        patch.object(
            d,
            "_check_mandatory_sources",
            new_callable=AsyncMock,
            return_value=(False, ["/projects/proj/script.xml"]),
        ) as check_mandatory,
        patch.object(
            d,
            "_sync",
            new_callable=AsyncMock,
            return_value=True,
        ) as sync_mock,
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d.sync_files("proj", "project")

    assert result is False
    check_mandatory.assert_called_once()
    sync_mock.assert_not_called()
    assert any("mandatory project files are missing" in e for e in d.errors), d.errors


def test_sync_files_project_does_single_sync_after_mandatory_precheck(
    deploy_with_loop,
):
    """Option A keeps one transfer process after mandatory checks pass."""
    d = deploy_with_loop
    with (
        patch.object(
            d,
            "_check_mandatory_sources",
            new_callable=AsyncMock,
            return_value=(True, []),
        ) as check_mandatory,
        patch.object(
            d,
            "_sync",
            new_callable=AsyncMock,
            return_value=True,
        ) as sync_mock,
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d.sync_files("proj", "project")

    assert result is True
    check_mandatory.assert_called_once()
    sync_mock.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# _check_mandatory_sources (async)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_check_mandatory_sources_probes_once_for_all_paths():
    """Mandatory precheck should run one probe with the full path set."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    mandatory_paths = [
        "/projects/proj/script.xml",
        "/projects/proj/settings.xml",
    ]
    proc = MagicMock()
    proc.returncode = 0

    async def _communicate():
        return b"", b""

    proc.communicate = _communicate

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ) as mock_exec:
        ok, missing = await d._check_mandatory_sources(mandatory_paths)

    assert ok is True
    assert missing == []
    mock_exec.assert_called_once()
    args = mock_exec.call_args.args
    assert args[0] == "rsync"
    assert "-r" in args
    assert "--list-only" in args
    assert any(str(a).startswith("--files-from=") for a in args)


@pytest.mark.anyio
async def test_check_mandatory_sources_extracts_missing_subset():
    """Missing paths are extracted from a single probe stderr payload."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    stderr = (
        b'rsync: [sender] link_stat "/projects/proj/settings.xml" failed: '
        b"No such file or directory (2)\n"
    )
    proc = MagicMock()
    proc.returncode = 23

    async def _communicate():
        return b"", stderr

    proc.communicate = _communicate

    with patch(
        "asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
        return_value=proc,
    ):
        ok, missing = await d._check_mandatory_sources(
            [
                "/projects/proj/script.xml",
                "/projects/proj/settings.xml",
            ]
        )

    assert ok is False
    assert missing == ["/projects/proj/settings.xml"]


# ─────────────────────────────────────────────────────────────────────────
# Log file path
# ─────────────────────────────────────────────────────────────────────────


def test_default_log_file_is_under_run_cuems():
    """Log file moved out of /tmp to avoid cross-uid ownership conflicts."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    assert d.log_file.startswith(
        "/run/cuems/"
    ), f"expected /run/cuems/ prefix, got {d.log_file!r}"


# ─────────────────────────────────────────────────────────────────────────
# Rsync command flags
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sync_command_includes_supervision_flags(tmp_path):
    """rsync must be invoked with the stream-supervision flag set."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    proc = _make_async_proc(rc=0, stdout_chunks=[b""], stderr_chunks=[b""])
    captured = []

    async def _capture(*args, **kwargs):
        captured.extend(args)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=_capture):
        await d._sync(str(log_file))

    assert captured[0] == "rsync"
    assert "--contimeout=2" in captured
    assert "--timeout=5" in captured
    assert "--ignore-missing-args" in captured
    assert "--info=progress2,name0" in captured
    assert "-rq" not in captured
    assert "-q" not in captured


# ─────────────────────────────────────────────────────────────────────────
# Watchdog paths
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sync_startup_deadline_fires_with_no_output(tmp_path, monkeypatch):
    """If rsync produces zero output before the startup deadline, kill it
    and surface a clean error — the original 'pre-fork hang' case (T011)."""
    _shrink_watchdogs(monkeypatch)
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    async def _hanging_read(n):
        await asyncio.sleep(100)
        return b""

    proc = MagicMock()
    proc.returncode = None
    proc.stdout = MagicMock()
    proc.stdout.read = _hanging_read
    proc.stderr = MagicMock()
    proc.stderr.read = _hanging_read

    async def _wait():
        proc.returncode = 0
        return 0

    proc.wait = _wait
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await d._sync(str(log_file))

    assert result is False
    assert any("startup deadline" in e for e in d.errors), d.errors
    proc.terminate.assert_called()


@pytest.mark.anyio
async def test_sync_inactivity_threshold_fires_after_started(tmp_path, monkeypatch):
    """Post-startup wedge: rsync emits one chunk, then nothing. Watchdog
    must kick in with the inactivity message (T012)."""
    _shrink_watchdogs(monkeypatch)
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    stdout_source = iter([b"  1,024   0%    0.00kB/s    0:00:00\r"])

    async def _read_stdout(n):
        chunk = next(stdout_source, None)
        if chunk is not None:
            return chunk
        await asyncio.sleep(100)
        return b""

    async def _hanging_read(n):
        await asyncio.sleep(100)
        return b""

    proc = MagicMock()
    proc.returncode = None
    proc.stdout = MagicMock()
    proc.stdout.read = _read_stdout
    proc.stderr = MagicMock()
    proc.stderr.read = _hanging_read

    async def _wait():
        proc.returncode = 0
        return 0

    proc.wait = _wait
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await d._sync(str(log_file))

    assert result is False
    assert any("inactivity threshold" in e for e in d.errors), d.errors


# ─────────────────────────────────────────────────────────────────────────
# Error-exit paths
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sync_handles_rsync_error_exit(tmp_path):
    """A non-zero rsync exit must produce False with captured stderr,
    and the positional 'rsync error: ...' trailer must be stripped."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    proc = _make_async_proc(
        rc=10,
        stdout_chunks=[b""],
        stderr_chunks=[b"rsync: connection refused\nrsync error: foo at main.c(123)\n"],
    )
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await d._sync(str(log_file))

    assert result is False
    assert any("connection refused" in e for e in d.errors), d.errors
    assert not any("rsync error:" in e for e in d.errors), d.errors


@pytest.mark.anyio
async def test_sync_handles_empty_stderr(tmp_path):
    """Defensive: rsync may exit non-zero without any stderr at all."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    proc = _make_async_proc(rc=1, stdout_chunks=[b""], stderr_chunks=[b""])
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await d._sync(str(log_file))

    assert result is False
    assert d.errors == []


# ─────────────────────────────────────────────────────────────────────────
# on_progress callback
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sync_fires_on_progress_for_progress2_lines(tmp_path):
    """on_progress receives a structured dict for each progress2 update."""
    cb = MagicMock()
    d = CuemsDeploy(controller_ip="10.0.0.1", on_progress=cb)
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    progress = b"  2,147,483,648 100%  118.34MB/s    0:00:17 " b"(xfr#3, to-chk=0/3)\r"
    proc = _make_async_proc(
        rc=0,
        stdout_chunks=[progress, b""],
        stderr_chunks=[b""],
    )
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await d._sync(str(log_file))

    assert result is True
    assert cb.call_count == 1
    parsed = cb.call_args[0][0]
    assert parsed["bytes"] == 2_147_483_648
    assert parsed["pct"] == 100
    assert parsed["rate"] == "118.34MB/s"
    assert parsed["eta"] == "0:00:17"
    assert parsed["xfr"] == 3
    assert parsed["remaining"] == 0
    assert parsed["total"] == 3


# ─────────────────────────────────────────────────────────────────────────
# _parse_progress unit tests
# ─────────────────────────────────────────────────────────────────────────


def test_parse_progress_basic_line(deploy):
    parsed = deploy._parse_progress(
        "         32,768   0%    0.00kB/s    0:00:00 (xfr#1, to-chk=0/1)"
    )
    assert parsed["bytes"] == 32_768
    assert parsed["pct"] == 0
    assert parsed["rate"] == "0.00kB/s"
    assert parsed["eta"] == "0:00:00"
    assert parsed["xfr"] == 1
    assert parsed["remaining"] == 0
    assert parsed["total"] == 1


def test_parse_progress_without_xfr_suffix(deploy):
    parsed = deploy._parse_progress("         32,768   5%    1.50MB/s    0:00:10")
    assert parsed["bytes"] == 32_768
    assert parsed["pct"] == 5
    assert "xfr" not in parsed


@pytest.mark.parametrize(
    "line",
    [
        "",
        "Number of files: 1",  # stats line
        "sending incremental file list",
        "projects/foo/script.xml",  # file path
        "total size is 1,234  speedup is 1.00",
    ],
)
def test_parse_progress_returns_empty_for_non_progress_lines(deploy, line):
    assert deploy._parse_progress(line) == {}


# ─────────────────────────────────────────────────────────────────────────
# Phase 2: US3 — _RSYNC_PASSWORD class constant (T003)
# ─────────────────────────────────────────────────────────────────────────


def test_rsync_password_constant_defined():
    """_RSYNC_PASSWORD must be a ClassVar on CuemsDeploy with the correct value
    and the literal must appear exactly once in the module source."""
    import inspect

    assert hasattr(
        CuemsDeploy, "_RSYNC_PASSWORD"
    ), "CuemsDeploy must have a _RSYNC_PASSWORD class attribute"
    assert CuemsDeploy._RSYNC_PASSWORD == "f48t5eL2kLHw2Wfw"
    source = inspect.getsource(CuemsDeploy)
    count = source.count("f48t5eL2kLHw2Wfw")
    assert (
        count == 1
    ), f"Password literal must appear exactly once in source; got {count}"


# ─────────────────────────────────────────────────────────────────────────
# Phase 3: US1 — coroutine shape tests (T007-T009)
# ─────────────────────────────────────────────────────────────────────────


def test_sync_is_coroutine_function():
    """T007: _sync must be an async coroutine function."""
    assert asyncio.iscoroutinefunction(CuemsDeploy._sync)


def test_kill_is_coroutine_function():
    """T008: _kill must be an async coroutine function."""
    assert asyncio.iscoroutinefunction(CuemsDeploy._kill)


def test_check_mandatory_sources_is_coroutine_function():
    """T009: _check_mandatory_sources must be an async coroutine function."""
    assert asyncio.iscoroutinefunction(CuemsDeploy._check_mandatory_sources)


# ─────────────────────────────────────────────────────────────────────────
# Phase 3: US1 — loop guard (T010)
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_returns_false_when_loop_is_none():
    """
    T010: sync_files must return False immediately when self.loop is None (async path).
    """
    d = CuemsDeploy(controller_ip="10.0.0.1", is_async=True)
    assert d.loop is None
    result = d.sync_files("proj", "project")
    assert result is False


# ─────────────────────────────────────────────────────────────────────────
# Phase 3: US1 — async watchdog tests (T011, T012)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sync_startup_watchdog_fires(tmp_path, monkeypatch):
    """T011: startup watchdog fires when asyncio.wait returns empty done set
    before first output (pump tasks hang, timeout expires)."""
    import cuemsengine.tools.CuemsDeploy as mod

    monkeypatch.setattr(mod, "_STARTUP_DEADLINE_S", 0.05)
    monkeypatch.setattr(mod, "_INACTIVITY_S", 0.05)

    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    async def _hanging_read(n):
        await asyncio.sleep(100)
        return b""

    proc = MagicMock()
    proc.returncode = None
    proc.stdout = MagicMock()
    proc.stdout.read = _hanging_read
    proc.stderr = MagicMock()
    proc.stderr.read = _hanging_read

    async def _wait():
        proc.returncode = 0
        return 0

    proc.wait = _wait
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await d._sync(str(log_file))

    assert result is False
    assert any("startup deadline" in e for e in d.errors), d.errors
    proc.terminate.assert_called()


@pytest.mark.anyio
async def test_sync_inactivity_watchdog_fires_after_first_chunk(tmp_path, monkeypatch):
    """
    T012: inactivity watchdog fires after first chunk arrives then silence.
    """
    import cuemsengine.tools.CuemsDeploy as mod

    monkeypatch.setattr(mod, "_STARTUP_DEADLINE_S", 0.05)
    monkeypatch.setattr(mod, "_INACTIVITY_S", 0.05)

    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    stdout_source = iter([b"  1,024   0%    0.00kB/s    0:00:00\r"])

    async def _read_stdout(n):
        chunk = next(stdout_source, None)
        if chunk is not None:
            return chunk
        await asyncio.sleep(100)
        return b""

    async def _hanging_read(n):
        await asyncio.sleep(100)
        return b""

    proc = MagicMock()
    proc.returncode = None
    proc.stdout = MagicMock()
    proc.stdout.read = _read_stdout
    proc.stderr = MagicMock()
    proc.stderr.read = _hanging_read

    async def _wait():
        proc.returncode = 0
        return 0

    proc.wait = _wait
    proc.terminate = MagicMock()
    proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        result = await d._sync(str(log_file))

    assert result is False
    assert any("inactivity threshold" in e for e in d.errors), d.errors


# ─────────────────────────────────────────────────────────────────────────
# Phase 3: US1 — async _check_mandatory_sources (T013)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_check_mandatory_sources_false_and_paths_on_nonzero_exit():
    """T013: async _check_mandatory_sources returns (False, [path]) when
    asyncio.create_subprocess_exec exits non-zero with matching stderr."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    stderr_payload = (
        b'rsync: [sender] link_stat "/projects/proj/script.xml" failed: '
        b"No such file or directory (2)\n"
    )
    proc = MagicMock()
    proc.returncode = 23

    async def _communicate():
        return b"", stderr_payload

    proc.communicate = _communicate

    with patch("asyncio.create_subprocess_exec", return_value=proc):
        ok, missing = await d._check_mandatory_sources(["/projects/proj/script.xml"])

    assert ok is False
    assert missing == ["/projects/proj/script.xml"]


# ─────────────────────────────────────────────────────────────────────────
# Phase 3: US1 — sync bridge tests (T014, T015)
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_returns_false_and_skips_sync_when_precheck_fails(
    deploy_with_loop,
):
    """
    T014: sync_files returns False without calling _sync when precheck fails.
    """
    d = deploy_with_loop
    with (
        patch.object(
            d,
            "_check_mandatory_sources",
            new_callable=AsyncMock,
            return_value=(False, ["/projects/proj/script.xml"]),
        ),
        patch.object(
            d,
            "_sync",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_sync,
        patch.object(
            d,
            "_create_deploy_log",
            return_value=True,
        ),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d.sync_files("proj", "project")

    assert result is False
    mock_sync.assert_not_called()


def test_sync_files_returns_true_when_precheck_and_sync_succeed(
    deploy_with_loop,
):
    """T015: sync_files returns True when both precheck and _sync succeed."""
    d = deploy_with_loop
    with (
        patch.object(
            d,
            "_check_mandatory_sources",
            new_callable=AsyncMock,
            return_value=(True, []),
        ),
        patch.object(
            d,
            "_sync",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(
            d,
            "_create_deploy_log",
            return_value=True,
        ),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d.sync_files("proj", "project")

    assert result is True


# ─────────────────────────────────────────────────────────────────────────
# Phase 4: US2 — --delete flags (T027, T028)
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sync_command_includes_delete_flags(tmp_path):
    """T027: rsync cmd in _sync() must contain --delete and --delete-delay."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = tmp_path / "rsync_request.log"
    log_file.write_text("")

    proc = _make_async_proc(rc=0, stdout_chunks=[b""], stderr_chunks=[b""])
    captured = []

    async def _capture(*args, **kwargs):
        captured.extend(args)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=_capture):
        await d._sync(str(log_file))

    assert "--delete" in captured
    assert "--delete-delay" in captured


@pytest.mark.anyio
async def test_check_mandatory_sources_does_not_include_delete_flags():
    """
    T028: rsync cmd in _check_mandatory_sources() must NOT contain --delete.
    """
    d = CuemsDeploy(controller_ip="10.0.0.1")
    proc = MagicMock()
    proc.returncode = 0

    async def _communicate():
        return b"", b""

    proc.communicate = _communicate
    captured = []

    async def _capture(*args, **kwargs):
        captured.extend(args)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=_capture):
        await d._check_mandatory_sources(["/projects/proj/script.xml"])

    assert "--delete" not in captured
    assert "--delete-delay" not in captured


# ─────────────────────────────────────────────────────────────────────────
# Phase 5: US3 — password constant verification (T030)
# ─────────────────────────────────────────────────────────────────────────


def test_rsync_password_not_in_method_bodies():
    """T030: neither _sync nor _check_mandatory_sources body contains the
    password literal; _RSYNC_PASSWORD is annotated as ClassVar."""
    import inspect

    sync_src = inspect.getsource(CuemsDeploy._sync)
    check_src = inspect.getsource(CuemsDeploy._check_mandatory_sources)
    assert "f48t5eL2kLHw2Wfw" not in sync_src
    assert "f48t5eL2kLHw2Wfw" not in check_src
    # ClassVar annotation must appear in the class body
    class_src = inspect.getsource(CuemsDeploy)
    assert "ClassVar" in class_src


# ─────────────────────────────────────────────────────────────────────────
# Phase 6: US4 — _media_files path expansion (T031, T032)
# ─────────────────────────────────────────────────────────────────────────


def test_media_files_video_and_audio(deploy):
    """T031: video gets media/ + idx entry; audio gets only media/ entry."""
    result = deploy._media_files(["clip.mp4", "track.wav"])
    assert result == [
        "media/clip.mp4",
        "media/indexes/clip.mp4.idx",
        "media/track.wav",
    ]


def test_media_files_idx_only_for_video_extensions(deploy):
    """T032: .avi and .mkv get idx entries; .mp3 does not."""
    result = deploy._media_files(["a.avi", "b.mkv", "c.mp3"])
    assert "media/a.avi" in result
    assert "media/indexes/a.avi.idx" in result
    assert "media/b.mkv" in result
    assert "media/indexes/b.mkv.idx" in result
    assert "media/c.mp3" in result
    assert "media/indexes/c.mp3.idx" not in result


# ─────────────────────────────────────────────────────────────────────────
# T003 / T004 — Constructor: is_async parameter
# ─────────────────────────────────────────────────────────────────────────


def test_constructor_accepts_is_async_false_default():
    """T003: default construction stores _is_async=False with no kwarg."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    assert d._is_async is False


def test_constructor_accepts_is_async_true():
    """T004: is_async=True is stored as True."""
    d = CuemsDeploy(controller_ip="10.0.0.1", is_async=True)
    assert d._is_async is True


# ─────────────────────────────────────────────────────────────────────────
# T006 — sync_files routing: _is_async flag dispatches to correct private method
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_routes_to_blocking_when_is_async_false():
    """T006a: with _is_async=False, sync_files calls _sync_files_blocking."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    with (
        patch.object(d, "_sync_files_blocking", return_value=True) as mock_blocking,
        patch.object(d, "_sync_files_async", return_value=True) as mock_async,
    ):
        result = d.sync_files("proj", "project")
    mock_blocking.assert_called_once_with("proj", "project", [])
    mock_async.assert_not_called()
    assert result is True


def test_sync_files_routes_to_async_when_is_async_true():
    """T006b: with _is_async=True, sync_files calls _sync_files_async."""
    d = CuemsDeploy(controller_ip="10.0.0.1", is_async=True)
    with (
        patch.object(d, "_sync_files_blocking", return_value=True) as mock_blocking,
        patch.object(d, "_sync_files_async", return_value=True) as mock_async,
    ):
        result = d.sync_files("proj", "project")
    mock_async.assert_called_once_with("proj", "project", [])
    mock_blocking.assert_not_called()
    assert result is True


# ─────────────────────────────────────────────────────────────────────────
# T012–T014 — _kill_blocking tests
# ─────────────────────────────────────────────────────────────────────────

import os as _os
import subprocess as _subprocess


def test_kill_blocking_is_not_coroutine():
    """T012: _kill_blocking must be a plain method, not a coroutine."""
    assert not asyncio.iscoroutinefunction(CuemsDeploy._kill_blocking)


def test_kill_blocking_terminates_then_waits():
    """T013: normal case — terminate + wait(timeout=2) succeeds."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    proc = MagicMock()
    proc.wait.return_value = 0
    d._kill_blocking(proc)
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=2)


def test_kill_blocking_escalates_to_kill_on_timeout():
    """T014: if wait() times out, proc.kill() is called."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    proc = MagicMock()
    proc.wait.side_effect = [_subprocess.TimeoutExpired(cmd="rsync", timeout=2), 0]
    d._kill_blocking(proc)
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# T016–T021 — _sync_blocking tests
# Uses real OS pipes so fcntl/selectors/os.read work without extra mocking.
# ─────────────────────────────────────────────────────────────────────────


def _make_sync_blocking_proc(r_out, r_err, wait_rc=0, poll_rc=0):
    """Fake subprocess.Popen return value backed by real pipe fds."""
    proc = MagicMock()
    proc.stdout.fileno.return_value = r_out
    proc.stderr.fileno.return_value = r_err
    proc.wait.return_value = wait_rc
    proc.poll.return_value = poll_rc
    return proc


def test_sync_blocking_is_not_coroutine():
    """T016: _sync_blocking must be a plain method, not a coroutine."""
    assert not asyncio.iscoroutinefunction(CuemsDeploy._sync_blocking)


def test_sync_blocking_includes_correct_rsync_flags(tmp_path):
    """T017: _sync_blocking builds rsync cmd with all required flags."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.close(w_out)
    _os.close(w_err)

    captured_cmd = []

    def _fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _make_sync_blocking_proc(r_out, r_err)

    with patch(
        "cuemsengine.tools.CuemsDeploy.subprocess.Popen", side_effect=_fake_popen
    ):
        d._sync_blocking(log_file)

    _os.close(r_out)
    _os.close(r_err)

    assert "rsync" in captured_cmd
    assert "-rt" in captured_cmd
    assert "--delete" in captured_cmd
    assert "--delete-delay" in captured_cmd
    assert "--contimeout=2" in captured_cmd
    assert "--timeout=5" in captured_cmd
    assert "--ignore-missing-args" in captured_cmd
    assert "--info=progress2,name0" in captured_cmd
    assert f"--files-from={log_file}" in captured_cmd


def test_sync_blocking_returns_true_on_zero_exit(tmp_path):
    """T018: zero exit code → True + errors cleared."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.close(w_out)
    _os.close(w_err)
    proc = _make_sync_blocking_proc(r_out, r_err, wait_rc=0, poll_rc=0)

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(r_out)
    _os.close(r_err)
    assert result is True
    assert d.errors == []


def test_sync_blocking_returns_false_on_nonzero_exit(tmp_path):
    """T019: non-zero exit code → False + errors contain stderr output."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.write(w_err, b"rsync connection refused\n")
    _os.close(w_out)
    _os.close(w_err)
    proc = _make_sync_blocking_proc(r_out, r_err, wait_rc=10, poll_rc=10)

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(r_out)
    _os.close(r_err)
    assert result is False
    assert any("rsync connection refused" in e for e in d.errors)


def test_sync_blocking_startup_deadline_fires(tmp_path, monkeypatch):
    """T020: no output before startup deadline → False + startup-deadline error."""
    import cuemsengine.tools.CuemsDeploy as _mod

    monkeypatch.setattr(_mod, "_STARTUP_DEADLINE_S", 0.05)
    monkeypatch.setattr(_mod, "_INACTIVITY_S", 0.05)

    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    proc = MagicMock()
    proc.stdout.fileno.return_value = r_out
    proc.stderr.fileno.return_value = r_err
    proc.wait.return_value = 0
    proc.poll.return_value = None

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(w_out)
    _os.close(r_out)
    _os.close(w_err)
    _os.close(r_err)
    assert result is False
    assert any("startup deadline" in e for e in d.errors)
    proc.terminate.assert_called()


def test_sync_blocking_inactivity_fires_after_first_chunk(tmp_path, monkeypatch):
    """T021: output then silence → False + inactivity-threshold error."""
    import cuemsengine.tools.CuemsDeploy as _mod

    monkeypatch.setattr(_mod, "_STARTUP_DEADLINE_S", 0.05)
    monkeypatch.setattr(_mod, "_INACTIVITY_S", 0.05)

    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.write(w_out, b"  1,024   0%    0.00kB/s    0:00:00\r")
    proc = MagicMock()
    proc.stdout.fileno.return_value = r_out
    proc.stderr.fileno.return_value = r_err
    proc.wait.return_value = 0
    proc.poll.return_value = None

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(w_out)
    _os.close(r_out)
    _os.close(w_err)
    _os.close(r_err)
    assert result is False
    assert any("inactivity threshold" in e for e in d.errors)
    proc.terminate.assert_called()


# ─────────────────────────────────────────────────────────────────────────
# T023–T029 — _sync_files_blocking tests
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_blocking_returns_false_when_disabled():
    """T023: disabled instance (no controller IP) → False without attempting rsync."""
    d = CuemsDeploy(controller_ip=None)
    result = d._sync_files_blocking("proj", "project", [])
    assert result is False


def test_sync_files_blocking_does_not_require_loop():
    """T024: _sync_files_blocking with no loop bound → succeeds (no RuntimeError)."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    assert d.loop is None
    with (
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d._sync_files_blocking("proj", "project", [])
    assert result is True


def test_sync_files_blocking_defaults_project_files_for_project_tag():
    """T025: tag='project' with empty file_names → _project_files() expansion."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    captured = []

    def _capture(log_file, file_names):
        captured.extend(file_names)
        return True

    with (
        patch.object(d, "_create_deploy_log", side_effect=_capture),
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        d._sync_files_blocking("proj", "project", [])

    assert any("/projects/proj/script.xml" in f for f in captured)


def test_sync_files_blocking_expands_media_files_for_media_tag():
    """T026: tag='media' with file list → _media_files() expansion."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    captured = []

    def _capture(log_file, file_names):
        captured.extend(file_names)
        return True

    with (
        patch.object(d, "_create_deploy_log", side_effect=_capture),
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        d._sync_files_blocking("proj", "media", ["clip.mp4"])

    assert "media/clip.mp4" in captured
    assert "media/indexes/clip.mp4.idx" in captured


def test_sync_files_blocking_returns_true_on_success():
    """T027: _sync_blocking returns True → _sync_files_blocking returns True."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    with (
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log") as mock_reset,
    ):
        result = d._sync_files_blocking("proj", "project", [])
    assert result is True
    mock_reset.assert_called_once()


def test_sync_files_blocking_logs_errors_on_failure():
    """T028: _sync_blocking returns False → _sync_files_blocking returns False."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    d.errors = ["fake error"]
    with (
        patch.object(d, "_sync_blocking", return_value=False),
        patch.object(d, "_create_deploy_log", return_value=True),
    ):
        result = d._sync_files_blocking("proj", "project", [])
    assert result is False


def test_sync_files_blocking_does_not_call_check_mandatory_sources():
    """T029: _check_mandatory_sources must NOT be called on the blocking path (FR-012)."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    with (
        patch.object(d, "_check_mandatory_sources") as mock_check,
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        d._sync_files_blocking("proj", "project", [])
    assert mock_check.call_count == 0


# ─────────────────────────────────────────────────────────────────────────
# T031–T032 — _sync_files_async specification tests (US2)
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_async_returns_false_when_loop_unbound():
    """T031: async path with no loop bound → False + 'event loop not bound' error."""
    d = CuemsDeploy(controller_ip="10.0.0.1", is_async=True)
    assert d.loop is None
    result = d.sync_files("proj", "project")
    assert result is False
    assert d.errors == ["event loop not bound"]


def test_sync_files_async_errors_cleared_on_success(deploy_with_loop):
    """T032: stale errors are cleared when async deploy succeeds."""
    d = deploy_with_loop
    d.errors = ["stale"]
    with (
        patch.object(
            d,
            "_check_mandatory_sources",
            new_callable=AsyncMock,
            return_value=(True, []),
        ),
        patch.object(d, "_sync", new_callable=AsyncMock, return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d.sync_files("proj", "project")
    assert result is True
    assert d.errors == []


# ─────────────────────────────────────────────────────────────────────────
# T003 / T004 — Constructor: is_async parameter
# ─────────────────────────────────────────────────────────────────────────


def test_constructor_accepts_is_async_false_default():
    """T003: default construction stores _is_async=False with no kwarg."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    assert d._is_async is False


def test_constructor_accepts_is_async_true():
    """T004: is_async=True is stored as True."""
    d = CuemsDeploy(controller_ip="10.0.0.1", is_async=True)
    assert d._is_async is True


# ─────────────────────────────────────────────────────────────────────────
# T006 — sync_files routing: _is_async flag dispatches to correct private method
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_routes_to_blocking_when_is_async_false():
    """T006a: with _is_async=False, sync_files calls _sync_files_blocking."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    with (
        patch.object(d, "_sync_files_blocking", return_value=True) as mock_blocking,
        patch.object(d, "_sync_files_async", return_value=True) as mock_async,
    ):
        result = d.sync_files("proj", "project")
    mock_blocking.assert_called_once_with("proj", "project", [])
    mock_async.assert_not_called()
    assert result is True


def test_sync_files_routes_to_async_when_is_async_true():
    """T006b: with _is_async=True, sync_files calls _sync_files_async."""
    d = CuemsDeploy(controller_ip="10.0.0.1", is_async=True)
    with (
        patch.object(d, "_sync_files_blocking", return_value=True) as mock_blocking,
        patch.object(d, "_sync_files_async", return_value=True) as mock_async,
    ):
        result = d.sync_files("proj", "project")
    mock_async.assert_called_once_with("proj", "project", [])
    mock_blocking.assert_not_called()
    assert result is True


# ─────────────────────────────────────────────────────────────────────────
# T012–T014 — _kill_blocking tests
# ─────────────────────────────────────────────────────────────────────────

import os as _os
import subprocess as _subprocess


def test_kill_blocking_is_not_coroutine():
    """T012: _kill_blocking must be a plain method, not a coroutine."""
    assert not asyncio.iscoroutinefunction(CuemsDeploy._kill_blocking)


def test_kill_blocking_terminates_then_waits():
    """T013: normal case — terminate + wait(timeout=2) succeeds."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    proc = MagicMock()
    proc.wait.return_value = 0
    d._kill_blocking(proc)
    proc.terminate.assert_called_once()
    proc.wait.assert_called_once_with(timeout=2)


def test_kill_blocking_escalates_to_kill_on_timeout():
    """T014: if wait() times out, proc.kill() is called."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    proc = MagicMock()
    proc.wait.side_effect = [_subprocess.TimeoutExpired(cmd="rsync", timeout=2), 0]
    d._kill_blocking(proc)
    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# T016–T021 — _sync_blocking tests
# Uses real OS pipes so fcntl/selectors/os.read work without extra mocking.
# ─────────────────────────────────────────────────────────────────────────


def _make_sync_blocking_proc(r_out, r_err, wait_rc=0, poll_rc=0):
    """Fake subprocess.Popen return value backed by real pipe fds."""
    proc = MagicMock()
    proc.stdout.fileno.return_value = r_out
    proc.stderr.fileno.return_value = r_err
    proc.wait.return_value = wait_rc
    proc.poll.return_value = poll_rc
    return proc


def test_sync_blocking_is_not_coroutine():
    """T016: _sync_blocking must be a plain method, not a coroutine."""
    assert not asyncio.iscoroutinefunction(CuemsDeploy._sync_blocking)


def test_sync_blocking_includes_correct_rsync_flags(tmp_path):
    """T017: _sync_blocking builds rsync cmd with all required flags."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.close(w_out)
    _os.close(w_err)

    captured_cmd = []

    def _fake_popen(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _make_sync_blocking_proc(r_out, r_err)

    with patch(
        "cuemsengine.tools.CuemsDeploy.subprocess.Popen", side_effect=_fake_popen
    ):
        d._sync_blocking(log_file)

    _os.close(r_out)
    _os.close(r_err)

    assert "rsync" in captured_cmd
    assert "-rt" in captured_cmd
    assert "--delete" in captured_cmd
    assert "--delete-delay" in captured_cmd
    assert "--contimeout=2" in captured_cmd
    assert "--timeout=5" in captured_cmd
    assert "--ignore-missing-args" in captured_cmd
    assert "--info=progress2,name0" in captured_cmd
    assert f"--files-from={log_file}" in captured_cmd


def test_sync_blocking_returns_true_on_zero_exit(tmp_path):
    """T018: zero exit code → True + errors cleared."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.close(w_out)
    _os.close(w_err)
    proc = _make_sync_blocking_proc(r_out, r_err, wait_rc=0, poll_rc=0)

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(r_out)
    _os.close(r_err)
    assert result is True
    assert d.errors == []


def test_sync_blocking_returns_false_on_nonzero_exit(tmp_path):
    """T019: non-zero exit code → False + errors contain stderr output."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.write(w_err, b"rsync connection refused\n")
    _os.close(w_out)
    _os.close(w_err)
    proc = _make_sync_blocking_proc(r_out, r_err, wait_rc=10, poll_rc=10)

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(r_out)
    _os.close(r_err)
    assert result is False
    assert any("rsync connection refused" in e for e in d.errors)


def test_sync_blocking_startup_deadline_fires(tmp_path, monkeypatch):
    """T020: no output before startup deadline → False + startup-deadline error."""
    import cuemsengine.tools.CuemsDeploy as _mod

    monkeypatch.setattr(_mod, "_STARTUP_DEADLINE_S", 0.05)
    monkeypatch.setattr(_mod, "_INACTIVITY_S", 0.05)

    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    proc = MagicMock()
    proc.stdout.fileno.return_value = r_out
    proc.stderr.fileno.return_value = r_err
    proc.wait.return_value = 0
    proc.poll.return_value = None

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(w_out)
    _os.close(r_out)
    _os.close(w_err)
    _os.close(r_err)
    assert result is False
    assert any("startup deadline" in e for e in d.errors)
    proc.terminate.assert_called()


def test_sync_blocking_inactivity_fires_after_first_chunk(tmp_path, monkeypatch):
    """T021: output then silence → False + inactivity-threshold error."""
    import cuemsengine.tools.CuemsDeploy as _mod

    monkeypatch.setattr(_mod, "_STARTUP_DEADLINE_S", 0.05)
    monkeypatch.setattr(_mod, "_INACTIVITY_S", 0.05)

    d = CuemsDeploy(controller_ip="10.0.0.1")
    log_file = str(tmp_path / "rsync.log")

    r_out, w_out = _os.pipe()
    r_err, w_err = _os.pipe()
    _os.write(w_out, b"  1,024   0%    0.00kB/s    0:00:00\r")
    proc = MagicMock()
    proc.stdout.fileno.return_value = r_out
    proc.stderr.fileno.return_value = r_err
    proc.wait.return_value = 0
    proc.poll.return_value = None

    with patch("cuemsengine.tools.CuemsDeploy.subprocess.Popen", return_value=proc):
        result = d._sync_blocking(log_file)

    _os.close(w_out)
    _os.close(r_out)
    _os.close(w_err)
    _os.close(r_err)
    assert result is False
    assert any("inactivity threshold" in e for e in d.errors)
    proc.terminate.assert_called()


# ─────────────────────────────────────────────────────────────────────────
# T023–T029 — _sync_files_blocking tests
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_blocking_returns_false_when_disabled():
    """T023: disabled instance (no controller IP) → False without attempting rsync."""
    d = CuemsDeploy(controller_ip=None)
    result = d._sync_files_blocking("proj", "project", [])
    assert result is False


def test_sync_files_blocking_does_not_require_loop():
    """T024: _sync_files_blocking with no loop bound → succeeds (no RuntimeError)."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    assert d.loop is None
    with (
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d._sync_files_blocking("proj", "project", [])
    assert result is True


def test_sync_files_blocking_defaults_project_files_for_project_tag():
    """T025: tag='project' with empty file_names → _project_files() expansion."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    captured = []

    def _capture(log_file, file_names):
        captured.extend(file_names)
        return True

    with (
        patch.object(d, "_create_deploy_log", side_effect=_capture),
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        d._sync_files_blocking("proj", "project", [])

    assert any("/projects/proj/script.xml" in f for f in captured)


def test_sync_files_blocking_expands_media_files_for_media_tag():
    """T026: tag='media' with file list → _media_files() expansion."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    captured = []

    def _capture(log_file, file_names):
        captured.extend(file_names)
        return True

    with (
        patch.object(d, "_create_deploy_log", side_effect=_capture),
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        d._sync_files_blocking("proj", "media", ["clip.mp4"])

    assert "media/clip.mp4" in captured
    assert "media/indexes/clip.mp4.idx" in captured


def test_sync_files_blocking_returns_true_on_success():
    """T027: _sync_blocking returns True → _sync_files_blocking returns True."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    with (
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log") as mock_reset,
    ):
        result = d._sync_files_blocking("proj", "project", [])
    assert result is True
    mock_reset.assert_called_once()


def test_sync_files_blocking_logs_errors_on_failure():
    """T028: _sync_blocking returns False → _sync_files_blocking returns False."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    d.errors = ["fake error"]
    with (
        patch.object(d, "_sync_blocking", return_value=False),
        patch.object(d, "_create_deploy_log", return_value=True),
    ):
        result = d._sync_files_blocking("proj", "project", [])
    assert result is False


def test_sync_files_blocking_does_not_call_check_mandatory_sources():
    """T029: _check_mandatory_sources must NOT be called on the blocking path (FR-012)."""
    d = CuemsDeploy(controller_ip="10.0.0.1")
    with (
        patch.object(d, "_check_mandatory_sources") as mock_check,
        patch.object(d, "_sync_blocking", return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        d._sync_files_blocking("proj", "project", [])
    assert mock_check.call_count == 0


# ─────────────────────────────────────────────────────────────────────────
# T031–T032 — _sync_files_async specification tests (US2)
# ─────────────────────────────────────────────────────────────────────────


def test_sync_files_async_returns_false_when_loop_unbound():
    """T031: async path with no loop bound → False + 'event loop not bound' error."""
    d = CuemsDeploy(controller_ip="10.0.0.1", is_async=True)
    assert d.loop is None
    result = d.sync_files("proj", "project")
    assert result is False
    assert d.errors == ["event loop not bound"]


def test_sync_files_async_errors_cleared_on_success(deploy_with_loop):
    """T032: stale errors are cleared when async deploy succeeds."""
    d = deploy_with_loop
    d.errors = ["stale"]
    with (
        patch.object(
            d,
            "_check_mandatory_sources",
            new_callable=AsyncMock,
            return_value=(True, []),
        ),
        patch.object(d, "_sync", new_callable=AsyncMock, return_value=True),
        patch.object(d, "_create_deploy_log", return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d.sync_files("proj", "project")
    assert result is True
    assert d.errors == []


def test_sync_files_media_tag_auto_expands_bare_names(deploy_with_loop):
    """T034a: sync_files with tag='media' must expand bare filenames via
    _media_files before passing them to _create_deploy_log / _sync."""
    d = deploy_with_loop
    captured_file_names = []

    def _capture_log(log_file, file_names):
        captured_file_names.extend(file_names)
        return True

    with (
        patch.object(d, "_create_deploy_log", side_effect=_capture_log),
        patch.object(d, "_sync", new_callable=AsyncMock, return_value=True),
        patch.object(d, "_reset_deploy_log"),
    ):
        result = d.sync_files("proj", "media", ["clip.mp4", "track.wav"])

    assert result is True
    assert "media/clip.mp4" in captured_file_names
    assert "media/indexes/clip.mp4.idx" in captured_file_names
    assert "media/track.wav" in captured_file_names
    assert "clip.mp4" not in captured_file_names
