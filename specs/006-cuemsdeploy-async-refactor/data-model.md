# Data Model: CuemsDeploy Async Refactor

**Feature**: 006-cuemsdeploy-async-refactor | **Date**: 2026-05-19

This refactor has no persistent data model changes. The relevant "model" is the internal
state of `CuemsDeploy` and the async execution graph.

---

## CuemsDeploy instance state

| Attribute | Type | Set when | Description |
|-----------|------|----------|-------------|
| `library_path` | `str` | `__init__` | Destination directory for rsync (`/opt/cuems_library/`) |
| `tmp_path` | `str` | `__init__` | Directory for rsync request log files (`/tmp/cuems_library/`) |
| `log_file` | `str` | `__init__` | Path for rsync's `--log-file` output (`/run/cuems/rsync.log`) |
| `main_ip` | `str \| None` | `__init__` | Resolved controller IP; `None` if unresolvable |
| `address` | `str \| None` | `__init__` | Full rsync daemon URL or `None` when disabled |
| `enabled` | `bool` | `__init__` | `True` iff `main_ip` is truthy |
| `errors` | `list[str]` | any failed call | Last error messages; reset to `[]` on success |
| `encoding` | `str` | `__init__` | Filesystem encoding for subprocess output decoding |
| `_on_progress` | `Callable[[dict], None]` | `__init__` | Progress callback; no-op by default |
| `loop` | `asyncio.AbstractEventLoop \| None` | `NodeEngine.start()` (late-bind) | Event loop for `run_coroutine_threadsafe`; `None` until bound |

---

## Async execution graph

```
sync_files(project, tag, file_names)            ← public, synchronous, blocking
  │
  ├─ guard: enabled? loop set?  →  return False (no subprocess)
  │
  ├─ _project_files(project)       [if tag=='project' and no file_names]
  ├─ _mandatory_paths(project, tag)
  ├─ _deploy_log_path(project, tag)
  │
  └─ run_coroutine_threadsafe(_deploy_all_async(...), self.loop).result()
         │
         ├─ _check_mandatory_sources(mandatory_paths)  [async, early-fail]
         │     └─ asyncio.create_subprocess_exec(rsync --list-only ...)
         │           stdout/stderr consumed inline (short probe, no watchdog tasks)
         │
         ├─ [early return False if precheck fails]
         │
         ├─ _create_deploy_log(log_file, file_names)   [sync file I/O, fast]
         │
         └─ _sync(log_file)                            [async]
               ├─ asyncio.create_subprocess_exec(rsync -rt --delete --delete-delay ...)
               ├─ asyncio.Queue  ←  _pump(stdout, 'out', queue)  [Task]
               │                 ←  _pump(stderr, 'err', queue)  [Task]
               └─ main driver loop
                     asyncio.wait({t_out, t_err}, timeout=budget)
                       ├─ empty done set  →  watchdog fires  →  _kill(proc)  →  False
                       └─ items in queue  →  drain + dispatch + reset deadline
```

---

## Progress event shape (unchanged)

Emitted to `on_progress` callback from `_dispatch_line` → `_parse_progress` for each
`--info=progress2` line:

| Field | Type | Present when | Description |
|-------|------|-------------|-------------|
| `bytes` | `int` | always | Bytes transferred so far |
| `pct` | `int` | always | Percentage complete (0–100) |
| `rate` | `str` | always | Transfer rate string (e.g. `"118.34MB/s"`) |
| `eta` | `str` | always | Estimated time remaining (`"H:MM:SS"`) |
| `xfr` | `int` | when xfr info present | Transfer count |
| `remaining` | `int` | when xfr info present | Files remaining at destination check |
| `total` | `int` | when xfr info present | Total files in transfer |

---

## Watchdog state machine (internal to `_sync`)

```
STATES: STARTUP → ACTIVE → DONE | KILLED

STARTUP:  deadline = now + _STARTUP_DEADLINE_S (10s)
          transition to ACTIVE on first queue item received

ACTIVE:   deadline = now + _INACTIVITY_S (15s), reset on every queue item
          transition to DONE when pipes_done == 2 and proc exits
          transition to KILLED if asyncio.wait returns empty done set

DONE:     rc == 0 → return True; rc != 0 → set errors from stderr_lines → return False

KILLED:   await _kill(proc) → set self.errors → return False
```

---

## `_media_files` output contract

Input: `bare_names: list[str]` — bare filenames (e.g. `["intro.mp4", "sfx.wav"]`)

Output: `list[str]` — rsync-relative paths for `--files-from`:
- Every file: `media/<name>` (e.g. `"media/intro.mp4"`)
- Video files only (`.mp4 .mov .avi .mkv .mpg`): `media/indexes/<name>.idx`

Example:
```python
_media_files(["intro.mp4", "sfx.wav"])
# → ["media/intro.mp4", "media/indexes/intro.mp4.idx", "media/sfx.wav"]
```
