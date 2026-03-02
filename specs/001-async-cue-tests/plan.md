# Implementation Plan: Async Cue Execution Test Suite

**Branch**: `001-async-cue-tests` | **Date**: 2026-02-26 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-async-cue-tests/spec.md`

## Summary

Build a comprehensive test suite that validates the asynchronous cue execution
lifecycle in cuems-engine. The suite verifies single-cue lifecycle, concurrent
execution, post-go chaining, MTC synchronization, error handling, and the
dual-event-loop architecture (AsyncCommsThread managing separate IPC and cue
orchestration loops). All async logic uses stdlib `asyncio` exclusively. Test
infrastructure is implemented as reusable components to accommodate future
Cue object modifications.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: asyncio (stdlib), pytest, pytest-cov, pytest-mock, threading, concurrent.futures
**Storage**: N/A
**Testing**: pytest with markers `unit`, `integration`, `slow`, `cuems`; `--strict-markers --strict-config`
**Target Platform**: Linux (Debian-based)
**Project Type**: Library/daemon — show-control engine
**Performance Goals**: Unit test suite ≤ 30 s; cue trigger latency ≤ 50 ms
**Constraints**: Only asyncio (no trio/anyio/pytest-asyncio); zero new external deps; all external I/O mocked
**Scale/Scope**: ~10 test modules, ~60-80 test functions, ~6 reusable helper modules

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|---|---|---|
| I. Code Quality & Consistency | ✅ PASS | Test code will comply with black/isort/flake8; type annotations on all public helpers |
| II. Testing Discipline | ✅ PASS | All tests use `@pytest.mark.unit`; deterministic via mocked time; strict markers enabled |
| III. Real-Time Performance | ✅ PASS | Unit suite targets ≤ 30 s; no real I/O or subprocess spawning in unit tests |
| IV. User Experience Consistency | ✅ PASS | Tests verify canonical state machine for all cue types uniformly |
| V. Reliability & Fault Tolerance | ✅ PASS | Tests verify cleanup on error, subprocess reaping, resource release |

**Post-Phase 1 re-check**: All gates still pass. No complexity violations.

## Project Structure

### Documentation (this feature)

```text
specs/001-async-cue-tests/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: research decisions
├── data-model.md        # Phase 1: entity model
├── quickstart.md        # Phase 1: run instructions
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
tests/
├── async_helpers/                # Reusable test components (NEW)
│   ├── __init__.py
│   ├── factories.py              # MockCueFactory — parametric cue mock builder
│   ├── loops.py                  # EventLoopFixture — background asyncio loop
│   ├── mtc.py                    # MockMtcListener — controllable MTC time
│   ├── osc.py                    # MockOscClient — records OSC calls
│   ├── players.py                # MockPlayerHandler — stub singleton
│   └── assertions.py             # LifecycleAssertions — reusable checks
├── async_cue/                    # Test modules (NEW)
│   ├── __init__.py
│   ├── conftest.py               # Fixtures composing async_helpers
│   ├── test_single_lifecycle.py  # US1: arm → go → run → loop → disarm (Audio, Video, Action, CueList)
│   ├── test_concurrent.py        # US2: parallel cues, thread safety
│   ├── test_post_go.py           # US3: go / go_at_end chaining
│   ├── test_mtc_loop.py          # US4: MTC polling, offset, loop counter
│   ├── test_error_cleanup.py     # US5: fault injection, cleanup
│   ├── test_loop_identity.py     # FR-011/012/014: loop affinity & isolation
│   ├── test_wait_for_cue.py      # FR-013: missing method exposure
│   └── test_edge_cases.py        # Edge cases from spec
├── conftest.py                   # Existing — unchanged
├── fixtures.py                   # Existing — unchanged
└── ... (existing test files)

src/cuemsengine/
├── tools/
│   └── communicate.py            # AsyncCommsThread — will need _cue_loop addition
├── cues/
│   ├── CueHandler.py             # go() must submit to _cue_loop; wait_for_cue() TBD
│   ├── arm_cue.py                # Tested via mocks
│   ├── run_cue.py                # Tested via mocks
│   ├── loop_cue.py               # Tested via mocks
│   └── helpers.py                # find_timing — tested via mocks
└── players/
    └── PlayerHandler.py          # Tested via MockPlayerHandler
```

**Structure Decision**: Two new test packages (`async_helpers/`, `async_cue/`)
under the existing `tests/` directory. No changes to `src/` directory structure.
Production code modifications (AsyncCommsThread, CueHandler) are implementation
tasks driven by failing tests, not part of the test-suite feature itself.

## Key Design Decisions

### D1: Stdlib-Only Async Testing

Tests use `asyncio.run()` for simple coroutine verification and a custom
`EventLoopFixture` (background thread with `loop.run_forever()`) for tests
requiring a persistent loop. No `pytest-asyncio` dependency.

Pattern for single-coroutine tests:
```python
@pytest.mark.unit
def test_prewait_delays_execution(mock_cue, mock_mtc):
    async def run():
        t0 = time.monotonic()
        await handler._go_async(mock_cue, mock_mtc)
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.1  # 100ms prewait
    asyncio.run(run())
```

Pattern for loop-affinity tests:
```python
@pytest.mark.unit
def test_task_runs_on_cue_loop(cue_loop_fixture):
    loop = cue_loop_fixture
    async def check():
        assert asyncio.get_running_loop() is loop
    future = asyncio.run_coroutine_threadsafe(check(), loop)
    future.result(timeout=5)
```

### D2: Reusable Component Architecture

All mock factories accept keyword arguments for every configurable cue
attribute. New cue types are added by registering a new preset — existing
tests need no modification.

The `LifecycleAssertions` helper provides:
- `assert_lifecycle_completed(cue)` — verifies loaded→armed→running→idle
- `assert_timing_budget(elapsed, budget_ms)` — checks latency constraints
- `assert_resources_released(cue, player_handler)` — no leaked players/OSC

### D3: Dual-Loop Isolation Testing

Tests create two separate event loops:
1. `ipc_loop` — represents `AsyncCommsThread.event_loop`
2. `cue_loop` — represents `AsyncCommsThread._cue_loop`

FR-014 test: submit a blocking coroutine (10s sleep) to `ipc_loop`, then
verify `cue_loop` still processes tasks within the latency budget.

### D4: Singleton Reset Strategy

CueHandler and PlayerHandler are singletons. Between tests:
- `CueHandler._instance = None` forces fresh instance on next access
- `PlayerHandler._instance = None` forces fresh instance on next access
- Encapsulated in an `autouse` fixture in `async_cue/conftest.py`

This avoids cross-test state contamination without monkeypatching.
