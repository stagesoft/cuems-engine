# Feature Specification: CuemsDeploy Sync/Async Branching

**Feature Branch**: `007-cuemsdeploy-sync-fallback`
**Created**: 2026-05-22
**Status**: Draft
**Input**: User description: "Using CuemsDeploy.py, undergo a partial regression to allow for a branched decision recovering the previous subprocess logic. The goal is to obtain complete backcompatibility instead of relying on asynchronous code. Class instantiation can be kept as is. Modified class MUST keep actual asyncio logic, keep actual public surface with sync_files method, add a new parameter at last position is_async: bool = False, internal logic must branch sync_files logic based on this parameter, use internal methods for clear and clean internal branching."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Backward-compatible sync deploy without an event loop (Priority: P1)

A node engine that has not yet started an asyncio event loop (or does not use one at all) needs to deploy project or media files to a remote node. It calls `CuemsDeploy` with the default `is_async=False` (or omits the parameter entirely) and invokes `sync_files()`. The operation must complete entirely within the calling thread, with no dependency on an event loop, returning `True` on success or `False` with populated `self.errors` on failure.

**Why this priority**: This is the primary backward-compatibility requirement. Existing call sites that predate the async refactor must continue to work without modification.

**Independent Test**: Instantiate `CuemsDeploy(controller_ip=..., is_async=False)` with no event loop present, call `sync_files('myproject', 'project')`, and verify that the call returns a boolean result and populates `self.errors` appropriately — with no `RuntimeError` about missing event loops.

**Acceptance Scenarios**:

1. **Given** a `CuemsDeploy` instance with `is_async=False` and no event loop bound, **When** `sync_files('proj', 'project')` is called, **Then** it completes synchronously, returns `True` or `False`, and never raises a loop-related exception.
2. **Given** a `CuemsDeploy` instance constructed without the `is_async` argument (default), **When** `sync_files()` is called, **Then** behavior is identical to the pre-async version (commit `5b4eb4697e`).
3. **Given** rsync fails during a sync-path deploy, **When** `sync_files()` returns `False`, **Then** `self.errors` contains at least one diagnostic string.
4. **Given** `CuemsDeploy` is disabled (no controller IP), **When** `sync_files()` is called with `is_async=False`, **Then** it returns `False` and logs an error without attempting subprocess I/O.

---

### User Story 2 - Async deploy with event loop bound (Priority: P2)

A node engine that has started its asyncio loop (via `NodeEngine.start()`) and has bound `deploy_manager.loop` wants to deploy files. It instantiates `CuemsDeploy` with `is_async=True` and calls `sync_files()`, which must follow the current async code path (`run_coroutine_threadsafe` → `_deploy_all_async`), preserving all existing behaviour.

**Why this priority**: The async path is the active production path for fully-started node engines. It must not regress.

**Independent Test**: Instantiate `CuemsDeploy(controller_ip=..., is_async=True)`, bind a running event loop to `.loop`, call `sync_files()`, and verify the result matches the current async implementation.

**Acceptance Scenarios**:

1. **Given** a `CuemsDeploy` instance with `is_async=True` and a bound event loop, **When** `sync_files()` is called, **Then** it submits `_deploy_all_async()` via `run_coroutine_threadsafe` and blocks until completion.
2. **Given** `is_async=True` and `self.loop is None`, **When** `sync_files()` is called, **Then** it returns `False` with an "event loop not bound" error (preserving current guard).
3. **Given** the mandatory project-file precheck fails with `is_async=True`, **When** `sync_files()` is called, **Then** it returns `False` without invoking the full rsync transfer.

---

### User Story 3 - Shared public API surface unchanged (Priority: P3)

Any caller that imports and uses `CuemsDeploy` must not require changes. The constructor signature gains `is_async` only at the last position (keyword-safe), and `sync_files(project, tag, file_names)` retains its exact current signature.

**Why this priority**: Interface stability is a hard constraint — all existing callers would otherwise need auditing and modification.

**Independent Test**: Run the existing call sites / tests against the modified class without altering imports or call signatures, and verify no `TypeError` is raised.

**Acceptance Scenarios**:

1. **Given** existing code that calls `CuemsDeploy(library_path=..., controller_ip=...)` without `is_async`, **When** it is executed against the modified class, **Then** it constructs successfully with `is_async=False` default.
2. **Given** existing code that calls `sync_files(project, tag)` or `sync_files(project, tag, file_names)`, **When** executed against the modified class, **Then** it behaves identically to the pre-modification version.

---

### Edge Cases

