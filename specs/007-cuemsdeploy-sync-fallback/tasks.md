# Tasks: CuemsDeploy Sync/Async Branching

**Input**: Design documents from `specs/007-cuemsdeploy-sync-fallback/`
**Prerequisites**: plan.md ✓, spec.md ✓, data-model.md ✓

**TDD is NON-NEGOTIABLE** (constitution §II). Every new production method has failing tests written and confirmed before implementation. Existing tests are updated only after their target behavior is fully implemented.

**Organization**: Foundational (routing infrastructure + refactor) → US1 (blocking path, P1 MVP) → US2 (async path documented, P2) → US3 (API surface verified, P3) → Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other [P] tasks in the same phase
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3)

---

## Phase 1: Setup — Baseline Verification

**Purpose**: Confirm the full test suite is green before any changes. This is the Red-Green-Refactor safety net.

- [X] T001 Run `pytest tests/test_cuems_deploy.py tests/test_cuems_deploy_integration.py -v` and confirm all tests pass with zero failures

---

## Phase 2: Foundational — Constructor Parameter, Imports, and Routing Dispatcher

**Purpose**: Introduce `is_async` parameter, restructure `sync_files` into a dispatcher, and refactor the current async body into `_sync_files_async`. The `_sync_files_blocking` stub preserves enough guards so all existing tests remain green. No user-story code starts until this phase is complete.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Add `import fcntl`, `import selectors`, `import time` to the top-level import block in `src/cuemsengine/tools/CuemsDeploy.py` (alongside existing imports)

- [X] T003 [P] Write failing test `test_constructor_accepts_is_async_false_default` in `tests/test_cuems_deploy.py`: construct `CuemsDeploy(controller_ip='10.0.0.1')` without `is_async` arg and assert `d._is_async is False`

- [X] T004 [P] Write failing test `test_constructor_accepts_is_async_true` in `tests/test_cuems_deploy.py`: construct `CuemsDeploy(controller_ip='10.0.0.1', is_async=True)` and assert `d._is_async is True`

- [X] T005 Confirm T003 and T004 fail, then implement: add `is_async: bool = False` as the last parameter in `CuemsDeploy.__init__()` in `src/cuemsengine/tools/CuemsDeploy.py` and store `self._is_async = is_async` — confirm T003 and T004 now pass

- [X] T006 [P] Write failing tests `test_sync_files_routes_to_blocking_when_is_async_false` and `test_sync_files_routes_to_async_when_is_async_true` in `tests/test_cuems_deploy.py`: patch `_sync_files_blocking` and `_sync_files_async` as `MagicMock`, assert the correct one is called based on `_is_async` flag

- [X] T007 Confirm T006 fails, then implement the dispatcher refactor in `src/cuemsengine/tools/CuemsDeploy.py`: (a) reduce `sync_files` body to `if self._is_async: return self._sync_files_async(...) else: return self._sync_files_blocking(...)` with the `enabled` guard remaining in `sync_files` before the branch; (b) move the current `sync_files` async body verbatim into a new method `_sync_files_async(self, project, tag, file_names)`; (c) add `_sync_files_blocking(self, project, tag, file_names)` stub that raises `NotImplementedError` — confirm T006 passes

- [X] T008 Update `deploy_with_loop` fixture in `tests/test_cuems_deploy.py`: change `CuemsDeploy(controller_ip='10.0.0.1', loop=loop)` to `CuemsDeploy(controller_ip='10.0.0.1', loop=loop, is_async=True)` — this routes all 6 dependent tests through the real `_sync_files_async` implementation

- [X] T009 Update `test_sync_files_returns_false_when_loop_is_none` in `tests/test_cuems_deploy.py`: change construction to `CuemsDeploy(controller_ip='10.0.0.1', is_async=True)` — loop guard now lives in `_sync_files_async` so the assertion still holds

