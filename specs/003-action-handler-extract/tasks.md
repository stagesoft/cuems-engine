# Tasks: Dedicated Action Handler with Extensibility

**Input**: Design documents from `/specs/003-action-handler-extract/`  
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

**Purpose**: Confirm baseline before refactor.

- [x] T001 Verify `poetry run pytest -q tests/test_action_cue.py` passes on current branch
- [x] T002 [P] Skim `specs/003-action-handler-extract/contracts/action-handler-extensibility.md` and `specs/003-action-handler-extract/research.md` for binding and hook-order decisions

**Checkpoint**: Green baseline; design decisions loaded.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Introduce `ActionHandler`, move execution logic off `CueHandler`, rewire entrypoint.

**⚠️ CRITICAL**: No user story work beyond regression lock-in until this phase completes.

- [x] T003 Create `src/cuemsengine/cues/action_handler.py` with `ActionHandler` class, `SUPPORTED_CUE_ACTIONS`, `ACTION_HANDLER` singleton, and `bind_cue_handler(...)` (or equivalent) accepting the `CueHandler` instance for `arm`/`go`/`get_armed_cue_by_id` as needed
- [x] T004 Move `execute_action`, `_handle_*` handlers, `_ACTION_HANDLERS`, and `_action_result` from `src/cuemsengine/cues/CueHandler.py` into `src/cuemsengine/cues/action_handler.py`, preserving behavior and logging semantics
- [x] T005 Strip per-action implementation from `src/cuemsengine/cues/CueHandler.py`; keep a thin `execute_action` forwarder to `ACTION_HANDLER.execute_action` **or** remove method and update all call sites (prefer single entry: `run_cue` → `ACTION_HANDLER` per `research.md` Decision 6)
- [x] T006 Update `src/cuemsengine/cues/run_cue.py` so `run_actionCue` imports and calls `ACTION_HANDLER.execute_action(cue, mtc)` from `action_handler.py`
- [x] T007 Resolve `CueHandler` ↔ `ActionHandler` import/binding order (no circular imports); initialize binding once singletons exist (e.g. end of `CueHandler.py` or lazy bind)
- [x] T008 Update `tests/test_action_cue.py` fixtures to obtain `execute_action` from `ACTION_HANDLER` with an isolated mock `CueHandler` bound per test where needed
- [x] T009 Run `poetry run pytest -q tests/test_action_cue.py` and fix failures until all pass (regression gate for US1)

**Checkpoint**: Action execution lives in `action_handler.py`; `CueHandler` no longer owns handler bodies; tests green.

---

## Phase 3: User Story 1 — No regression for live action cues (Priority: P1) 🎯 MVP

**Goal**: All supported action types and invalid paths behave like the pre-refactor baseline.

**Independent Test**: `poetry run pytest -q tests/test_action_cue.py` covers full matrix; optional manual spot-check per `quickstart.md` §2.

### Tests for User Story 1 ⚠️

> **NOTE: Baseline tests exist from feature 002; extend only if gaps appear after extract.**

- [x] T010 [P] [US1] Add regression assertion in `tests/test_action_cue.py` if outcome dict keys or log prefixes changed during extract (must match contract for operators)

### Implementation for User Story 1

- [x] T011 [US1] Re-run `poetry run pytest -q tests/test_action_cue.py` and document any intentional deviations in `specs/003-action-handler-extract/contracts/action-handler-extensibility.md` (should be none)

**Checkpoint**: US1 complete when action tests fully pass with no unexplained behavior drift.

---

## Phase 4: User Story 2 — Integrators can extend action handling (Priority: P2)

**Goal**: Thread-safe hooks, dual registration surfaces, injectable result sink, NNG-compatible default send.

**Independent Test**: Hooks fire in documented order; dual-source registration honored; sink receives outcomes when injected.

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before hook implementation**

- [x] T012 [P] [US2] Unit test: `before_dispatch` then default then `after_dispatch` order in `tests/test_action_cue.py`
- [x] T013 [P] [US2] Unit test: duplicate registration same hook+filter → last wins (FR-008) in `tests/test_action_cue.py`
- [x] T014 [P] [US2] Unit test: `cue_layer` registration applied before `node_layer` for same phase (FR-009) in `tests/test_action_cue.py`
- [x] T015 [P] [US2] Unit test: injectable result sink records outcome; default path invokes comms mock when sink unset (SC-005) in `tests/test_action_cue.py`
- [x] T016 [P] [US2] Unit test: hook raises → outcome `failed`/`rejected`, unrelated cue state unchanged in `tests/test_action_cue.py`
- [x] T016a [P] [US2] Unit test: action arrives while target is mid-transition with a hook registered → behavior is deterministic and safe (idempotent or ordered per contract, edge case §4) in `tests/test_action_cue.py`

### Implementation for User Story 2