- What happens when `is_async=False` and the rsync process hangs beyond the startup or inactivity deadline? The synchronous path must apply the same watchdog constants (`_STARTUP_DEADLINE_S`, `_INACTIVITY_S`) as the reference commit.
- What happens when `is_async=True` is passed but `self.loop` is later unbound (set back to `None`)? The existing guard in the async path already handles this; it must not be removed.
- What happens when `is_async` is set to `True` but the calling thread is the event-loop thread itself? This is an existing limitation (deadlock risk); the spec does not change this behaviour.
- What happens with a `tag='media'` deploy on the sync path? File-name expansion via `_media_files()` must apply on the sync path identically to the async path.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `CuemsDeploy.__init__()` MUST accept `is_async: bool = False` as the last parameter, after all existing parameters including `loop`.
- **FR-002**: When `is_async=False`, `sync_files()` MUST route execution to a dedicated synchronous private method that uses `subprocess.Popen`-based I/O equivalent to commit `5b4eb4697e`; file-name expansion via `_media_files` is included for parity with the async path.
- **FR-003**: When `is_async=True`, `sync_files()` MUST route execution to a dedicated private method that follows the current `run_coroutine_threadsafe` → `_deploy_all_async` path.
- **FR-004**: The public signature of `sync_files(project, tag, file_names)` MUST remain unchanged.
- **FR-005**: All existing async methods (`_sync`, `_kill`, `_pump`, `_deploy_all_async`, `_check_mandatory_sources`) MUST be retained without modification.
- **FR-006**: The synchronous path MUST implement its own private `_sync` equivalent (e.g., `_sync_blocking`) that uses `selectors`-based I/O multiplexing, matching the pre-async watchdog behaviour.
- **FR-007**: The synchronous path MUST implement its own private `_kill` equivalent (e.g., `_kill_blocking`) that terminates the subprocess without requiring `await`.
- **FR-008**: Both paths MUST share all stateless helpers: `_avahi_resolve`, `_project_files`, `_media_files`, `_mandatory_paths`, `_deploy_log_path`, `_create_deploy_log`, `_reset_deploy_log`, `_parse_progress`, `_dispatch_line`.
- **FR-009**: Both paths MUST populate `self.errors` with diagnostic strings on failure and reset `self.errors = []` before returning `True` on success (do not leak errors from prior calls).
- **FR-010**: The synchronous path MUST NOT require a bound event loop. Calling `sync_files()` with `is_async=False` and `self.loop is None` MUST succeed (or fail due to rsync/network errors), not fail due to a missing loop.
- **FR-011**: Imports added for the synchronous path (`fcntl`, `selectors`, `time`) MUST be added as unconditional top-level imports alongside the existing imports.
- **FR-012**: The mandatory-source precheck (`_check_mandatory_sources`) applies only to the async path. The synchronous path MUST replicate the pre-async behaviour from commit `5b4eb4697e`, which had no such precheck.
- **FR-013**: `_RSYNC_PASSWORD` MUST remain a `ClassVar` on `CuemsDeploy`; the password literal MUST NOT appear in any method body. Both paths reference it via `self._RSYNC_PASSWORD`.

### Key Entities

- **`CuemsDeploy`**: The single class being modified. Gains `is_async` flag and two new private routing methods.
- **Synchronous path**: The set of private methods implementing blocking subprocess I/O, derived from commit `5b4eb4697e`.
- **Async path**: The existing set of async private methods. Unchanged.
- **Routing layer**: The private methods that `sync_files()` delegates to based on `is_async`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All existing call sites of `CuemsDeploy` compile and run without modification after the change is applied.
- **SC-002**: The watchdog constants `_STARTUP_DEADLINE_S` (10) and `_INACTIVITY_S` (15) used by the synchronous path match the reference commit values, verified by unit tests.
- **SC-003**: A `CuemsDeploy` instance with `is_async=True` produces identical results to the current implementation for every input.
- **SC-004**: No new entries are added to `pyproject.toml` runtime dependencies; all new imports come from the Python standard library.
- **SC-005**: The test suite passes for both `is_async=False` and `is_async=True` paths independently, with no shared state leaking between test runs.

## Assumptions

- The synchronous fallback path is a direct restoration of the `_sync()` and `_kill()` methods as they existed at commit `5b4eb4697e938e22756aa5ded6b12c4152f61bce`, renamed to distinguish them from the async variants.
- The `loop` parameter introduced in the async refactor is retained in `__init__` and is irrelevant (but harmless) when `is_async=False`.
- The mandatory project-file precheck (`_check_mandatory_sources`) was introduced as part of the async refactor and is not present in the reference commit; the sync path does not need it.
- `fcntl` is available on all target platforms (Linux-only deployment context).
- Callers are responsible for passing the correct `is_async` value; no runtime detection of loop availability is performed by `sync_files()`.
- The `_RSYNC_PASSWORD` class variable and rsync command flags are shared between both paths.