- [X] T010 Update `test_nng_heartbeat_not_blocked_during_deploy` in `tests/test_cuems_deploy_integration.py`: add `d._is_async = True` after the manual `__new__`-based construction of the instance — async co-existence test must route through `_sync_files_async`

- [X] T011 Run `pytest tests/test_cuems_deploy.py tests/test_cuems_deploy_integration.py -v` and confirm all existing tests pass (foundation is stable); `test_sync_blocking_*` and `test_sync_files_blocking_*` tests do not yet exist — no failures expected

**Checkpoint**: Dispatcher implemented, `_sync_files_async` extracted, `deploy_with_loop` and loop-guard test updated, full suite green. Blocking-path stub ready for US1.

---

## Phase 3: User Story 1 — Sync Deploy Without Event Loop (Priority: P1) 🎯 MVP

**Goal**: `CuemsDeploy` with `is_async=False` (default) completes a deploy synchronously using `subprocess.Popen`/`selectors`/`fcntl` — no event loop needed.

**Independent Test**: Construct `CuemsDeploy(controller_ip='10.0.0.1')` (no loop, no `is_async=True`), call `sync_files('proj', 'project')` with a mocked subprocess, and verify the call returns `True` without any event-loop error.

### `_kill_blocking` (TDD)

- [X] T012 [P] [US1] Write failing test `test_kill_blocking_is_not_coroutine` in `tests/test_cuems_deploy.py`: assert `asyncio.iscoroutinefunction(CuemsDeploy._kill_blocking)` is `False`

- [X] T013 [P] [US1] Write failing test `test_kill_blocking_terminates_then_waits` in `tests/test_cuems_deploy.py`: construct a `MagicMock` proc with `wait` returning normally; call `d._kill_blocking(proc)` and assert `proc.terminate` was called followed by `proc.wait(timeout=2)`

- [X] T014 [P] [US1] Write failing test `test_kill_blocking_escalates_to_kill_on_timeout` in `tests/test_cuems_deploy.py`: configure `proc.wait` to raise `subprocess.TimeoutExpired` on first call; assert `proc.kill()` is subsequently called

- [X] T015 [US1] Confirm T012–T014 fail, then implement `_kill_blocking(self, proc: subprocess.Popen) -> None` in `src/cuemsengine/tools/CuemsDeploy.py` from the reference commit (`proc.terminate()` → `proc.wait(timeout=2)` → `subprocess.TimeoutExpired` → `proc.kill()` → `proc.wait(timeout=2)`) — confirm T012–T014 pass

### `_sync_blocking` (TDD)

- [X] T016 [P] [US1] Write failing test `test_sync_blocking_is_not_coroutine` in `tests/test_cuems_deploy.py`: assert `asyncio.iscoroutinefunction(CuemsDeploy._sync_blocking)` is `False`

- [X] T017 [P] [US1] Write failing test `test_sync_blocking_includes_correct_rsync_flags` in `tests/test_cuems_deploy.py`: patch `subprocess.Popen` to capture the `cmd` argument; call `d._sync_blocking(str(log_file))`; assert `cmd` contains `'rsync'`, `'-rt'`, `'--contimeout=2'`, `'--timeout=5'`, `'--ignore-missing-args'`, `'--info=progress2,name0'`, `'--delete'`, `'--delete-delay'`

- [X] T018 [P] [US1] Write failing test `test_sync_blocking_returns_true_on_zero_exit` in `tests/test_cuems_deploy.py`: patch `subprocess.Popen` with a mock that closes stdout/stderr immediately and returns `rc=0` via `wait()`; assert `d._sync_blocking(log_file)` returns `True` and `d.errors == []`

- [X] T019 [P] [US1] Write failing test `test_sync_blocking_returns_false_on_nonzero_exit` in `tests/test_cuems_deploy.py`: mock proc emits a stderr line then closes with `rc=10`; assert `_sync_blocking` returns `False` and `d.errors` contains the stderr content

