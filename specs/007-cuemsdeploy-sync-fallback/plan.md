# Implementation Plan: CuemsDeploy Sync/Async Branching

**Branch**: `007-cuemsdeploy-sync-fallback` | **Date**: 2026-05-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/007-cuemsdeploy-sync-fallback/spec.md`

## Summary

Add `is_async: bool = False` to `CuemsDeploy.__init__()` and split `sync_files()` into two private dispatch methods: `_sync_files_blocking()` (restores `subprocess`/`selectors`/`fcntl` logic from commit `5b4eb4697e`) and `_sync_files_async()` (lifts the current async path into its own method). All five existing async methods are left untouched. Existing tests that test the async path must be updated to opt-in via `is_async=True`; new tests cover the blocking path.

## Technical Context

**Language/Version**: Python 3.11 (pyenv + Poetry)
**Primary Dependencies**: stdlib only — `asyncio`, `subprocess`, `selectors`, `fcntl`, `time`, `os`, `re`, `sys`, `tempfile`
**Storage**: N/A
**Testing**: pytest + anyio (existing setup)
**Target Platform**: Linux (Debian) — `fcntl` is Linux-only; already assumed by existing code
**Project Type**: internal library class (single file)
**Performance Goals**: identical to respective pre-existing paths; no new overhead
**Constraints**: zero new runtime dependencies; all added imports are stdlib

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **SRP** | PASS with caveat | `CuemsDeploy` already mixes addressing, I/O, progress parsing, and log management. Adding a branching parameter compounds this marginally. Mitigation: dispatch is a thin two-line branch; each private method is a clean unit. Acceptable for a contained refactor of an existing class. |
| **OCP** | PASS | All five existing async methods are closed to modification. New methods are additive. |
| **Liskov / ISeg / DI** | N/A | No subtype hierarchy or injected interface involved. |
| **TDD** | GATE — MANDATORY | Failing tests must be written and confirmed before any production code. New tests for `is_async=False` path + updates for existing async-path tests. |
| **YAGNI** | PASS | `is_async=False` is justified by the concrete requirement: callers without an event loop must not be forced into the async path. |
| **No new deps** | PASS | `fcntl`, `selectors`, `time` are stdlib; already used at commit `5b4eb4697e`. |
| **Observability** | PASS | Both paths populate `self.errors` and call `Logger.error/warning`. Silent failures forbidden. |
| **Doc layout** | PASS | All artifacts under `specs/007-cuemsdeploy-sync-fallback/`. |

**Post-Phase-1 re-check**: No design change invalidates any gate above.

## Project Structure

### Documentation (this feature)

```text
specs/007-cuemsdeploy-sync-fallback/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/cuemsengine/tools/
└── CuemsDeploy.py       # Single file modified

