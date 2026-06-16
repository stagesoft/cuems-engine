# Tasks: CuemsDeploy Async Refactor

**Input**: Design documents from `specs/006-cuemsdeploy-async-refactor/`
**Prerequisites**: plan.md ✅ spec.md ✅ research.md ✅ data-model.md ✅ contracts/ ✅

**TDD**: Tests MUST be written and confirmed FAILING before each implementation step (constitution §II).

**Affected files**:
- `src/cuemsengine/tools/CuemsDeploy.py` — primary change
- `src/cuemsengine/NodeEngine.py` — late-bind + deploy_media update
- `tests/test_cuems_deploy.py` — async test infrastructure rewrite + new cases
- `tests/test_node_engine.py` — new (or extended) file for the `NodeEngine.start()` late-bind test
- `tests/test_cuems_deploy_integration.py` — new file for the SC-001 NNG-heartbeat-during-deploy integration test

---

## Phase 1: Setup

**Purpose**: Verify baseline and confirm async test infrastructure is available.

- [X] T001 Confirm all 26 existing tests pass: `cd src && pytest ../tests/test_cuems_deploy.py -v` (establishes regression baseline)
- [X] T002 Verify `anyio` pytest plugin is active: `pytest --co -q tests/test_cuems_deploy.py` should list `anyio-4.11.0` in plugins; check `pyproject.toml` for `asyncio_mode` setting — add `[tool.pytest.ini_options] asyncio_mode = "auto"` only if `pytest.mark.anyio` requires it

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Test helpers and the `_RSYNC_PASSWORD` class constant — both are prerequisites for all subsequent phases.

**⚠️ CRITICAL**: All US1–US4 work depends on the async mock helpers (T004–T005). `_RSYNC_PASSWORD` (T003/T006) should be done before rewriting any method that embeds the literal.

- [X] T003 [US3] Write failing test: assert `hasattr(CuemsDeploy, '_RSYNC_PASSWORD')`, `CuemsDeploy._RSYNC_PASSWORD == "f48t5eL2kLHw2Wfw"`, and the password literal string appears in `CuemsDeploy.py` source exactly once in `tests/test_cuems_deploy.py`
- [X] T004 [P] Write async test helper `_make_async_proc(rc, stdout_chunks, stderr_chunks)` in `tests/test_cuems_deploy.py` — returns a `MagicMock` with async `.wait()`, `.stdout`, `.stderr` matching `asyncio.create_subprocess_exec` return shape (see research.md §1)
- [X] T005 [P] Write async test helper `_make_stream_reader(chunks)` in `tests/test_cuems_deploy.py` — wraps a list of `bytes` chunks into an object whose `.read(n)` coroutine returns chunks in order then `b''`
- [X] T006 [US3] Add `_RSYNC_PASSWORD: ClassVar[str] = "f48t5eL2kLHw2Wfw"` as a private class attribute on `CuemsDeploy` in `src/cuemsengine/tools/CuemsDeploy.py`; import `ClassVar` from `typing`; replace the two inline string literals in `_check_mandatory_sources` and `_sync` env dicts with `self._RSYNC_PASSWORD` — T003 must pass green after this step

**Checkpoint**: Baseline green. Async helpers available. Password constant in place. Phase 3+ can begin.

---

## Phase 3: User Story 1 — Non-blocking async deploy (Priority: P1) 🎯 MVP

**Goal**: `_sync()`, `_check_mandatory_sources()`, and `_kill()` become async coroutines; `sync_files()` bridges to the async flow via `run_coroutine_threadsafe`; all `selectors`/`fcntl`/`os.read` machinery removed.

**Independent Test**: Trigger a project load while watching NNG heartbeats — no stall during transfer; deploy returns correct success/failure.

### Tests for US1 ⚠️ Write FIRST — confirm FAILING before T016+