- [X] T020 [P] [US1] Write failing test `test_sync_blocking_startup_deadline_fires` in `tests/test_cuems_deploy.py`: monkeypatch `_STARTUP_DEADLINE_S=0.05`, `_INACTIVITY_S=0.05`; mock `subprocess.Popen` with pipes that block forever (simulate with `select` never returning events); assert result is `False` and `d.errors` contains `'startup deadline'`

- [X] T021 [P] [US1] Write failing test `test_sync_blocking_inactivity_fires_after_first_chunk` in `tests/test_cuems_deploy.py`: monkeypatch watchdog constants to `0.05s`; mock proc emits one stdout chunk then blocks; assert result is `False` and `d.errors` contains `'inactivity threshold'`

- [X] T022 [US1] Confirm T016–T021 fail, then implement `_sync_blocking(self, path: str) -> bool` in `src/cuemsengine/tools/CuemsDeploy.py` (restored from commit `5b4eb4697e`): `subprocess.Popen` + `fcntl O_NONBLOCK` on both pipes + `selectors.DefaultSelector` event loop + startup-deadline / inactivity watchdog calling `self._kill_blocking(proc)` — confirm T016–T021 pass

### `_sync_files_blocking` (TDD)

- [X] T023 [P] [US1] Write failing test `test_sync_files_blocking_returns_false_when_disabled` in `tests/test_cuems_deploy.py`: construct disabled instance (`controller_ip=None`); call `d._sync_files_blocking('proj', 'project', [])` directly; assert `False`

- [X] T024 [P] [US1] Write failing test `test_sync_files_blocking_does_not_require_loop` in `tests/test_cuems_deploy.py`: construct `CuemsDeploy(controller_ip='10.0.0.1')` (no loop); patch `_sync_blocking` to return `True`; patch `_create_deploy_log` to return `True`; patch `_reset_deploy_log`; call `d._sync_files_blocking('proj', 'project', [])` and assert `True` with no event-loop exception

- [X] T025 [P] [US1] Write failing test `test_sync_files_blocking_defaults_project_files_for_project_tag` in `tests/test_cuems_deploy.py`: patch `_create_deploy_log` to capture `file_names`; call `_sync_files_blocking('proj', 'project', [])` with no explicit files; assert captured list contains `/projects/proj/script.xml` path

- [X] T026 [P] [US1] Write failing test `test_sync_files_blocking_expands_media_files_for_media_tag` in `tests/test_cuems_deploy.py`: patch `_create_deploy_log` to capture `file_names`; call `_sync_files_blocking('proj', 'media', ['clip.mp4'])` ; assert captured list contains `media/clip.mp4` and `media/indexes/clip.mp4.idx`

- [X] T027 [P] [US1] Write failing test `test_sync_files_blocking_returns_true_on_success` in `tests/test_cuems_deploy.py`: patch `_sync_blocking` to return `True`, `_create_deploy_log` to return `True`, `_reset_deploy_log`; call `_sync_files_blocking` and assert `True`

- [X] T028 [P] [US1] Write failing test `test_sync_files_blocking_logs_errors_on_failure` in `tests/test_cuems_deploy.py`: patch `_sync_blocking` to return `False` with `d.errors=['fake error']`; `_create_deploy_log` to return `True`; assert `_sync_files_blocking` returns `False` and errors are logged

- [X] T029 [P] [US1] Write failing test `test_sync_files_blocking_does_not_call_check_mandatory_sources` in `tests/test_cuems_deploy.py`: patch `_check_mandatory_sources` as `MagicMock`; patch `_sync_blocking` to return `True`, `_create_deploy_log` to return `True`, `_reset_deploy_log`; call `_sync_files_blocking('proj', 'project', [])`; assert `_check_mandatory_sources.call_count == 0` — FR-012 regression guard

- [X] T030 [US1] Confirm T023–T029 fail, then implement `_sync_files_blocking(self, project, tag, file_names)` in `src/cuemsengine/tools/CuemsDeploy.py`: `enabled` guard → file-name expansion (`_project_files` or `_media_files`) → `_deploy_log_path` → `_create_deploy_log` → `_sync_blocking` → `_reset_deploy_log` on success / log errors on failure — confirm T023–T029 pass

