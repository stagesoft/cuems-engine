# Implementation Plan: CuemsDeploy Async Refactor

**Branch**: `006-cuemsdeploy-async-refactor` | **Date**: 2026-05-19 | **Spec**: [spec.md](spec.md)

## Summary

Refactor `CuemsDeploy` to replace its `selectors`/`fcntl`/`subprocess.Popen` I/O loop with
`asyncio.create_subprocess_exec` and concurrent reader tasks, while keeping `sync_files()` as
a synchronous public API via a `run_coroutine_threadsafe` bridge. Simultaneously: extract
`RSYNC_PASSWORD` as a module constant, add `--delete --delete-delay` to the main sync command,
migrate `_check_mandatory_sources` to async (with early-fail semantics), and move the media
path-construction logic from `NodeEngine.deploy_media()` into a new `CuemsDeploy._media_files()`
helper.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: `asyncio` (stdlib), `subprocess` (stdlib, retained for `_avahi_resolve` only)  
**Storage**: N/A (temporary rsync list-files in `/tmp/cuems_library/`; rsync log in `/run/cuems/`)  
**Testing**: pytest + anyio (`pytest.mark.anyio` available via the existing `anyio-4.11.0` plugin; no new test dependency required)  
**Target Platform**: Linux server (systemd-managed node, Debian package)  
**Project Type**: Library component (engine internal module)  
**Performance Goals**: NNG heartbeat intervals within ±20% of cadence during a 1 GB media deploy (SC-001)  
**Constraints**: `sync_files()` public API signature must not change; loop is `None` until `NodeEngine.start()` late-binds it; `_avahi_resolve` runs in `__init__` before any asyncio loop exists — it stays synchronous  
**Scale/Scope**: Single-module refactor (`CuemsDeploy.py`), one call-site change (`NodeEngine.start()`), test file rewrite

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Rule | Status | Notes |
|------|--------|-------|
| TDD — failing test before any production code | ✅ Required | All existing tests become the regression baseline; new tests written first for each new behaviour (async path, `_media_files`, `--delete-delay` flag, early-fail) |
| No new runtime dependency | ✅ Pass | `asyncio` and `subprocess` are stdlib; `anyio` is an existing transitive dep; no new packages |
| SOLID — Single Responsibility | ✅ Improved | Media path knowledge moves from `NodeEngine` into `CuemsDeploy`; each async method has one job |
| SOLID — Dependency Inversion | ✅ Pass | Event loop injected via `loop` attribute (late-bind); `CuemsDeploy` does not import or reference `AsyncCommsThread` |
| YAGNI — no speculative abstraction | ✅ Pass | No new public classes; `_deploy_all_async` is private; `_media_files` is a direct extraction of existing `NodeEngine` code |
| Observability — no silent failures | ✅ Required | All error and watchdog paths MUST log before returning `False`; existing pattern preserved |
| Integration tests hit real subsystems | ⚠️ Deferred | Full rsync integration tests against a real rsync daemon are out of scope for this refactor; async unit tests mock `asyncio.create_subprocess_exec` at the boundary |

## Project Structure

### Documentation (this feature)

```text
specs/006-cuemsdeploy-async-refactor/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── contracts/
│   └── cuemsdeploy-api.md   ← Phase 1 output
└── tasks.md             ← Phase 2 output (/speckit-tasks)
```

### Source Code (affected files only)

```text
src/cuemsengine/tools/CuemsDeploy.py   # primary change — async migration + constant + media helper
src/cuemsengine/NodeEngine.py           # minimal: add late-bind in start(); update deploy_media()
tests/test_cuems_deploy.py              # rewrite async test infrastructure; add new cases
```

**Structure Decision**: Single-project layout, existing `src/` + `tests/` hierarchy. No new files or directories in `src/`.

## Complexity Tracking

No constitution violations. The async migration removes complexity (eliminates `selectors`, `fcntl`, `os.read` machinery) rather than adding it.