- [X] T007 [US1] Write failing test: `CuemsDeploy._sync` is a coroutine function (`asyncio.iscoroutinefunction`) in `tests/test_cuems_deploy.py`
- [X] T008 [P] [US1] Write failing test: `CuemsDeploy._kill` is a coroutine function in `tests/test_cuems_deploy.py`
- [X] T009 [P] [US1] Write failing test: `CuemsDeploy._check_mandatory_sources` is a coroutine function in `tests/test_cuems_deploy.py`
- [X] T010 [P] [US1] Write failing test: `sync_files()` returns `False` immediately and logs error when `self.loop` is `None` in `tests/test_cuems_deploy.py`
- [X] T011 [P] [US1] Write failing `@pytest.mark.anyio` test: async startup watchdog fires and kills proc when `asyncio.wait` returns empty `done` set before first output — asserts `result is False` and `'startup deadline' in errors` in `tests/test_cuems_deploy.py`
- [X] T012 [P] [US1] Write failing `@pytest.mark.anyio` test: async inactivity watchdog fires after first chunk then silence — asserts `'inactivity threshold' in errors` in `tests/test_cuems_deploy.py`
- [X] T013 [P] [US1] Write failing `@pytest.mark.anyio` test: `_check_mandatory_sources` returns `(False, [path])` when `asyncio.create_subprocess_exec` exits non-zero with matching stderr in `tests/test_cuems_deploy.py`
- [X] T014 [US1] Write failing test: `sync_files()` with a real background event loop returns `False` and does NOT call `_sync` when precheck fails (`_deploy_all_async` early-fail path) in `tests/test_cuems_deploy.py`
- [X] T015 [US1] Write failing test: `sync_files()` with a real background event loop returns `True` when both precheck and `_sync` succeed in `tests/test_cuems_deploy.py`

### Implementation for US1

- [X] T016 [US1] Add `loop: asyncio.AbstractEventLoop | None = None` parameter to `CuemsDeploy.__init__` and store as `self.loop` in `src/cuemsengine/tools/CuemsDeploy.py`
- [X] T017 [US1] Convert `_kill()` to `async def _kill(proc)` using `asyncio.wait_for(proc.wait(), timeout=2.0)` with `asyncio.TimeoutError` in `src/cuemsengine/tools/CuemsDeploy.py`
- [X] T018 [US1] Add `async def _pump(stream, tag, queue)` coroutine: reads 4096-byte chunks until EOF, pushes `(tag, chunk)` tuples and `(tag, None)` sentinel to `queue` in `src/cuemsengine/tools/CuemsDeploy.py`
- [X] T019 [US1] Convert `_sync(path)` to `async def _sync(path)`: replace `subprocess.Popen` + selectors loop with `asyncio.create_subprocess_exec`, two `_pump` tasks, `asyncio.Queue`, and `asyncio.wait({t_out, t_err}, timeout=budget)` watchdog loop; preserve all error-precedence and `_dispatch_line` semantics (see data-model.md watchdog state machine) in `src/cuemsengine/tools/CuemsDeploy.py`
- [X] T020 [US1] Convert `_check_mandatory_sources(mandatory_paths)` to `async def` using `asyncio.create_subprocess_exec` with `stdout=PIPE, stderr=PIPE`; capture output via `stdout_bytes, stderr_bytes = await proc.communicate()` (short-lived probe, bounded output, no streaming needed); preserve missing-path extraction logic in `src/cuemsengine/tools/CuemsDeploy.py`
- [X] T021 [US1] Add `async def _deploy_all_async(log_file, file_names, mandatory_paths)`: awaits `_check_mandatory_sources` (early-return `False` on failure), calls `_create_deploy_log`, awaits `_sync(log_file)` in `src/cuemsengine/tools/CuemsDeploy.py`
- [X] T022 [US1] Update `sync_files()`: add `self.loop is None` guard (log error, return `False`); move mandatory-path check and log-creation into `_deploy_all_async`; submit `_deploy_all_async(...)` via `asyncio.run_coroutine_threadsafe(coro, self.loop).result()` in `src/cuemsengine/tools/CuemsDeploy.py`
- [X] T023 [US1] Remove `import fcntl`, `import selectors` from `src/cuemsengine/tools/CuemsDeploy.py`; remove `os` import if no longer used elsewhere in the file
- [X] T023a [US1] Write failing test in `tests/test_node_engine.py` (create file if absent): construct a `NodeEngine` instance with mocked `cm`, `CUE_HANDLER`, `PLAYER_HANDLER`, `PORT_HANDLER`; set up `CUE_HANDLER.communications_thread.event_loop` to a sentinel value; call `node.start()`; assert `node.deploy_manager.loop is CUE_HANDLER.communications_thread.event_loop`. This is the TDD gate for T024.
- [X] T024 [US1] Add late-bind line `self.deploy_manager.loop = CUE_HANDLER.communications_thread.event_loop` to `NodeEngine.start()` immediately after `CUE_HANDLER.set_nng_comms(...)` in `src/cuemsengine/NodeEngine.py` — T023a must turn green after this step
- [X] T025 [US1] Adapt all existing `_sync`-based and `_check_mandatory_sources`-based tests in `tests/test_cuems_deploy.py` to the async surface in a single pass: (1) replace `subprocess.Popen` patches with `asyncio.create_subprocess_exec` + `_make_async_proc`; (2) delete all `_ScriptedSelector`, `_FakeStream`, `_scripted_os_read` infrastructure; (3) wrap async assertions in `@pytest.mark.anyio` or `asyncio.run()`; (4) adapt `test_sync_files_returns_false_when_disabled` to remove `subprocess.Popen` patch (disabled check fires before any subprocess call); (5) adapt `test_check_mandatory_sources_*` tests to mock `asyncio.create_subprocess_exec` with `proc.communicate()` returning the scripted stdout/stderr bytes. Covers what was previously split between T025 and T026.