**Checkpoint**: US1 complete. `CuemsDeploy(controller_ip='10.0.0.1')` with default `is_async=False` can deploy synchronously without any event loop.

---

## Phase 4: User Story 2 — Async Path Preserved (Priority: P2)

**Goal**: `CuemsDeploy` with `is_async=True` behaves identically to the pre-refactor async implementation. All 6 `deploy_with_loop`-dependent tests and the integration test pass.

**Independent Test**: Bind a real event loop to a `CuemsDeploy(is_async=True)` instance, mock `asyncio.create_subprocess_exec` to return a successful fake proc, call `sync_files('proj', 'project')`, and verify `True` is returned with the precheck exercised.

- [X] T031 [P] [US2] Write specification test `test_sync_files_async_returns_false_when_loop_unbound` in `tests/test_cuems_deploy.py`: construct `CuemsDeploy(controller_ip='10.0.0.1', is_async=True)` (no loop); call `d.sync_files('proj', 'project')` and assert `False` with `d.errors == ['event loop not bound']` — this documents the loop-guard contract on `_sync_files_async`

- [X] T032 [P] [US2] Write specification test `test_sync_files_async_errors_cleared_on_success` in `tests/test_cuems_deploy.py` using `deploy_with_loop` (which now has `is_async=True`): preload `d.errors=['stale']`; patch `_check_mandatory_sources` as `AsyncMock(return_value=(True,[]))`, `_sync` as `AsyncMock(return_value=True)`, `_create_deploy_log` and `_reset_deploy_log`; assert result is `True` and `d.errors == []`

- [X] T033 [US2] Confirm T031–T032 pass (they should — `_sync_files_async` was fully implemented in T007); if either fails, fix `_sync_files_async` in `src/cuemsengine/tools/CuemsDeploy.py` until both pass

- [X] T034 [US2] Run all `deploy_with_loop` dependent tests to confirm they pass with `is_async=True`: `test_sync_files_fails_fast_when_project_mandatory_file_missing`, `test_sync_files_project_does_single_sync_after_mandatory_precheck`, `test_sync_files_returns_false_and_skips_sync_when_precheck_fails`, `test_sync_files_returns_true_when_precheck_and_sync_succeed`, `test_sync_files_media_tag_auto_expands_bare_names`

- [X] T035 [US2] Run the integration test `pytest tests/test_cuems_deploy_integration.py -v` and confirm `test_nng_heartbeat_not_blocked_during_deploy` passes (heartbeat intervals within ±20% of target)

**Checkpoint**: US2 complete. Async path is preserved, integration test green, all `deploy_with_loop` tests green.

---

## Phase 5: User Story 3 — Public API Surface Unchanged (Priority: P3)

**Goal**: All existing call sites compile and run without modification. Constructor gains only one trailing optional parameter; `sync_files` signature is unchanged.

**Independent Test**: Run all constructor tests and the `test_sync_files_returns_false_when_disabled` test against the modified class — zero `TypeError` exceptions.

- [X] T036 [US3] Run constructor tests (`test_constructor_with_controller_ip_is_enabled`, `test_constructor_with_none_ip_is_disabled`, `test_constructor_with_false_is_disabled`, `test_constructor_with_empty_string_is_disabled`, `test_constructor_with_hostname_falls_back_to_avahi`, `test_constructor_hostname_avahi_failure_is_disabled`, `test_controller_ip_takes_precedence_over_hostname`) and assert all pass with zero `TypeError` from the new `is_async` parameter

- [X] T037 [US3] Verify `test_sync_files_returns_false_when_disabled` passes: construct `CuemsDeploy(controller_ip=None)` (default `is_async=False`), call `sync_files('proj', 'project')`, assert `False` — the disabled guard fires in `sync_files` before reaching the dispatcher

