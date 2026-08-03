# Data Model: CuemsDeploy Sync/Async Branching

## Modified Class: `CuemsDeploy`

### Constructor Changes

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `is_async` | `bool` | `False` | **New — last position.** Stored as `self._is_async`. Controls which I/O path `sync_files()` dispatches to. |

All existing parameters (`library_path`, `tmp_path`, `controller_ip`, `hostname`, `log_file`, `on_progress`, `loop`) are unchanged in position and default.

### Instance State

| Attribute | Type | Owner | Notes |
|-----------|------|-------|-------|
| `_is_async` | `bool` | new | Set in `__init__` from `is_async` param. |
| `loop` | `asyncio.AbstractEventLoop \| None` | existing | Only checked/used when `_is_async=True`. |
| `errors` | `list[str]` | existing | Shared; populated/cleared by both dispatch paths. |
| `enabled` | `bool` | existing | Checked first in both dispatch methods; unchanged semantics. |

### New Private Methods

#### `_sync_files_blocking(project, tag, file_names) -> bool`

**Responsibility**: Synchronous deploy flow — no event loop required.

**Logic** (mirrors reference commit `sync_files`, adds `_media_files` expansion):
```
if not self.enabled → return False
if tag == 'project' and not file_names → file_names = _project_files(project)
elif tag == 'media' and file_names → file_names = _media_files(file_names)
log_file = _deploy_log_path(project, tag)
_create_deploy_log(log_file, file_names)
synced = _sync_blocking(log_file)
if synced → _reset_deploy_log(log_file)
else → log errors
return synced
```

**Does NOT call**: `_mandatory_paths`, `_check_mandatory_sources`, `run_coroutine_threadsafe`.

#### `_sync_files_async(project, tag, file_names) -> bool`

**Responsibility**: Async deploy flow — event loop must be bound.

**Logic** (lifts current `sync_files` async body verbatim):
```
if self.loop is None → return False (log: "event loop not bound")
file_names = list(file_names or [])
if tag == 'project' and not file_names → file_names = _project_files(project)
elif tag == 'media' and file_names → file_names = _media_files(file_names)
mandatory_paths = _mandatory_paths(project, tag)
log_file = _deploy_log_path(project, tag)
coro = _deploy_all_async(log_file, file_names, mandatory_paths)
synced = run_coroutine_threadsafe(coro, self.loop).result()
...
return synced
```

#### `_sync_blocking(path: str) -> bool`

**Responsibility**: Blocking rsync subprocess supervision with watchdog.

**I/O primitives**: `subprocess.Popen`, `fcntl.fcntl` + `O_NONBLOCK`, `selectors.DefaultSelector`, `os.read`, `time.monotonic`.

**Watchdog state machine**:

```
State       Trigger                         Action
─────────────────────────────────────────────────────────
STARTUP     sel.select() → empty events    kill + errors = [startup msg] + return False
            (started=False, budget expires)
ACTIVE      sel.select() → empty events    kill + errors = [inactivity msg] + return False
            (started=True, budget=_INACTIVITY_S)
DONE        Both pipes closed, rc=0        errors=[] + return True
DONE        Both pipes closed, rc≠0        errors=stderr_lines (trailer stripped) + return False
PIPE_EXIT   Both pipes closed, proc hangs  kill + errors=[pipe-exit-timeout msg] + return False
```

**Budget logic**:
- Before first data: `budget = deadline - time.monotonic()` (counts down from `_STARTUP_DEADLINE_S`)
- After first data: `budget = _INACTIVITY_S` (fixed; resets at each `sel.select()` call)

**rsync command flags**: identical to async `_sync` (same `cmd` list including `-rt`, `--delete`, `--delete-delay`, `--info=progress2,name0`, `--stats`, `--contimeout=2`, `--timeout=5`, `--ignore-missing-args`, `--files-from`, `--log-file`).

**Password**: uses `self._RSYNC_PASSWORD` (class constant; password literal must NOT appear in method body).

#### `_kill_blocking(proc: subprocess.Popen) -> None`

**Responsibility**: Graceful termination with SIGKILL escalation.

```
proc.terminate()
try: proc.wait(timeout=2)
except subprocess.TimeoutExpired:
    proc.kill()
    try: proc.wait(timeout=2)
    except subprocess.TimeoutExpired: pass
```

### Modified Methods

#### `sync_files(project, tag, file_names=[]) -> bool`

**Change**: Body replaced by two-line branch. Signature unchanged.

```python
if self._is_async:
    return self._sync_files_async(project, tag, file_names)
return self._sync_files_blocking(project, tag, file_names)
```

#### `__init__(self, ..., loop=None, is_async: bool = False)`

**Change**: `is_async` parameter appended at last position; `self._is_async = is_async` added.

### Unchanged Methods (async path)

`_sync`, `_kill`, `_pump`, `_deploy_all_async`, `_check_mandatory_sources` — zero modifications.

### Shared Helpers (both paths)

`_avahi_resolve`, `_project_files`, `_media_files`, `_mandatory_paths`, `_parse_progress`, `_dispatch_line`, `_deploy_log_path`, `_create_deploy_log`, `_reset_deploy_log` — zero modifications.

### New Imports

```python
import fcntl
import selectors
import time
```

Added to the existing import block at module top level. All three are stdlib; `fcntl` is Linux-only (already assumed by the deployment context).

---

## Test Changes

### `tests/test_cuems_deploy.py`

| Change | Reason |
|--------|--------|
| `deploy_with_loop` fixture: add `is_async=True` | 6 tests depend on it; all test the async path which requires opt-in after `is_async=False` becomes default |
| `test_sync_files_returns_false_when_loop_is_none`: construct with `is_async=True` | Loop guard applies only to async path |
| New test block: blocking-path tests (Blocks B–G from plan) | TDD for new code |

### `tests/test_cuems_deploy_integration.py`

| Change | Reason |
|--------|--------|
| `test_nng_heartbeat_not_blocked_during_deploy`: set `d._is_async = True` on manually constructed instance | Test patches `asyncio.create_subprocess_exec`; only reachable via async path |