tests/
├── test_cuems_deploy.py             # Updated + new blocking-path tests appended
└── test_cuems_deploy_integration.py # Updated: opt-in to is_async=True
```

**Structure Decision**: Single-project layout; one source file changed, one test file updated, one integration file updated. No new files in `src/`.

## Complexity Tracking

No constitution violations requiring justification.

---

## Phase 0: Research

### Decision 1 — Routing mechanism

**Decision**: `sync_files()` branches via two private methods: `_sync_files_blocking()` and `_sync_files_async()`.
**Rationale**: Each private method is independently testable. The branch condition in `sync_files` reduces to two lines.
**Alternatives considered**: A single long `if/else` inside `sync_files()` — rejected; harder to test in isolation and violates spirit of SRP.

### Decision 2 — Synchronous I/O method names

**Decision**: `_sync_blocking(path: str) -> bool` and `_kill_blocking(proc: subprocess.Popen) -> None`.
**Rationale**: Parallel naming to `_sync` / `_kill` makes the relationship obvious; type signature difference (`subprocess.Popen` vs `asyncio.subprocess.Process`) disambiguates.
**Alternatives considered**: `_sync_subprocess`, `_sync_legacy` — less clear.

### Decision 3 — Mandatory precheck on sync path

**Decision**: `_sync_files_blocking()` does **not** include a precheck call (`_check_mandatory_sources`).
**Rationale**: FR-012 mandates replicating the reference commit's behaviour, which had no precheck. YAGNI prohibits adding it.
**Alternatives considered**: Synchronous precheck wrapper — rejected.

### Decision 4 — `_media_files` expansion on sync path

**Decision**: `_sync_files_blocking()` includes the `elif tag == 'media'` expansion via `_media_files()`, matching the current `sync_files` (even though the reference commit did not have it).
**Rationale**: FR-008 states both paths share `_media_files`; the reference commit predates `_media_files` being added. The feature goal is "complete backcompatibility" in terms of not needing an event loop, not stripping features added post-reference.
**Alternatives considered**: Omitting `_media_files` on sync path to match reference commit exactly — rejected; would silently break media deploys.

### Decision 5 — Test update strategy

**Decision**: Update the `deploy_with_loop` fixture to add `is_async=True`. This propagates to all 6 tests that depend on it and tests the async path correctly. Update `test_sync_files_returns_false_when_loop_is_none` to construct with `is_async=True`. Update the integration test `test_nng_heartbeat_not_blocked_during_deploy` to set `d._is_async = True` (or reconstruct with `is_async=True`).
**Rationale**: With `is_async=False` as default, the loop guard and `run_coroutine_threadsafe` path are only reachable with `is_async=True`. Tests that patch `asyncio.create_subprocess_exec` or `_check_mandatory_sources` are testing the async path and must opt-in.
**Alternatives considered**: Adding a separate `deploy_with_loop_async` fixture and leaving old one untouched — rejected; creates confusion about which fixture to use and leaves existing tests silently testing the wrong path.

### Decision 6 — `_sync_blocking` watchdog semantics

**Decision**: Faithfully restore the reference commit's watchdog state machine:
- Before first data (`started=False`): budget = `deadline - time.monotonic()` (remaining startup window)
- After first data (`started=True`): budget = fixed `_INACTIVITY_S` (resets per-select-call, not per-chunk)

**Rationale**: The async `_sync` resets the absolute deadline per-chunk (`deadline = loop.time() + _INACTIVITY_S`), which differs subtly. The blocking path matches the reference commit exactly to preserve backward-compatible timing.
**Alternatives considered**: Matching async deadline-reset logic in the blocking path — rejected (YAGNI; would diverge from the reference commit this path is meant to restore).

---

## Phase 1: Design

### data-model.md

See [data-model.md](data-model.md).

### Contracts

No external interface contract changes. `sync_files()` signature is unchanged. No REST/CLI/IPC surface affected.

### Agent context updated

CLAUDE.md now points to `specs/007-cuemsdeploy-sync-fallback/plan.md`.

---

## Implementation Sequence (for /speckit-tasks)

The tasks must follow TDD order within each unit:

> **Note on ordering vs `tasks.md`**: The blocks below describe the logical units of TDD work. The actual ordering in `tasks.md` differs in two ways: (1) Block A (fixture / existing-test updates) is deferred until *after* the constructor parameter (Block B) and the dispatcher (Block C) are implemented, because `deploy_with_loop` cannot opt into `is_async=True` until the parameter exists; (2) Block D's `_sync_files_async` extraction is treated as a **refactor** in T007 (covered by the existing async-path tests as a safety net), with explicit specification tests for `_sync_files_async` deferred to Phase 4 (characterization tests, not pre-impl failing tests).

### Block A — Test infrastructure setup

**A1**: Add `is_async=True` to `deploy_with_loop` fixture (updates 6 dependent async tests at once).
**A2**: Update `test_sync_files_returns_false_when_loop_is_none` to construct with `is_async=True`.
**A3**: Update integration test `test_nng_heartbeat_not_blocked_during_deploy` to use `is_async=True`.
**A4**: Confirm updated tests still pass (they should — async path unchanged).

### Block B — Constructor parameter (TDD)

**B1**: Write failing test: `test_constructor_accepts_is_async_false_default` — asserts `d._is_async is False` with no `is_async` arg.
**B2**: Write failing test: `test_constructor_accepts_is_async_true` — asserts `d._is_async is True`.
**B3**: Implement: add `is_async: bool = False` to `__init__`, store `self._is_async = is_async`.
**B4**: Green + confirm.

### Block C — `sync_files` routing (TDD)

**C1**: Write failing tests:
  - `test_sync_files_calls_sync_files_blocking_when_is_async_false`
  - `test_sync_files_calls_sync_files_async_when_is_async_true`
**C2**: Implement: reduce `sync_files` body to `if self._is_async: return self._sync_files_async(...) else: return self._sync_files_blocking(...)`.
**C3**: Green + confirm.

### Block D — `_sync_files_async` extraction (TDD)

**D1**: Write failing test: `test_sync_files_async_returns_false_when_loop_unbound` (uses `is_async=True`, no loop).
**D2**: Write failing test: `test_sync_files_async_submits_coroutine_via_threadsafe` (uses `is_async=True`, loop bound, mocks `run_coroutine_threadsafe`).
**D3**: Implement: move current `sync_files` async-path logic into `_sync_files_async(self, project, tag, file_names)`.
**D4**: Green + confirm.

### Block E — `_kill_blocking` (TDD)

**E1**: Write failing test: `test_kill_blocking_is_not_coroutine`.
**E2**: Write failing test: `test_kill_blocking_terminates_then_waits`.
**E3**: Write failing test: `test_kill_blocking_escalates_to_kill_on_timeout`.
**E4**: Implement `_kill_blocking(proc: subprocess.Popen) -> None` from reference commit.
**E5**: Green + confirm.

### Block F — `_sync_blocking` (TDD)

**F1**: Write failing tests:
  - `test_sync_blocking_is_not_coroutine`
  - `test_sync_blocking_returns_true_on_zero_exit` (mocks `subprocess.Popen`)
  - `test_sync_blocking_returns_false_on_nonzero_exit`
  - `test_sync_blocking_startup_deadline_fires` (mock hangs; shrink watchdog constants)
  - `test_sync_blocking_inactivity_fires_after_first_chunk`
  - `test_sync_blocking_includes_correct_rsync_flags`
**F2**: Add `import fcntl, selectors, time` to top of `CuemsDeploy.py`.
**F3**: Implement `_sync_blocking(self, path: str) -> bool` from reference commit (renamed internal `_kill` calls to `_kill_blocking`).
**F4**: Green + confirm.

### Block G — `_sync_files_blocking` (TDD)

**G1**: Write failing tests:
  - `test_sync_files_blocking_returns_false_when_disabled`
  - `test_sync_files_blocking_does_not_require_loop`
  - `test_sync_files_blocking_defaults_project_files_when_tag_is_project`
  - `test_sync_files_blocking_expands_media_files_when_tag_is_media`
  - `test_sync_files_blocking_returns_true_on_success`
  - `test_sync_files_blocking_logs_errors_on_failure`
**G2**: Implement `_sync_files_blocking(self, project, tag, file_names)` from reference commit's `sync_files` logic (using `_sync_blocking`).
**G3**: Green + confirm.

### Block H — Full suite validation

**H1**: Run `pytest tests/test_cuems_deploy.py tests/test_cuems_deploy_integration.py -v` — all green.
**H2**: Run `ruff check src/cuemsengine/tools/CuemsDeploy.py` — no lint errors.
**H3**: Confirm `test_rsync_password_not_in_method_bodies` still passes (password must not appear in `_sync_blocking` body — use `self._RSYNC_PASSWORD`).

---

## Key Invariants

1. `_sync`, `_kill`, `_pump`, `_deploy_all_async`, `_check_mandatory_sources` — zero modifications.
2. `sync_files` public signature — unchanged: `sync_files(project, tag, file_names=[])`.
3. `self.errors` — cleared on success, populated on failure, on **both** paths.
4. `_RSYNC_PASSWORD` — referenced as `self._RSYNC_PASSWORD` in `_sync_blocking`; password literal must remain appearing exactly once in source (`test_rsync_password_constant_defined` guards this).
5. `is_async` defaults to `False` — no event loop required by default.