**Checkpoint**: All tests green. `CuemsDeploy` is fully async internally; `sync_files()` API is unchanged. NNG loop free during transfers.

---

## Phase 4: User Story 2 — Stale-file cleanup (Priority: P2)

**Goal**: Destination nodes automatically remove files absent from the new project's source list after each successful sync.

**Independent Test**: Deploy project A then project B (different media) — files exclusive to A are absent after B's deploy completes.

### Tests for US2 ⚠️ Write FIRST — confirm FAILING before T029

- [X] T027 [P] [US2] Write failing `@pytest.mark.anyio` test: rsync command captured from `asyncio.create_subprocess_exec` call in `_sync()` contains `'--delete'` and `'--delete-delay'` in `tests/test_cuems_deploy.py`
- [X] T028 [P] [US2] Write failing `@pytest.mark.anyio` test: rsync command in `_check_mandatory_sources()` does NOT contain `'--delete'` or `'--delete-delay'` in `tests/test_cuems_deploy.py`

### Implementation for US2

- [X] T029 [US2] Add `'--delete'` and `'--delete-delay'` to the rsync `cmd` list in `_sync()` in `src/cuemsengine/tools/CuemsDeploy.py` (before the `--files-from` flag, after existing flags)

**Checkpoint**: T027 and T028 green. Stale files are cleaned at destination. Precheck probe is unaffected.

---

## Phase 5: User Story 3 — Centralised credential (Priority: P3)

**Goal**: The rsync password literal appears exactly once in `CuemsDeploy.py`, as the value of the private class constant `CuemsDeploy._RSYNC_PASSWORD: ClassVar[str]`.

**Note**: T003 and T006 (Foundational) already complete this story's implementation. This phase adds an explicit verification task.

### Tests for US3

> **Note**: T003 already wrote the failing test. T006 already made it pass. The task below is a final format validation.

- [X] T030 [P] [US3] Confirm `test_rsync_password_constant_defined` (from T003) is green; add assertion that neither `_sync` nor `_check_mandatory_sources` source body contains the literal string (inspect via `inspect.getsource`); add assertion that `_RSYNC_PASSWORD` is annotated with `ClassVar` in the class body in `tests/test_cuems_deploy.py`

**Checkpoint**: Password literal has exactly one occurrence in the module.

---

## Phase 6: User Story 4 — Consolidated media-path logic (Priority: P4)

**Goal**: `NodeEngine.deploy_media()` delegates all path construction to `CuemsDeploy._media_files()`; no `media/` literals or video-extension sets remain in `NodeEngine`.

**Independent Test**: Call `deploy._media_files(['intro.mp4', 'sfx.wav'])` directly and assert expected paths.

### Tests for US4 ⚠️ Write FIRST — confirm FAILING before T033

- [X] T031 [P] [US4] Write failing test: `deploy._media_files(['clip.mp4', 'track.wav'])` returns `['media/clip.mp4', 'media/indexes/clip.mp4.idx', 'media/track.wav']` in `tests/test_cuems_deploy.py`
- [X] T032 [P] [US4] Write failing test: `deploy._media_files(['a.avi', 'b.mkv', 'c.mp3'])` returns `media/` entries plus `.idx` entries for `.avi` and `.mkv` but not `.mp3` in `tests/test_cuems_deploy.py`

### Implementation for US4