**Checkpoint**: All three user stories independently functional and verified.

---

## Phase N: Polish & Cross-Cutting Concerns

- [X] T038 Run `ruff check src/cuemsengine/tools/CuemsDeploy.py` and fix any reported lint errors (unused imports, line-length violations, etc.)

- [X] T039 Verify `test_rsync_password_not_in_method_bodies` passes: the test inspects `_sync` and `_check_mandatory_sources` source for the password literal — it must not find `f48t5eL2kLHw2Wfw` there; also verify `_sync_blocking` source does not contain the literal (uses `self._RSYNC_PASSWORD`) — enforces FR-013

- [X] T040 [P] Verify `test_rsync_password_constant_defined` passes: password literal appears exactly once in the full class source (as the `ClassVar` assignment only) — enforces FR-013

- [X] T041 Run full suite `pytest tests/test_cuems_deploy.py tests/test_cuems_deploy_integration.py -v` — zero failures, no regressions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories**
- **US1 (Phase 3)**: Depends on Foundational completion — can begin independently
- **US2 (Phase 4)**: Depends on Foundational completion — can begin after Phase 3 (T007–T011 are also prerequisites since `_sync_files_async` is real after T007)
- **US3 (Phase 5)**: Depends on US1 and US2 completion
- **Polish (Phase N)**: Depends on all user stories complete

### Within Phase 3 (US1)

```
T012–T014 [P] → T015      (_kill_blocking: tests → impl)
T016–T021 [P] → T022      (_sync_blocking: tests → impl)  ← depends on T015
T023–T029 [P] → T030      (_sync_files_blocking: tests → impl)  ← depends on T022
```

### Parallel Opportunities

**Phase 2**: T003, T004 can run in parallel (both are write-only to tests/).
**Phase 3**: Within each group (T012–T014, T016–T021, T023–T029), all `[P]`-marked test-writing tasks are independent and can be written in parallel. Each group's implementation task (T015, T022, T030) is sequential within its group.
**Phase 4**: T031, T032 can be written in parallel.
**Polish**: T039, T040 can run in parallel.

---

## Parallel Example: Phase 3 (US1)

```bash
# Write all _kill_blocking tests together (no file conflicts):
Task T012: test_kill_blocking_is_not_coroutine
Task T013: test_kill_blocking_terminates_then_waits
Task T014: test_kill_blocking_escalates_to_kill_on_timeout

# Then implement (sequential):
Task T015: implement _kill_blocking

# Write all _sync_blocking tests together:
Task T016–T021: six test functions, all in tests/test_cuems_deploy.py

# Then implement (sequential):
Task T022: implement _sync_blocking
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Baseline (T001)
2. Complete Phase 2: Foundational (T002–T011) — CRITICAL
3. Complete Phase 3: US1 (T012–T030) — blocking path done
4. **STOP and VALIDATE**: `CuemsDeploy(controller_ip='...')` deploys synchronously without an event loop
5. Ship if ready

### Incremental Delivery

1. Phase 1 + Phase 2 → Routing infrastructure ready
2. Phase 3 (US1) → Blocking path works; default callers unblocked → MVP
3. Phase 4 (US2) → Async path documented and verified → Full feature
4. Phase 5 (US3) → API contract confirmed → Ready for merge
5. Phase N → Polish → PR-ready

---

## Notes

- `[P]` tasks touch different test functions — no file conflicts within a group
- Tests marked `[P]` within Phase 3 groups can all be written in a single edit pass
- Every `implement` task (T015, T022, T030, T033) must follow **confirmed failure** of its preceding test tasks — constitution §II
- `_sync_blocking` mock strategy: patch `subprocess.Popen` at the call site; use `fcntl` patching or pre-write a `bytes` mock for `os.read`; consider `selectors.DefaultSelector` mock returning controlled events
- Password literal guard (T039–T040): `inspect.getsource(CuemsDeploy._sync_blocking)` must not contain `f48t5eL2kLHw2Wfw` (FR-013)
