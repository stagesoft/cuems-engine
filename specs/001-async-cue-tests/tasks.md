# Tasks: Async Cue Execution Test Suite

**Input**: Design documents from `/specs/001-async-cue-tests/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

**Tests**: This feature IS a test suite. All tasks produce test code or test infrastructure.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: Create package structure for test suite and reusable helpers

- [X] T001 [P] Create `tests/async_helpers/` package with `tests/async_helpers/__init__.py`
- [X] T002 [P] Create `tests/async_cue/` package with `tests/async_cue/__init__.py`

---

## Phase 2: Foundational (Reusable Test Components)

**Purpose**: Build all reusable mock factories, fixtures, and assertion helpers that EVERY user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

**Constitution compliance**: All modules MUST include a docstring stating their single responsibility. All public functions and classes MUST have type-annotated signatures.

- [X] T003 [P] Implement `MockCueFactory` in `tests/async_helpers/factories.py` — parametric builder for AudioCue, VideoCue, ActionCue, CueList mocks with configurable `id`, `loaded`, `enabled`, `prewait`, `postwait`, `loop`, `post_go`, `_target_object`, `_local`, `_osc`, `_start_mtc`, `_end_mtc`, `contents` attributes. Must use `unittest.mock.MagicMock` with correct `spec` for each cue type from `cuemsutils.cues`. Presets: `MockCueFactory.audio()`, `.video()`, `.action()`, `.cuelist(contents=[...])`.
- [X] T004 [P] Implement `EventLoopFixture` in `tests/async_helpers/loops.py` — `start()` creates a new `asyncio.new_event_loop()` in a daemon thread running `loop.run_forever()`, returns `(loop, thread)`. `stop(loop, thread)` calls `loop.call_soon_threadsafe(loop.stop)` then `thread.join(timeout=2)`. Supports creating dual loops (IPC + cue) to mimic AsyncCommsThread architecture.
- [X] T005 [P] Implement `MockMtcListener` in `tests/async_helpers/mtc.py` — controllable MTC time source with `main_tc` attribute (CTimecode). Methods: `advance_to(tc_string)`, `advance_by(milliseconds)`. Must support `framerate` parameter. No real MIDI hardware.
- [X] T006 [P] Implement `MockOscClient` in `tests/async_helpers/osc.py` — records all `set_value(key, value)` calls in an ordered list. Provides `get_calls() → list[tuple[str, Any]]`, `get_value(key) → Any`, `get_node(key)` returning a mock with `.parameter.value`. No network I/O.
- [X] T007 [P] Implement `MockPlayerHandler` in `tests/async_helpers/players.py` — stub that tracks `store_cue_player()`, `remove_cue_player()`, `get_cue_player()` calls. `new_audio_output()` and `set_video_player()` record calls without spawning subprocesses. Thread-safe via `threading.Lock`.
- [X] T008 [P] Implement `LifecycleAssertions` in `tests/async_helpers/assertions.py` — reusable assertion functions: `assert_lifecycle_completed(cue)` (loaded→armed→running→idle), `assert_timing_budget(elapsed_ms, budget_ms)`, `assert_resources_released(cue, player_handler_mock)` (no leaked players/OSC clients), `assert_loop_identity(expected_loop)` (coroutine verifying `asyncio.get_running_loop() is expected_loop`).
- [X] T009 Implement shared fixtures in `tests/async_cue/conftest.py` — compose `async_helpers` into pytest fixtures: `reset_singletons` (autouse, sets `CueHandler._instance = None` and `PlayerHandler._instance = None`), `mock_audio_cue`, `mock_video_cue`, `mock_action_cue`, `mock_cuelist_cue` (from `MockCueFactory`), `cue_loop` (from `EventLoopFixture.start()`), `ipc_loop` (second loop for isolation tests), `mock_mtc` (from `MockMtcListener`), `mock_osc` (from `MockOscClient`). All fixtures yield and clean up.

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Single Cue Async Lifecycle (Priority: P1) 🎯 MVP

**Goal**: Verify that a single cue progresses through its complete async lifecycle correctly for each cue type

**Independent Test**: `pytest -m unit -k "single_cue_lifecycle" tests/async_cue/`

### Implementation

- [X] T010 [US1] Test AudioCue full lifecycle: arm → go → prewait → run_cue → postwait → loop_cue → disarm. Verify `cue.loaded` transitions, `_start_mtc`/`_end_mtc` set during run, OSC `/offset` and `/mtcfollow` values sent via MockOscClient, player cleaned up after disarm. In `tests/async_cue/test_single_lifecycle.py`.
- [X] T011 [US1] Test VideoCue full lifecycle: arm → go → prewait → run_cue → postwait → loop_cue → disarm. Verify OSC `/jadeo/offset` and `/jadeo/cmd` values sent, video player toggling behavior, MTC disconnect on loop exit. In `tests/async_cue/test_single_lifecycle.py`.
- [X] T012 [US1] Test ActionCue lifecycle for action types `load`, `unload`, `play`, `enable`, `disable`. Verify each action dispatches to the correct CueHandler method on the target object. In `tests/async_cue/test_single_lifecycle.py`.
- [X] T012b [US1] Test CueList lifecycle: arm → go → run_cue triggers `go()` on first child cue in `contents`. Verify child cue is scheduled on the cue orchestration loop. In `tests/async_cue/test_single_lifecycle.py`.
- [X] T013 [US1] Test prewait enforcement: VideoCue with `prewait=100ms` — assert `run_cue()` is not invoked until ≥100ms after `go()`. Use `time.monotonic()` delta. In `tests/async_cue/test_single_lifecycle.py`.
- [X] T014 [US1] Test postwait enforcement: AudioCue with `postwait=50ms` — assert `loop_cue()` is not called until ≥50ms after `run_cue()` returns. In `tests/async_cue/test_single_lifecycle.py`.
- [X] T015 [US1] Test disarm cleanup: after lifecycle completes, verify `PlayerHandler.remove_cue_player()` was called, `cue._osc` is None, `cue.loaded` is False, cue removed from `_armed_cues`. In `tests/async_cue/test_single_lifecycle.py`.
- [X] T016 [US1] Test timing budget: verify full lifecycle (go → disarm) with zero prewait/postwait completes within ≤50ms using `assert_timing_budget()`. In `tests/async_cue/test_single_lifecycle.py`.

**Checkpoint**: Single cue lifecycle verified for all 4 cue types. MVP functional.

---

## Phase 4: User Story 2 — Concurrent Cue Execution (Priority: P2)

**Goal**: Verify multiple cues execute simultaneously without blocking or corrupting shared state

**Independent Test**: `pytest -m unit -k "concurrent_cues" tests/async_cue/`

### Implementation

- [X] T017 [US2] Test three simultaneous cues (Audio + Video + Action) triggered via `go()` on the same event loop tick using `asyncio.gather()`. Verify all three complete independently, `_armed_cues` list is consistent, no shared state corruption. In `tests/async_cue/test_concurrent.py`.
- [X] T018 [US2] Test error isolation: two cues on same CueHandler, inject `RuntimeError` into one cue's `run_cue()` — verify the other cue completes its full lifecycle unaffected. In `tests/async_cue/test_concurrent.py`.
- [X] T019 [US2] Test thread-safety stress: 50 iterations × 3 concurrent threads submitting `go()` via `run_coroutine_threadsafe()` through `ThreadPoolExecutor` with `threading.Barrier` synchronization. Assert zero exceptions, armed-cues list length consistent after each iteration. In `tests/async_cue/test_concurrent.py`.
- [X] T020 [US2] Test concurrent `arm()`/`disarm()` interleaving: multiple threads calling `add_armed_cue()` and `remove_armed_cue()` simultaneously. Verify `_armed_cues` and `_armed_cues_set` remain consistent. In `tests/async_cue/test_concurrent.py`.

**Checkpoint**: Concurrency correctness verified under both async and threaded access patterns

---

## Phase 5: User Story 3 — Post-Go Chaining (Priority: P3)

**Goal**: Verify `post_go` modes chain cue execution in the correct order

**Independent Test**: `pytest -m unit -k "post_go" tests/async_cue/`

### Implementation

- [X] T021 [US3] Test `post_go='go'`: cue A finishes `run_cue()` → cue B's `go()` is invoked before cue A's postwait completes. Verify invocation order via call timestamps. In `tests/async_cue/test_post_go.py`.
- [X] T022 [US3] Test `post_go='go_at_end'`: cue A's `loop_cue()` completes → cue B's `go()` is invoked after loop exit. Verify cue B starts only after cue A's loop counter is exhausted. In `tests/async_cue/test_post_go.py`.
- [X] T023 [US3] Test `post_go='go_at_end'` with error in loop: cue A raises during `loop_cue()` → cue B is NOT triggered. Verify cue B's `go()` was never called. In `tests/async_cue/test_post_go.py`.
- [X] T024 [US3] Test auto-arm of chained cue: cue A has `_target_object` pointing to unarmed cue B → verify `go()` calls `arm()` on cue B before scheduling its task. In `tests/async_cue/test_post_go.py`.

**Checkpoint**: Post-go chaining verified for both modes plus error propagation

---

## Phase 6: User Story 4 — MTC Synchronization in Loop (Priority: P4)

**Goal**: Verify `loop_cue()` polling correctly tracks MTC, recalculates offsets, and disconnects

**Independent Test**: `pytest -m unit -k "mtc_loop" tests/async_cue/`

### Implementation

- [X] T025 [US4] Test AudioCue `loop_cue()` with `loop=3`: advance MockMtcListener past `_end_mtc` three times — verify loop counter increments toward target (3), offset recalculated each iteration via `MockOscClient.set_value('/offset', ...)`. In `tests/async_cue/test_mtc_loop.py`.
- [X] T026 [US4] Test VideoCue `loop_cue()` with `loop=2`: advance MockMtcListener past `_end_mtc` twice — verify `/jadeo/offset` recalculated, `/jadeo/cmd` `'midi disconnect'` sent on final exit. In `tests/async_cue/test_mtc_loop.py`.
- [X] T027 [US4] Test final loop iteration: on last loop, MTC reaches `_end_mtc` → verify MTC disconnected (OSC `/mtcfollow` set to 0 for audio, `/jadeo/cmd` `'midi disconnect'` for video) and coroutine returns. In `tests/async_cue/test_mtc_loop.py`.
- [X] T028 [US4] Test MTC stall resilience: set MockMtcListener.main_tc below `_end_mtc` and never advance — verify `loop_cue()` does not return or crash within 500ms (use `asyncio.wait_for` with timeout to confirm it's still polling). In `tests/async_cue/test_mtc_loop.py`.
- [X] T029 [US4] Test `loop=0` (no loop — play once, `loop_cue()` returns immediately) and `loop=-1` (infinite loop — verify `loop_cue()` keeps looping, test 3 iterations then cancel task, assert no error). In `tests/async_cue/test_mtc_loop.py`.

**Checkpoint**: MTC polling, offset recalculation, and loop counter verified for audio and video

---

## Phase 7: User Story 5 — Error Handling & Cleanup (Priority: P5)

**Goal**: Verify failures at any lifecycle phase produce error states and clean up resources

**Independent Test**: `pytest -m unit -k "error_cleanup" tests/async_cue/`

### Implementation

- [X] T030 [US5] Test player crash during `run_cue()`: mock `_osc.set_value()` to raise `ConnectionError` — verify exception logged (check `caplog`), cue disarmed, `PlayerHandler.remove_cue_player()` called. In `tests/async_cue/test_error_cleanup.py`.
- [X] T031 [US5] Test OSC connection error during arm: mock `PlayerHandler.new_audio_output()` to raise — verify cue NOT added to `_armed_cues`, `cue.loaded` remains False, no dangling OSC client. In `tests/async_cue/test_error_cleanup.py`.
- [X] T032 [US5] Test unhandled exception in `loop_cue()`: inject `RuntimeError` into MockMtcListener.main_tc property — verify asyncio task does not silently die, error is logged, cue is disarmed. In `tests/async_cue/test_error_cleanup.py`.
- [X] T033 [US5] Test asyncio task cancellation at each lifecycle phase: cancel task during prewait, during run_cue, during postwait, during loop_cue — verify resources released cleanly in each case (no leaked players, no dangling OSC). In `tests/async_cue/test_error_cleanup.py`.

**Checkpoint**: Error handling and cleanup verified for crash, connection error, exception, and cancellation scenarios

---

## Phase 8: Cross-Cutting — Event Loop Identity & Edge Cases

**Purpose**: Verify architectural constraints (FR-011/012/013/014) and edge cases

### Event Loop Identity (FR-011, FR-012, FR-014)

- [ ] T034 Test `go()` submits task to cue orchestration loop: create dual loops via `EventLoopFixture`, call `go()` with cue loop as target — inside `_go_async`, call `assert_loop_identity(cue_loop)`. Verify task does NOT run on IPC loop. In `tests/async_cue/test_loop_identity.py`.
- [X] T035 Test cross-thread submission via `run_coroutine_threadsafe()`: from main thread, submit cue coroutine to cue loop — verify `asyncio.get_running_loop()` inside coroutine matches cue loop. In `tests/async_cue/test_loop_identity.py`.
- [X] T036 Test loop isolation (FR-014): submit `asyncio.sleep(10)` to IPC loop, then submit cue task to cue loop — verify cue task completes within 50ms despite IPC loop being blocked. In `tests/async_cue/test_loop_identity.py`.

### Missing wait_for_cue (FR-013)

- [X] T037 Test `CueHandler.wait_for_cue()` does not exist: call `CUE_HANDLER.wait_for_cue(mock_task)` — assert `AttributeError` raised. Document expected signature in test docstring. In `tests/async_cue/test_wait_for_cue.py`.
- [X] T038 Test expected `wait_for_cue` contract: define the expected behavior (block calling thread until task completes) as a spec test that will pass once the method is implemented. Use `pytest.mark.xfail(reason="wait_for_cue not yet implemented")`. In `tests/async_cue/test_wait_for_cue.py`.

### Edge Cases

- [X] T039 [P] Test `go()` called on already-running cue — verify behavior (second go rejected or queued). In `tests/async_cue/test_edge_cases.py`.
- [X] T040 [P] Test `disarm()` called while async task is mid-execution — verify task is cancelled or completes gracefully, resources released. In `tests/async_cue/test_edge_cases.py`.
- [X] T041 [P] Test event loop shutdown while cues are running — verify all running tasks are cancelled and resources cleaned up. In `tests/async_cue/test_edge_cases.py`.
- [X] T042 [P] Test two cues sharing same video player pool when one errors — verify the other cue's player is not affected. In `tests/async_cue/test_edge_cases.py`.
- [X] T043 [P] Test `prewait=0` and `postwait=0` — verify `asyncio.sleep(0)` is either skipped or executes instantly without error. In `tests/async_cue/test_edge_cases.py`.
- [X] T044 [P] Test `loop=0` (no loop — `loop_cue()` exits immediately after single play) and `loop=-1` (infinite loop — `loop_cue()` continues indefinitely; run 3 iterations then cancel, assert no error). In `tests/async_cue/test_edge_cases.py`.

---

## Phase 9: Polish & Validation

**Purpose**: Code quality and final verification

- [X] T045 Run `black --check` and `isort --check` on all files in `tests/async_helpers/` and `tests/async_cue/`; fix any formatting issues
- [X] T046 Run `flake8` on all new test files; fix any warnings
- [X] T047 Verify `pytest -m unit tests/async_cue/` completes in ≤ 30s wall time
- [X] T048 Verify `pytest --cov=src/cuemsengine/cues --cov-branch --cov-report=term-missing tests/async_cue/` shows ≥ 80% branch coverage
- [X] T049 Run quickstart.md validation: execute all commands from `specs/001-async-cue-tests/quickstart.md` and verify expected outcomes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001, T002) — BLOCKS all user stories
- **User Stories (Phases 3–7)**: All depend on Foundational phase completion
  - Stories can proceed in priority order (P1 → P2 → P3 → P4 → P5)
  - US2 depends conceptually on US1 patterns but can technically start in parallel
- **Cross-Cutting (Phase 8)**: Depends on Foundational; can run in parallel with user stories
- **Polish (Phase 9)**: Depends on ALL previous phases

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — No dependencies on other stories
- **US2 (P2)**: Can start after Foundational — Reuses mock patterns from US1 but different file
- **US3 (P3)**: Can start after Foundational — Uses cue chaining, benefits from US1 patterns
- **US4 (P4)**: Can start after Foundational — Uses MockMtcListener heavily, independent scope
- **US5 (P5)**: Can start after Foundational — Uses fault injection, independent scope
- **Cross-Cutting**: Independent of user stories, only needs Foundational fixtures

### Within Each User Story

- All tests within a story can be written in sequence in a single file
- Each test function is independent (singleton reset via autouse fixture)
- Story complete = all test functions pass for that story's `-k` filter

### Parallel Opportunities

- All Setup tasks (T001, T002) can run in parallel
- All Foundational component tasks (T003–T008) can run in parallel (different files)
- All edge case tasks (T039–T044) can run in parallel (different test functions, same file)
- User stories can be parallelized across developers:
  - Developer A: US1 + US2
  - Developer B: US3 + US4
  - Developer C: US5 + Cross-Cutting

---

## Parallel Example: Foundational Phase

```bash
# All reusable components can be built simultaneously:
Task: "MockCueFactory in tests/async_helpers/factories.py"
Task: "EventLoopFixture in tests/async_helpers/loops.py"
Task: "MockMtcListener in tests/async_helpers/mtc.py"
Task: "MockOscClient in tests/async_helpers/osc.py"
Task: "MockPlayerHandler in tests/async_helpers/players.py"
Task: "LifecycleAssertions in tests/async_helpers/assertions.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T009)
3. Complete Phase 3: User Story 1 (T010–T016)
4. **STOP and VALIDATE**: `pytest -m unit -k "single_cue_lifecycle" tests/async_cue/`
5. If passing → MVP achieved

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 → Test independently → MVP! (single cue lifecycle)
3. Add US2 → Test independently (concurrent execution)
4. Add US3 → Test independently (post-go chaining)
5. Add US4 → Test independently (MTC sync)
6. Add US5 → Test independently (error handling)
7. Add Cross-Cutting → Loop identity + edge cases
8. Polish → Format, coverage, timing validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable via `pytest -k`
- Singleton reset (autouse fixture) ensures test isolation
- No new dependencies: only stdlib asyncio + existing dev deps
- All mocks use `unittest.mock` from stdlib
- Avoid: real subprocesses, real MIDI hardware, real OSC network in unit tests