- [X] T033 [US4] Add `_media_files(self, bare_names: list[str]) -> list[str]` to `CuemsDeploy` in `src/cuemsengine/tools/CuemsDeploy.py`: build `media/<name>` for each name; append `media/indexes/<name>.idx` for names whose extension (lowercased) is in `{'.mp4', '.mov', '.avi', '.mkv', '.mpg'}`
- [X] T034 [US4] Update `NodeEngine.deploy_media()` in `src/cuemsengine/NodeEngine.py`: remove the `media_entries`/`idx_entries`/`video_exts` inline construction; pass `bare_names` directly to `sync_files(project, 'media', bare_names)` — path expansion is now owned by `sync_files` (see T034a)
- [X] T034a [US4] Add `elif tag == 'media' and len(file_names) > 0: file_names = self._media_files(file_names)` branch to `sync_files()` in `src/cuemsengine/tools/CuemsDeploy.py` so that callers pass bare filenames and path expansion (`media/`, `media/indexes/`) is centralised in `sync_files`; add test `test_sync_files_media_tag_auto_expands_bare_names` (T034a) in `tests/test_cuems_deploy.py` asserting that bare names are expanded to `media/<name>` + `.idx` entries before reaching `_create_deploy_log`

**Checkpoint**: `NodeEngine.deploy_media()` contains no `media/` literals or extension sets. T031, T032 green.

---

## Phase 7: Polish & Verification

**Purpose**: Cross-cutting verification that all success criteria are met.

- [X] T035 Run full test suite and confirm all tests pass: `cd src && pytest ../tests/test_cuems_deploy.py -v` — zero failures, zero skipped (SC-004)
- [X] T036 [P] Verify SC-006: `grep -n 'import fcntl\|import selectors\|subprocess\.Popen\|subprocess\.run' src/cuemsengine/tools/CuemsDeploy.py` — only `subprocess.run` inside `_avahi_resolve` is permitted; all other hits are a blocker
- [X] T037 [P] Verify SC-003: `grep -c 'f48t5eL2kLHw2Wfw' src/cuemsengine/tools/CuemsDeploy.py` outputs `1` (the constant definition)
- [X] T038 [P] Verify SC-005: `grep -n "media/" src/cuemsengine/NodeEngine.py` — no matches in `deploy_media()` body; `grep -n 'video_exts\|\.mp4\|\.mov\|\.mkv' src/cuemsengine/NodeEngine.py` — no matches in `deploy_media()` body
- [X] T039 [P] Verify SPDX headers present on any newly created files (none expected — this is an in-place refactor)
- [X] T040 Run linter: `cd src && ruff check . --select E,F,W` — zero new violations introduced by this branch
- [X] T041 Documentation pass on `src/cuemsengine/tools/CuemsDeploy.py` (covers FR-013, SC-007): (1) delete the `ASYNC MIGRATION NOTE` block (lines 19–59); (2) delete every `[ASYNC-MIGRATE]` inline marker (~25 occurrences); (3) add/update module docstring summarising the async model, the late-bind protocol, and why `_avahi_resolve` stays synchronous; (4) add docstrings to `_sync` (watchdog state machine + queue pattern), `_kill` (timeout cascade), `_pump` (EOF sentinel contract), `_deploy_all_async` (precheck early-fail), `_check_mandatory_sources` (probe semantics + `communicate()` rationale), `sync_files` (`run_coroutine_threadsafe` bridge rationale), `_media_files` (output shape contract); (5) keep at most ~20 single-line `#` comments for non-obvious WHY-only notes (preserve the 2026-05-19 mtime-drift incident note as a one-liner)
- [X] T042 [P] Verify SC-007: count non-SPDX comment lines in `src/cuemsengine/tools/CuemsDeploy.py` (`grep -cE '^\s*#' src/cuemsengine/tools/CuemsDeploy.py` minus 3 SPDX lines) — MUST be ≤ 20
- [X] T043 Integration test for SC-001 (NNG heartbeat resilience during deploy) in `tests/test_cuems_deploy_integration.py` (create file): spin up a real `asyncio` event loop in a thread; construct `CuemsDeploy` with `loop` bound to it; mock `asyncio.create_subprocess_exec` to return a long-running fake process that emits a progress chunk every 100 ms for 30 seconds; concurrently schedule a "heartbeat" coroutine that records `loop.time()` at 1 Hz; call `sync_files()` from a separate thread; after completion, assert (a) `sync_files` returned `True`, (b) heartbeat intervals were within ±20% of 1 s with no missed beats. Marks: `@pytest.mark.integration` so it can be excluded from fast unit runs.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No deps — start immediately
- **Phase 2 (Foundational)**: After Phase 1 baseline green — **BLOCKS all US phases**
- **Phase 3 (US1)**: After Phase 2 complete — largest phase; everything else layers on top
- **Phase 4 (US2)**: After Phase 3 (adds flags to already-async `_sync`)
- **Phase 5 (US3)**: Already done in Phase 2; Phase 5 is verification only
- **Phase 6 (US4)**: After Phase 2 (helpers) — independent of US1/US2 logic, but wait for US1 to avoid merge conflicts on the same file
- **Phase 7 (Polish)**: After all user story phases complete

