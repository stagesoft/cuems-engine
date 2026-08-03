# Research: CuemsDeploy Async Refactor

**Feature**: 006-cuemsdeploy-async-refactor | **Date**: 2026-05-19

## 1. Mocking `asyncio.create_subprocess_exec` in pytest (no new deps)

**Decision**: Use `unittest.mock.AsyncMock` + `anyio` (`pytest.mark.anyio`) for async test cases;
use `asyncio.run()` inside plain sync tests where only a single coroutine call is exercised.

**Rationale**: `pytest-asyncio` is not installed and adding it requires team review (constitution §IV).
`anyio-4.11.0` is already a registered pytest plugin and supports `pytest.mark.anyio`, which works
with the stdlib `asyncio` backend. No new dependency needed.

**Pattern**:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

@pytest.mark.anyio
async def test_sync_success():
    proc = _make_async_proc(rc=0, stdout_chunks=[b'  32,768   0% ...\r', b''], stderr_chunks=[b''])
    with patch('asyncio.create_subprocess_exec', return_value=proc):
        result = await deploy._sync('/path/to/log')
    assert result is True
```

**`_make_async_proc` helper** (replaces `_make_proc` + `_ScriptedSelector`):

```python
def _make_async_proc(rc, stdout_chunks, stderr_chunks):
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

def _make_stream_reader(chunks):
    reader = MagicMock()
    q = iter(chunks)
    async def _read(n):
        return next(q, b'')
    reader.read = _read
    return reader
```

**Alternatives considered**:
- `asyncio.run()` wrappers in all test functions — workable for unit tests of individual coroutines
  but more verbose; `pytest.mark.anyio` is cleaner for test cases that await multiple coroutines.
- `pytest-asyncio` — not installed; adding it is out of scope for this refactor.

---

## 2. Two-reader-task watchdog design

**Decision**: Each pump task (`_pump_stdout`, `_pump_stderr`) reads until EOF and pushes decoded
lines into a shared `asyncio.Queue`. The main driver loop does `asyncio.wait({t_out, t_err}, timeout=budget)`:
an empty `done` set means the budget expired → watchdog fires → `_kill()` + return False.

**Rationale**: Using a queue decouples line production (reader tasks) from line dispatch
(`_dispatch_line`). The main loop keeps control of the watchdog reset, which must happen on
every received chunk, not once per task completion.

**Watchdog reset rule**: `deadline` is reset to `now + _INACTIVITY_S` after every `asyncio.wait`
call that returns a non-empty `done` set AND after the queue is drained. The startup deadline
(`_STARTUP_DEADLINE_S`) is replaced by `_INACTIVITY_S` after the first item is pulled from
the queue.

**Sentinel**: Reader tasks push `None` when they reach EOF; the main loop decrements a counter
(`pipes_done`) and exits when both are `None`.

**Sketch**:

```python
async def _pump(stream, tag, queue):
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            await queue.put((tag, None))   # EOF sentinel
            return
        await queue.put((tag, chunk))

async def _sync(self, path):
    proc = await asyncio.create_subprocess_exec(...)
    queue = asyncio.Queue()
    t_out = asyncio.create_task(_pump(proc.stdout, 'out', queue))
    t_err = asyncio.create_task(_pump(proc.stderr, 'err', queue))
    started = False
    deadline = asyncio.get_event_loop().time() + _STARTUP_DEADLINE_S
    pipes_done = 0
    bufs = {'out': '', 'err': ''}
    ...
    while pipes_done < 2:
        budget = deadline - asyncio.get_event_loop().time()
        done, _ = await asyncio.wait({t_out, t_err}, timeout=max(budget, 0.1))
        if not done:
            reason = 'no output within startup deadline' if not started \
                     else 'no output within inactivity threshold'
            await self._kill(proc)
            self.errors = [f'rsync {reason} (target: {self.address})']
            return False
        # drain queue without blocking — queue already has items because tasks ran
        while not queue.empty():
            tag, chunk = queue.get_nowait()
            if chunk is None:
                pipes_done += 1
                continue
            started = True
            deadline = asyncio.get_event_loop().time() + _INACTIVITY_S
            bufs[tag] += chunk.decode(errors='replace')
            *parts, bufs[tag] = re.split(r'[\r\n]', bufs[tag])
            for p in parts:
                if p:
                    self._dispatch_line(tag, p, stderr_lines)
    ...
