# Feature Specification: CuemsDeploy Async Refactor

**Feature Branch**: `006-cuemsdeploy-async-refactor`
**Created**: 2026-05-19
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Non-blocking project deploy (Priority: P1)

When a stage operator loads a new project on a node, the deploy operation (rsync of script.xml, mappings.xml, settings.xml and media files) no longer monopolises the engine's asyncio event loop. Other engine tasks (NNG heartbeats, OSC keep-alive, watchdog ticks) continue to execute normally during a deploy.

**Why this priority**: The async migration is the primary goal of this refactor. The rsync subprocess I/O currently runs as blocking selectors inside the thread that handles NNG commands; while the NNG receiver loop itself runs unblocked (commands are dispatched to separate threads), any second command that arrives during a deploy shares the same asyncio loop resources. Making the I/O async ensures the loop is free for all other tasks.

**Independent Test**: Can be fully tested by triggering a project load while monitoring NNG heartbeat cadence — heartbeats must not stall during the rsync transfer, and the deploy must still complete successfully and return the correct success/failure status.

**Acceptance Scenarios**:

1. **Given** a project with 2 GB of media, **When** load is triggered, **Then** the deploy completes successfully and NNG/OSC communications remain responsive throughout.
2. **Given** the rsync daemon is unreachable, **When** load is triggered, **Then** the startup-deadline watchdog fires within 10 s, the deploy returns failure, and no other engine task is blocked.
3. **Given** a deploy is in progress, **When** rsync output stops for 15 s, **Then** the inactivity watchdog kills rsync, the deploy returns failure with a descriptive error.

---

### User Story 2 — Stale-file cleanup at destination (Priority: P2)

When a project is loaded onto a node that previously ran a different project, files that are no longer needed are automatically removed from the node's library, keeping disk usage bounded without manual intervention.

**Why this priority**: Without cleanup, the node's library grows without bound across projects. `--delete-delay` defers removal until after the transfer completes, making the operation safe (no partial deletes mid-transfer).

**Independent Test**: Can be fully tested by loading project A (with file X), then loading project B (without file X) — file X must be absent from the node library after the second deploy.

**Acceptance Scenarios**:

1. **Given** file X exists locally and is not in the source file list for the new project, **When** sync completes, **Then** file X is absent from the local directory.
2. **Given** the source is unreachable, **When** sync fails, **Then** no local files are deleted (rsync exits before the delete phase).
3. **Given** `--ignore-missing-args` is in effect and some listed files don't exist at source, **When** sync runs, **Then** those missing-at-source files are skipped (not deleted locally), while genuinely stale files not in the list are removed.

---

### User Story 3 — Centralised rsync credential management (Priority: P3)

The rsync password appears in exactly one place in the codebase. Rotating the credential, auditing its use, or moving it to a secrets manager in future requires editing a single constant.

**Why this priority**: Low-risk, high-value housekeeping. The password is currently duplicated in two methods; a future rotation would silently leave one copy stale.

**Independent Test**: Can be fully tested by grepping the file for the password string — it must appear exactly once (the constant definition), with all call sites referencing the constant name.

**Acceptance Scenarios**:

1. **Given** the module is loaded, **When** any rsync subprocess is spawned, **Then** all calls use the same module-level constant for the password.
2. **Given** the constant is updated, **When** the module is reloaded, **Then** both the mandatory-precheck call and the main sync call pick up the new value.

---

### User Story 4 — Consolidated media-path logic (Priority: P4)

The path-construction rules for media files (`media/<name>`, `media/indexes/<name>.idx`, video-extension set) live inside `CuemsDeploy` alongside the existing `_project_files()` and `_mandatory_paths()` helpers, so `NodeEngine` is not responsible for knowing the controller's library layout.

**Why this priority**: `NodeEngine.deploy_media()` currently embeds rsync-module path knowledge that belongs to the deploy layer. Keeping it in `NodeEngine` creates a coupling that would need updating whenever the library layout changes.

