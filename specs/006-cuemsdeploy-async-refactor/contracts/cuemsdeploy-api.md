# Contract: CuemsDeploy Public API

**Feature**: 006-cuemsdeploy-async-refactor | **Date**: 2026-05-19

This contract describes the externally-observable interface of `CuemsDeploy` after the refactor.
Callers (primarily `NodeEngine`) depend only on the items listed here.

---

## Constructor

```python
CuemsDeploy(
    library_path: str = '/opt/cuems_library/',
    tmp_path: str = '/tmp/cuems_library/',
    controller_ip: str | None = None,
    hostname: str | None = None,
    log_file: str = '/run/cuems/rsync.log',
    on_progress: Callable[[dict], None] | None = None,
    loop: asyncio.AbstractEventLoop | None = None,   # NEW — default None
)
```

**New parameter `loop`**: The asyncio event loop onto which deploy coroutines are submitted.
When `None` (default), `sync_files()` logs an error and returns `False` without attempting
any subprocess. Callers MUST late-bind this attribute after the comms thread starts (see
Late-Bind Protocol below).

All other parameters are unchanged from the pre-refactor API.

---

## `sync_files(project, tag, file_names=None) → bool`

**Signature**: unchanged.

**Behaviour**:
- Returns `False` immediately if `self.enabled` is `False` (no controller IP).
- Returns `False` immediately if `self.loop` is `None` (loop not yet bound).
- Resolves the file list, submits the full deploy flow (precheck → sync) to `self.loop`
  as a single coroutine, blocks until the coroutine completes.
- On success: resets the deploy log file, clears `self.errors`, returns `True`.
- On failure: populates `self.errors` with diagnostic strings, returns `False`.

**Blocking**: Always blocks the calling thread until the deploy completes or fails.
The asyncio loop is free to service other tasks during the rsync I/O.

**Thread safety**: Not re-entrant. Callers MUST NOT invoke `sync_files()` concurrently
from multiple threads (the existing `NodeEngine._loading_lock` already enforces this for
the `load` command path).

---

## `errors: list[str]`

Populated after a failed `sync_files()` call. Reset to `[]` on success.
Contents are human-readable diagnostic lines, stripped of the rsync positional trailer
(`rsync error: ... at main.c(NNN)`).

---

## `on_progress` callback

Called for each parsed `--info=progress2` line during a transfer.

```python
on_progress({'bytes': int, 'pct': int, 'rate': str, 'eta': str,
             'xfr': int, 'remaining': int, 'total': int})
# xfr/remaining/total present only when rsync emits the (xfr#N, to-chk=M/T) suffix
```

Invoked from the asyncio loop (inside the reader drain). Implementations MUST be
non-blocking (no I/O, no locks, no thread synchronisation). The callback may be called
zero times for transfers with no progress output.

---

## `_media_files(bare_names: list[str]) → list[str]`

Helper that expands bare media filenames into the rsync-relative paths expected by
`--files-from`. Not part of the original API; added by this refactor for use by
`NodeEngine.deploy_media()`.

```python
deploy._media_files(['intro.mp4', 'sfx.wav'])
# → ['media/intro.mp4', 'media/indexes/intro.mp4.idx', 'media/sfx.wav']
```

Exposed as a method (rather than a free function) so it can access the video-extension
set consistently. Prefixed with `_` — internal to the deploy layer; `NodeEngine` is the
only intended caller.

---

## Late-Bind Protocol (`NodeEngine` ↔ `CuemsDeploy`)

```
NodeEngine.__init__()
  └─ self.deploy_manager = CuemsDeploy(
         library_path=..., controller_ip=...,
         # loop NOT passed here — comms thread doesn't exist yet
     )

NodeEngine.start()
  └─ CUE_HANDLER.set_nng_comms(...)     ← starts AsyncCommsThread (creates event_loop)
  └─ ...
  └─ self.deploy_manager.loop = CUE_HANDLER.communications_thread.event_loop
     # MUST be set before any NNG 'load' command can arrive
```

**Invariant**: Any `sync_files()` call triggered by an NNG command arrives after
`NodeEngine.start()` completes, therefore after the loop is bound. The `loop is None`
guard in `sync_files()` is a belt-and-braces defence, not a normal code path.

---

## Class-level constant

```python
from typing import ClassVar

class CuemsDeploy:
    _RSYNC_PASSWORD: ClassVar[str] = "..."  # private to the class; not exported
```

**Rationale**: The credential is an implementation detail of `CuemsDeploy`'s subprocess
invocations — no caller outside this class needs to read it. The leading underscore signals
"do not import"; `ClassVar` signals to type checkers that this is a class constant, not an
instance attribute.

**Access pattern**: `self._RSYNC_PASSWORD` inside methods.

**Test patching** (if ever needed): `monkeypatch.setattr(CuemsDeploy, '_RSYNC_PASSWORD', '...')`.

Value is intentionally kept in source for this refactor. Rotation requires editing one line.

---

## Items NOT part of the public contract

The following are implementation details and may change without notice:

- `_sync()`, `_deploy_all_async()`, `_check_mandatory_sources()`, `_kill()`, `_pump()` — internal async coroutines
- `_project_files()`, `_mandatory_paths()`, `_deploy_log_path()` — internal path helpers
- `_create_deploy_log()`, `_reset_deploy_log()` — internal file helpers
- `_parse_progress()`, `_dispatch_line()` — internal line processing
- `_avahi_resolve()` — legacy hostname fallback, constructor-only