- [x] T017 [US2] Implement thread-safe registry and hook invocation in `src/cuemsengine/cues/action_handler.py` per `contracts/action-handler-extensibility.md`
- [x] T018 [US2] Update `specs/003-action-handler-extract/contracts/action-handler-extensibility.md` with the concrete callable signature, context fields passed to hooks (action type, target identity, outcome channel), invocation order per phase, and whether `wrap_dispatch` may fully replace default handling (FR-004, SC-004, edge case §3)
- [x] T019 [US2] Implement default result sink calling `NodeCommunications.send_operation` (or thin wrapper on `src/cuemsengine/comms/NodeCommunications.py` if a dedicated helper improves clarity) plus `set_result_sink(...)` on `ActionHandler`
- [x] T020 [US2] Expose registration helpers on `src/cuemsengine/cues/CueHandler.py` forwarding to `ACTION_HANDLER` with `source=cue_layer`
- [x] T021 [US2] Invoke `ACTION_HANDLER` registration API from `src/cuemsengine/NodeEngine.py` after `set_communications` / comms ready, passing `source=node_layer` for any node-level hooks (no-op if none registered by default)
- [x] T022 [US2] Validate US2 slice: `poetry run pytest -q tests/test_action_cue.py -k "hook or sink or layer or dispatch"`

**Checkpoint**: Extensions and sinks verified; FR-003–FR-010 satisfied in code.

---

## Phase 5: User Story 3 — Clear separation of responsibilities (Priority: P3)

**Goal**: Documentation and code structure make `ActionHandler` the single owner of action-cue execution logic.

**Independent Test**: Architecture note + grep show no per-action branching left in `CueHandler`.

### Implementation for User Story 3

- [x] T023 [P] [US3] Create `docs/cues.md` if absent, then add short architecture subsection naming `ActionHandler` as owner of action cues and linking to `specs/003-action-handler-extract/contracts/action-handler-extensibility.md`
- [x] T024 [US3] Verify `src/cuemsengine/cues/CueHandler.py` contains no `_handle_play`-style action handlers; only delegation / registration forwards remain

**Checkpoint**: US3 documentation and structure review complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Repo-wide quality gates and quickstart validation.

- [x] T025 [P] Run full regression `poetry run pytest -q`
- [x] T026 [P] Run `poetry run black --check src/cuemsengine/cues/ tests/test_action_cue.py` and `poetry run isort --check` on the same paths; fix if needed
- [x] T027 [P] Add lightweight timing or call-count guard in `tests/test_action_cue.py` for SC-009; if risk is negligible for this refactor, justify with measured evidence in the PR description
- [x] T028 [P] Verify UX consistency (NFR-003 / SC-008): confirm all log messages, error strings, and outcome wording emitted by `ActionHandler` match the existing `CueHandler` output character-for-character (diff or snapshot test)
- [x] T029 [P] Execute validation steps in `specs/003-action-handler-extract/quickstart.md` and note results in PR description

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: After Phase 1 — **BLOCKS** US1–US3
- **User Story 1 (Phase 3)**: After Phase 2 — confirms regression narrative
- **User Story 2 (Phase 4)**: After Phase 2 — can overlap with Phase 3 polish only after T009 green
- **User Story 3 (Phase 5)**: After Phase 2 — best after Phase 4 when public API stable
- **Polish (Phase 6)**: After desired user stories complete

### User Story Dependencies

- **US1**: Depends on Phase 2 only
- **US2**: Depends on Phase 2; practically after US1 test stability (T009) to avoid thrash
- **US3**: Depends on Phase 2; recommended after US2 API freeze

### Parallel Opportunities

- T002 parallel to T001
- T012–T016 parallel (all tests) before T017
- T023 parallel to late US2 tasks only if no doc dependency on final hook names
- T025–T029 parallel in Phase 6

---

## Parallel Example: User Story 2

```text
Task: "Unit test before/after dispatch order in tests/test_action_cue.py"
Task: "Unit test last-wins duplicate hook in tests/test_action_cue.py"
Task: "Unit test cue_layer vs node_layer merge order in tests/test_action_cue.py"
Task: "Unit test injectable result sink in tests/test_action_cue.py"
Task: "Unit test hook exception safety in tests/test_action_cue.py"
```

---

## Implementation Strategy

### MVP First (US1)

1. Phase 1 + Phase 2 + Phase 3 through T011  
2. **STOP**: `poetry run pytest -q tests/test_action_cue.py`  
3. Merge or demo if policy allows partial delivery

### Incremental Delivery

1. Setup + Foundational → extract + green tests  
2. US1 → explicit regression sign-off  
3. US2 → hooks + dual registration + sink  
4. US3 → docs + structure audit  
5. Polish → full suite + quickstart

---

## Notes

- Prefer `ACTION_HANDLER` as the single execution entry from `run_cue.py` per research Decision 6.
- NNG sends MUST stay on the comms thread (`AsyncCommsThread.run_coroutine`); do not block the receiver thread.
- [P] = different files or independent work packages; re-check ordering when touching the same file.
