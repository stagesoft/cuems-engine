# Tasks: Action Cue Execution

**Input**: Design documents from `/specs/002-action-cue-handler/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Include automated test tasks for every behavior change. Tests MUST be
developed and executed via Poetry-managed `pytest` (`poetry run pytest`).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: Prepare the cue-handling layer for action cue execution changes.

- [ ] T001 Verify existing test suite passes with `poetry run pytest -q`
- [ ] T002 [P] Review `cuemsutils.ActionCue` data contract fields (`action_type`, `action_target`, `_action_target_object`) from cuemsutils package

**Checkpoint**: Baseline green. Existing behavior confirmed before changes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the centralized action execution method to `CueHandler` that all user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T003 Add `execute_action` method to `CueHandler` in src/cuemsengine/cues/CueHandler.py that accepts an `ActionCue` and delegates to per-action-type handling with result logging
- [ ] T004 Replace the dead-code `run_actionCue` body in src/cuemsengine/cues/run_cue.py so it delegates to `CUE_HANDLER.execute_action(cue, mtc)` instead of the current unreachable branching after `pass`
- [ ] T005 Confirm `initial_cuelist_process` in src/cuemsengine/core/BaseEngine.py still resolves `_action_target_object` for every `ActionCue` before action execution

**Checkpoint**: Foundation ready — `run_actionCue` routes to `CueHandler.execute_action`, and all user stories can now be implemented inside that method.

---

## Phase 3: User Story 1 — Execute cue-level actions (Priority: P1) 🎯 MVP

**Goal**: Supported cue-level action types produce the correct state transition on the target cue.

**Independent Test**: Send each supported cue-level action while a project is loaded and verify target cue state changes without affecting unrelated cues.

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T006 [P] [US1] Unit test for `play` action: target cue enters running state, in tests/test_action_cue.py
- [ ] T007 [P] [US1] Unit test for `pause` action: target cue enters paused state, in tests/test_action_cue.py
- [ ] T008 [P] [US1] Unit test for `stop` action: target cue exits running state, in tests/test_action_cue.py
- [ ] T009 [P] [US1] Unit test for `enable` action: target cue becomes enabled, in tests/test_action_cue.py
- [ ] T010 [P] [US1] Unit test for `disable` action: target cue becomes disabled, in tests/test_action_cue.py
- [ ] T011 [P] [US1] Unit test for `fade-in` action: target ramps into active state, in tests/test_action_cue.py
- [ ] T012 [P] [US1] Unit test for `fade-out` action: target ramps down and exits active state, in tests/test_action_cue.py
- [ ] T013 [P] [US1] Unit test for `go-to` action: execution pointer navigates to target cue, in tests/test_action_cue.py
- [ ] T014 [P] [US1] Unit test for idempotent repeat: same action on same target produces no harmful side effect, in tests/test_action_cue.py
- [ ] T015 [P] [US1] Unit test for non-target isolation: unrelated armed cues remain unchanged after action, in tests/test_action_cue.py
- [ ] T016 [P] [US1] Unit test for rapid succession: multiple actions targeting the same cue in quick sequence produce stable final state, in tests/test_action_cue.py

### Implementation for User Story 1

- [ ] T017 [US1] Implement `play` action handler inside `CueHandler.execute_action` in src/cuemsengine/cues/CueHandler.py
- [ ] T018 [US1] Implement `pause` action handler in src/cuemsengine/cues/CueHandler.py
- [ ] T019 [US1] Implement `stop` action handler in src/cuemsengine/cues/CueHandler.py
- [ ] T020 [P] [US1] Implement `enable` and `disable` action handlers in src/cuemsengine/cues/CueHandler.py
- [ ] T021 [US1] Implement `fade-in` action handler in src/cuemsengine/cues/CueHandler.py
- [ ] T022 [US1] Implement `fade-out` action handler in src/cuemsengine/cues/CueHandler.py
- [ ] T023 [US1] Implement `go-to` action handler in src/cuemsengine/cues/CueHandler.py
- [ ] T024 [US1] Add structured result logging for each action outcome (applied / applied_no_change / rejected / failed) in src/cuemsengine/cues/CueHandler.py
- [ ] T025 [US1] Validate all US1 tests pass with `poetry run pytest -q tests/test_action_cue.py`

**Checkpoint**: All 8 supported cue-level actions work and are independently verified. Unrelated cues are unaffected.

---

## Phase 4: User Story 2 — Handle unsupported or invalid actions safely (Priority: P2)

**Goal**: Invalid action commands fail safely with no unintended state change and clear logging.

**Independent Test**: Send invalid action types and malformed targets; verify safe rejection and stable playback state.

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T026 [P] [US2] Unit test for unknown `action_type`: rejected with no state mutation, in tests/test_action_cue.py
- [ ] T027 [P] [US2] Unit test for missing `_action_target_object`: rejected safely, in tests/test_action_cue.py
- [ ] T028 [P] [US2] Unit test for action targeting cue from inactive project: rejected safely, in tests/test_action_cue.py

### Implementation for User Story 2

- [ ] T029 [US2] Add unknown-action-type guard with clear log message in `CueHandler.execute_action` in src/cuemsengine/cues/CueHandler.py
- [ ] T030 [US2] Add missing-target guard with clear log message in `CueHandler.execute_action` in src/cuemsengine/cues/CueHandler.py
- [ ] T031 [US2] Validate all US2 tests pass with `poetry run pytest -q tests/test_action_cue.py -k invalid`

**Checkpoint**: All invalid/unsupported action paths are safely handled. Existing playback remains stable.

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories.

- [ ] T032 [P] Run full regression suite with `poetry run pytest -q` and confirm zero failures
- [ ] T033 [P] Run linting and formatting checks (`poetry run black --check src/ tests/` and `poetry run isort --check src/ tests/`)
- [ ] T034 Remove dead unreachable branching block inside `run_actionCue` in src/cuemsengine/cues/run_cue.py
- [ ] T035 [P] Verify action outcome terminology and error messages match existing show-control semantics and operator-facing logging style (NFR-003 UX consistency)
- [ ] T036 [P] Measure action-to-state reflection latency under normal show load; pass condition: ≥95% of commands reflected within 1 second (SC-004, NFR-004)
- [ ] T037 [P] Update docs/ if any action-related documentation exists in docs/cues.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **User Stories (Phase 3–4)**: All depend on Phase 2 completion
  - User stories can proceed sequentially in priority order (P1 → P2)
  - Or in parallel if staffed
- **Polish (Phase 5)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Phase 2 — no dependencies on other stories
- **User Story 2 (P2)**: Can start after Phase 2 — independent of US1

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Implementation tasks follow test tasks
- Validation task confirms all story tests pass before moving on

### Parallel Opportunities

- All test tasks within a story marked [P] can run in parallel
- Phase 1 tasks T001 and T002 can run in parallel
- Phase 5 tasks T032, T033, T035, T036, T037 can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Unit test for play action in tests/test_action_cue.py"
Task: "Unit test for pause action in tests/test_action_cue.py"
Task: "Unit test for stop action in tests/test_action_cue.py"
Task: "Unit test for enable action in tests/test_action_cue.py"
Task: "Unit test for disable action in tests/test_action_cue.py"
Task: "Unit test for fade-in action in tests/test_action_cue.py"
Task: "Unit test for fade-out action in tests/test_action_cue.py"
Task: "Unit test for go-to action in tests/test_action_cue.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Run `poetry run pytest -q tests/test_action_cue.py`
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP!)
3. Add User Story 2 → Test independently → Deploy/Demo
4. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files or independent code paths, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All test execution uses `poetry run pytest`