```

**Alternatives considered**:
- `asyncio.gather` with reader coroutines returning lists — simpler but loses incremental dispatch
  and watchdog reset on each chunk.
- Direct `await stream.read()` in a `while True` loop — cannot watch two streams concurrently
  without tasks; would serialize stdout and stderr reads.

---

## 3. `run_coroutine_threadsafe` sync bridge pattern

**Decision**: `sync_files()` submits one internal coroutine `_deploy_all_async()` to `self.loop`
via `asyncio.run_coroutine_threadsafe`, then calls `.result()` with no timeout (watchdogs inside
the coroutine handle all time bounds).

**Rationale**: `sync_files()` is always called from a plain `threading.Thread` (the NNG command
dispatcher in `NodeCommunications` spawns a new thread per command — confirmed at
`comms/NodeCommunications.py:100`). `run_coroutine_threadsafe` is safe from non-loop threads and
the existing `AsyncCommsThread.run_coroutine()` uses the identical pattern.

**Edge case — `future.result()` raises**: Any exception that escapes `_deploy_all_async` is
re-raised by `.result()`. Caught at the `sync_files()` call site, logged, and returned as `False`.

**`_deploy_all_async` responsibility boundary**:
- Runs precheck (async), early-fails on precheck failure
- Creates the deploy log file (sync, fast — acceptable in a coroutine)
- Runs main sync (async)
- Returns `bool`
- Does NOT call `_reset_deploy_log` (left to `sync_files()` for symmetry with current code)

**Test approach for `sync_files()`**: Tests that exercise the sync bridge spin a real event loop
in a background thread (`threading.Thread(target=loop.run_forever)`), set `deploy.loop`, then
call `sync_files()` synchronously. Inner coroutines are mocked via `AsyncMock`.

**Alternatives considered**:
- Wrapping `_deploy_all_async` with `asyncio.run()` per call — creates a fresh loop each time;
  incompatible if called from within a running loop in future; wastes thread pool.
- Exposing `async def sync_files_async()` alongside sync version — YAGNI; `NodeEngine` doesn't
  need it today.

---

## 4. `--delete-delay` with `--files-from` semantics

**Decision**: Add `--delete` and `--delete-delay` to the main `_sync()` rsync invocation.
Do **not** add them to the `_check_mandatory_sources` probe (`--list-only`).

**Rationale**: `--delete-delay` deletes at the receiver files that don't exist at the sender,
but defers all deletions until after all file transfers complete. This makes it safer than `--delete`
(which deletes as it traverses) when combined with a large transfer — a failed transfer leaves
the receiver intact rather than partially cleaned.

**Scope with `--files-from`**: rsync with `--files-from` operates on the paths listed in the
file. `--delete` applies to the directories that rsync traverses during the transfer. For
`/projects/<name>/` (project files) and `media/` (media files), this means only files in those
specific directory trees are candidates for deletion — not the entire library root.

**Risk note**: `--delete` with `media/` means files from a previously loaded project that are
not listed in the new project's file list will be removed. This is the intended behaviour
(controller is source of truth), but it means nodes cannot serve as a cache for multiple
projects simultaneously.

**`--list-only` exclusion**: The mandatory precheck uses `--list-only` to probe existence — it
never writes to the receiver. Adding `--delete-delay` to a `--list-only` call would be a no-op
but is excluded explicitly to keep the probe read-only and its intent unambiguous.

**Alternatives considered**:
- `--delete-after` (rsync's own deferred delete) — semantically identical to `--delete-delay`
  for most use cases; `--delete-delay` is preferred as it preserves the full transferred set
  before any deletion, making it slightly safer during interrupted transfers.
- Scope-limited delete (media only, not project files) — rejected; user confirmed all syncs.

---

## 5. `asyncio.create_subprocess_exec` vs `create_subprocess_shell`

**Decision**: Use `asyncio.create_subprocess_exec` (no shell).

**Rationale**: The existing code uses `subprocess.Popen` with a list argument (no `shell=True`).
`create_subprocess_exec` is the direct equivalent, avoids shell injection risk, and passes the
same list-form command unchanged.