### Within Each Phase: TDD Order

1. Write ALL failing tests for the phase first
2. Run test suite — confirm new tests FAIL, existing pass
3. Implement
4. Run test suite — confirm all green
5. Refactor if needed, keeping green

### Parallel Opportunities Within Phases

**Phase 2**: T003, T004, T005 can run in parallel (different concerns, test file only).  
**Phase 3 tests** (T007–T015, T023a): All can be written in parallel (T023a touches `tests/test_node_engine.py`, all others touch `tests/test_cuems_deploy.py`).  
**Phase 3 impl**: T017 (`_kill`), T018 (`_pump`) can be done in parallel; T019 (`_sync`) needs T017+T018 done; T020 (`_check_mandatory_sources`) is independent of T019; T021 (`_deploy_all_async`) needs T019+T020; T022 (`sync_files`) needs T021; T024 (NodeEngine late-bind) needs T023a green-able and T016 (loop attribute exists); T025 (test adaptation) runs after T019+T020 are merged.
**Phase 7**: T036, T037, T038, T039, T042 can all run in parallel (independent grep/count checks). T043 (integration test) is independent of the above.

---

## Parallel Example: Phase 3 Test Writing

```text
# Write all US1 failing tests in one pass (they're all in the same file,
# but non-overlapping — can be assigned to one agent or split by group):

Group A (coroutine shape tests — fast):
  T007: _sync is coroutine function
  T008: _kill is coroutine function
  T009: _check_mandatory_sources is coroutine function
  T010: sync_files returns False when loop is None

Group B (watchdog behaviour — async):
  T011: startup watchdog via asyncio.wait timeout
  T012: inactivity watchdog after first chunk

Group C (integration bridge — needs real event loop):
  T013: _check_mandatory_sources async happy/sad path
  T014: sync_files early-fail when precheck fails
  T015: sync_files success end-to-end bridge
```

---

## Implementation Strategy

### MVP (User Story 1 Only)

1. Phase 1 + Phase 2 → foundation ready
2. Phase 3 → async migration complete; `sync_files()` API unchanged
3. **Validate**: Run test suite; manually verify a project load on a node
4. US1 alone delivers the primary performance goal (SC-001)

### Incremental Delivery

- US1 (P1): Core async migration — the engine no longer blocks during deploy
- US2 (P2): Add two flags — cleanup at destination, no structural change
- US3 (P3): Already complete as of Phase 2 — zero additional effort  
- US4 (P4): `_media_files` helper — clean separation of concerns, no behaviour change

---

## Notes

- `_ScriptedSelector`, `_FakeStream`, `_scripted_os_read` helpers in `tests/test_cuems_deploy.py` are fully replaced by `_make_async_proc` and `_make_stream_reader` in T004/T005. Delete old helpers as part of T025.
- `test_sync_files_returns_false_when_disabled` (folded into T025): after refactor, `enabled is False` check fires before the `loop` check, so no subprocess patch is needed — just assert `result is False`.
- The `_deploy_all_async` coroutine owns log-file creation (after precheck passes). This preserves the original invariant: the log file is only created if the precheck passes.
- `proc.communicate()` is locked in for `_check_mandatory_sources` (short-lived probe, bounded output); the streaming pattern with `_pump` tasks is reserved for `_sync` (see research.md §2).
- T041 (documentation pass) intentionally lands in Phase 7 rather than woven through the implementation phases: the design decisions are easier to articulate once the new code is settled. Implementers are still expected to leave first-draft docstrings on the methods they create; T041 polishes them and removes the migration scaffolding.