**Independent Test**: Can be fully tested by calling the new `CuemsDeploy._media_files()` helper directly with a list of bare filenames and asserting the expected prefixed paths are returned.

**Acceptance Scenarios**:

1. **Given** a list of bare media filenames, **When** `CuemsDeploy._media_files(bare_names)` is called, **Then** it returns entries prefixed with `media/` and, for video files, corresponding `media/indexes/<name>.idx` entries.
2. **Given** `NodeEngine.deploy_media()` is invoked, **Then** it delegates path construction to `CuemsDeploy._media_files()` without duplicating the `media/` prefix logic or the video-extension set.

---

### Edge Cases

- What happens when the rsync module address is `None` (deploy disabled)? `sync_files()` must return `False` immediately without scheduling any subprocess.
- How does `--delete-delay` interact with `--files-from` when the listed files span multiple subdirectories? Deletions apply only within directories that rsync traverses — files outside the synced paths are untouched.
- What happens when `sync_files()` is called before `NodeEngine.start()` has set the event loop on the deploy manager? The method must fail gracefully (log + return `False`) rather than raise.
- What happens to the mandatory-precheck call (`--list-only`)? `--delete` and `--delete-delay` must **not** be added to the precheck command (read-only probe).
- What happens when the asyncio event loop is `None` at deploy call time? `sync_files()` must detect this, log a clear error, and return `False` without attempting subprocess creation.
- What happens when `_check_mandatory_sources()` returns failure? The enclosing coroutine must return immediately — `_sync()` must not be called, no transfer is attempted, and the error is surfaced to the caller via the existing `self.errors` list.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `CuemsDeploy._sync()` MUST be an `async def` coroutine using `asyncio.create_subprocess_exec` instead of `subprocess.Popen`; all `fcntl` O_NONBLOCK setup and `selectors` usage MUST be removed.
- **FR-002**: The async implementation MUST preserve all existing watchdog semantics: startup deadline (`_STARTUP_DEADLINE_S = 10 s`) and inactivity deadline (`_INACTIVITY_S = 15 s`), driven by `asyncio.wait` with a timeout budget.
- **FR-003**: Stdout and stderr MUST be consumed by two independent `asyncio.Task` reader coroutines running concurrently; the main loop MUST use `asyncio.wait({t_out, t_err}, timeout=budget)` to drive progress and watchdog checks.
- **FR-004**: `_kill()` MUST be an `async def` coroutine using `asyncio.wait_for(proc.wait(), timeout=2.0)` with `asyncio.TimeoutError` handling in place of `subprocess.TimeoutExpired`.
- **FR-005**: The `RSYNC_PASSWORD` string MUST be defined as a single module-level constant; no inline literal occurrences may remain anywhere in the file.
- **FR-006**: The main rsync command in `_sync()` MUST include `--delete` and `--delete-delay` flags; the mandatory-precheck (`--list-only`) command in `_check_mandatory_sources()` MUST NOT include these flags.
- **FR-007**: `CuemsDeploy` MUST expose a `_media_files(bare_names: list[str]) -> list[str]` method returning rsync-relative paths (`media/<name>` for all files plus `media/indexes/<name>.idx` for video files), so `NodeEngine.deploy_media()` can delegate path construction entirely to it.
- **FR-008**: `sync_files()` MUST remain a synchronous `def` method from `NodeEngine`'s perspective. After non-I/O setup (file-list preparation, log-file creation), it MUST bridge the entire async flow — precheck followed conditionally by main sync — as a single coroutine submitted via `asyncio.run_coroutine_threadsafe`, blocking on the result. `NodeEngine` call sites are unchanged.
- **FR-009**: `CuemsDeploy.__init__` MUST accept a new optional parameter `loop: asyncio.AbstractEventLoop | None = None`. `NodeEngine.start()` MUST assign the running loop to `deploy_manager.loop` after the comms thread is started (late-bind), so the loop is guaranteed non-`None` by the time any deploy is triggered.
- **FR-010**: When `self.loop` is `None` at the time `sync_files()` is called, the method MUST log an error and return `False` without attempting to schedule any coroutine.
- **FR-011**: All existing public behaviour of `sync_files()`, `_parse_progress()`, `_dispatch_line()`, error-precedence semantics, and the `on_progress` callback contract MUST be preserved unchanged.
- **FR-012**: `_check_mandatory_sources()` MUST be refactored to `async def`, using `asyncio.create_subprocess_exec` instead of `subprocess.run`. If the precheck returns failure, the enclosing coroutine MUST return immediately without invoking `_sync()`; no main transfer is attempted on a failed precheck.

