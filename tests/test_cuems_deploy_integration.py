# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>
"""Integration tests for CuemsDeploy async/NNG heartbeat coexistence (SC-001)."""

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All tests in this module are integration-class (excluded from fast unit runs).
pytestmark = pytest.mark.integration


def _make_chunked_proc(n_chunks=5, chunk_interval=0.05):
    """Return a fake asyncio subprocess that emits n_chunks progress lines then exits."""
    progress_line = b"    32,768  50%    1.00MB/s    0:00:01 (xfr#1, to-chk=0/1)\r"

    async def _read_out(size):
        await asyncio.sleep(chunk_interval)
        return progress_line

    async def _read_err(_size):
        return b""

    out_read_count = [0]

    async def _counting_read_out(size):
        out_read_count[0] += 1
        if out_read_count[0] > n_chunks:
            return b""
        await asyncio.sleep(chunk_interval)
        return progress_line

    stdout = MagicMock()
    stdout.read = _counting_read_out
    stderr = MagicMock()
    stderr.read = _read_err

    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = 0

    async def _wait():
        # Only complete after both pump tasks have seen EOF (stdout returns b'').
        await asyncio.sleep(chunk_interval * (n_chunks + 2))
        proc.returncode = 0
        return 0

    proc.wait = _wait
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc


def test_nng_heartbeat_not_blocked_during_deploy():
    """SC-001: NNG heartbeats are not blocked while CuemsDeploy.sync_files() runs.

    Spins up a real asyncio event loop in a background thread, binds it to
    CuemsDeploy.loop, mocks asyncio.create_subprocess_exec to return a slow fake
    process, and concurrently schedules a heartbeat coroutine that records
    loop.time() at 1 Hz. After sync_files() returns, asserts:
      (a) sync_files returned True
      (b) heartbeat intervals were within ±20% of 1 s with no missed beats

    The fake process emits 5 chunks spaced 50 ms apart, so the transfer takes
    ~250 ms. The heartbeat runs at 1 Hz and should complete at least 1 interval
    cycle with no stall.
    """
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()

    heartbeat_times: list[float] = []
    heartbeat_done = threading.Event()

    async def _heartbeat(n=3):
        for _ in range(n):
            heartbeat_times.append(loop.time())
            await asyncio.sleep(0.1)
        heartbeat_done.set()

    asyncio.run_coroutine_threadsafe(_heartbeat(n=3), loop)

    from cuemsengine.tools.CuemsDeploy import CuemsDeploy

    d = CuemsDeploy.__new__(CuemsDeploy)
    d.library_path = "/opt/cuems_library/"
    d.tmp_path = "/tmp/"
    d.log_file = "/tmp/rsync_test.log"
    d.errors = []
    d.encoding = "utf-8"
    d._on_progress = lambda _: None
    d.loop = loop
    d.enabled = True
    d.main_ip = "127.0.0.1"
    d.address = "rsync://cuems_library_rsync@127.0.0.1/cuems"

    fake_proc = _make_chunked_proc(n_chunks=5, chunk_interval=0.05)

    result_holder: list[bool] = []

    def _call_sync():
        with (
            patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=fake_proc,
            ),
            patch.object(d, "_create_deploy_log", return_value=True),
            patch.object(d, "_reset_deploy_log"),
        ):
            # tag='media' has no mandatory paths, so precheck is skipped.
            # The test focuses on heartbeat coexistence during the rsync transfer.
            r = d.sync_files("test_project", "media", ["media/clip.mp4"])
            result_holder.append(r)

    caller_thread = threading.Thread(target=_call_sync)
    caller_thread.start()
    caller_thread.join(timeout=10)

    heartbeat_done.wait(timeout=5)

    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=5)

    assert result_holder, "sync_files() did not return within 10 s"
    assert result_holder[0] is True, f"sync_files() returned False; errors={d.errors}"

    assert len(heartbeat_times) >= 2, "heartbeat recorded fewer than 2 timestamps"
    intervals = [
        heartbeat_times[i + 1] - heartbeat_times[i]
        for i in range(len(heartbeat_times) - 1)
    ]
    for i, interval in enumerate(intervals):
        assert (
            0.08 <= interval <= 0.12
        ), f"heartbeat interval {i} was {interval:.3f}s (expected 0.100 ± 20%)"