### Key Entities

- **`CuemsDeploy`**: The deploy manager class; owns all rsync subprocess lifecycle, progress parsing, watchdog logic, and library-path knowledge.
- **`RSYNC_PASSWORD`**: Module-level string constant holding the rsync daemon credential.
- **`loop`**: `asyncio.AbstractEventLoop | None` attribute on `CuemsDeploy`; late-bound by `NodeEngine.start()` after the comms thread is running.
- **`_media_files()`**: New helper encapsulating the controller library's media path layout (replaces inline logic in `NodeEngine.deploy_media()`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: During a deploy of a 1 GB media file, NNG heartbeat intervals remain within ±20% of their configured cadence with no missed beats.
- **SC-002**: After loading a project with a different media set, the node's library directory contains no files exclusive to the previous project (verified by directory listing).
- **SC-003**: The string literal `"f48t5eL2kLHw2Wfw"` appears exactly once in `CuemsDeploy.py` (the constant definition); all other references use the constant name.
- **SC-004**: The test suite passes without modification to any existing test assertions; no previously green test regresses.
- **SC-005**: `NodeEngine.deploy_media()` contains no `media/` string literals or video-extension sets; these exist only in `CuemsDeploy`.
- **SC-006**: `CuemsDeploy.py` contains no `import fcntl`, no `selectors` usage, and no `subprocess.Popen` or `subprocess.run` calls outside `_avahi_resolve()` after the refactor.

## Assumptions

- `AsyncCommsThread.event_loop` is the loop onto which deploy coroutines are submitted. It is `None` until `AsyncCommsThread.run()` is called (thread start), and is guaranteed non-`None` by the time the first NNG `load` command can arrive.
- `--delete` and `--delete-delay` apply to **all** `sync_files()` calls (both project-file and media syncs). The controller library is the single source of truth; nodes are expected to mirror it exactly.
- The `RSYNC_PASSWORD` value (`f48t5eL2kLHw2Wfw`) is intentionally kept in source for now; moving it to an environment variable or secrets manager is out of scope for this refactor.
- `NodeEngine.ensure_video_indexes()` and the thin `NodeEngine.deploy_project()` wrapper remain in `NodeEngine`; only the media path-construction logic moves to `CuemsDeploy`.
- Existing tests in `tests/test_cuems_deploy.py` are updated to mock `asyncio.create_subprocess_exec` instead of `subprocess.Popen` and `subprocess.run`; no existing test is deleted, only adapted.
- `_avahi_resolve()` retains `subprocess.run` — it is called from `__init__` before the asyncio loop exists and is a one-time cold-path resolution, not a deploy I/O operation.

## Clarifications

### Session 2026-05-19

- Q: Should `_check_mandatory_sources` be migrated to async, enabling removal of `subprocess.run` from the hot path, and should precheck failure abort `_sync()` without proceeding? → A: Yes (Option B) — migrate to `async def` using `asyncio.create_subprocess_exec`; bridge the full flow (precheck + sync) as one coroutine; early-fail if precheck returns failure, `_sync()` is never called. `_avahi_resolve()` retains `subprocess.run` (constructor constraint).
