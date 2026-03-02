# Research: Async Cue Execution Test Suite

**Branch**: `001-async-cue-tests` | **Date**: 2026-02-26

## R1: Async Testing Without pytest-asyncio

**Decision**: Use stdlib `asyncio.run()` and custom event loop fixtures within
regular (non-async) pytest test functions.

**Rationale**: The spec mandates zero new external dependencies (FR-006, SC-006).
`pytest-asyncio` is not in `[project.optional-dependencies].dev`. The stdlib
approach is sufficient because:
- `asyncio.run()` creates, runs, and closes a loop for each test — clean isolation.
- For tests requiring a persistent loop (simulating AsyncCommsThread), a
  `threading.Thread` fixture can spin up a loop and yield it for the test duration.
- `asyncio.run_coroutine_threadsafe()` works identically with a manual loop.

**Alternatives considered**:
- `pytest-asyncio`: Would simplify syntax but violates SC-006.
- `anyio` / `trio`: Violates the user constraint ("only asyncio").

## R2: Dual Event Loop Architecture in AsyncCommsThread

**Decision**: AsyncCommsThread acts as a **manager** owning two threads, each
running its own `asyncio.new_event_loop()`:
1. `_ipc_loop` — existing loop for editor/hwdiscovery/nodeconf IPC.
2. `_cue_loop` — new loop dedicated to cue orchestration tasks.

**Rationale**: Python's asyncio enforces one event loop per thread. Two isolated
loops require two threads. AsyncCommsThread already is a `threading.Thread`
subclass; it can spawn a second internal thread for the cue loop or restructure
into a coordinator that manages two daemon threads.

For testing, the key property is: tests must be able to assert which loop a
task was submitted to. This is verified by comparing `id(loop)` of the running
loop inside a coroutine against the expected loop reference.

**Alternatives considered**:
- Single shared loop (current): Rejected — IPC and cue tasks would compete for
  execution time; a slow IPC handler could stall cue triggers.
- Separate `CueLoopThread` class: Viable but increases API surface; rejected in
  favor of keeping loop management centralized in AsyncCommsThread.

## R3: Reusable Test Component Design

**Decision**: All test infrastructure is implemented as composable fixtures and
factory functions in a shared `tests/async_helpers/` package. Components:

| Component | Responsibility |
|---|---|
| `MockCueFactory` | Creates mock Cue objects (Audio/Video/Action) with configurable attributes (prewait, postwait, loop, post_go) |
| `EventLoopFixture` | Provides a running asyncio event loop in a background thread, mimicking AsyncCommsThread's cue loop |
| `MockMtcListener` | Simulates MTC time progression via a controllable `main_tc` attribute |
| `MockOscClient` | Records OSC set_value/get_value calls for assertion without network I/O |
| `MockPlayerHandler` | Stub PlayerHandler that tracks store/remove calls without spawning subprocesses |
| `LifecycleAssertions` | Reusable assertion helpers: verify state transitions, timing budgets, resource cleanup |

**Rationale**: The user explicitly requested reusable components to accommodate
future Cue object modifications. Factory-based mocks decouple tests from concrete
cue implementations; adding a new cue type requires only adding a factory preset,
not rewriting tests.

**Alternatives considered**:
- Inline mocks per test: Rejected — violates reusability mandate, duplicates setup.
- Monkeypatching production singletons: Rejected — fragile, test order dependent.

## R4: Thread-Safety Stress Testing

**Decision**: Use `concurrent.futures.ThreadPoolExecutor` to submit concurrent
`go()` calls from multiple threads, and `threading.Barrier` to synchronize
simultaneous starts.

**Rationale**: CueHandler and PlayerHandler are thread-safe singletons guarded
by `threading.Lock`. Stress tests must verify the lock discipline holds under
contention. `ThreadPoolExecutor` provides clean concurrency without managing
raw threads. `Barrier` ensures all submissions happen at the same instant.

The stress test pattern:
1. Create N threads, each holding a different mock cue.
2. All threads wait on a `Barrier`.
3. On release, all call `run_coroutine_threadsafe(go(...), cue_loop)`.
4. Assert: no exceptions, all cues complete, armed-cues list consistent.

**Alternatives considered**:
- `asyncio.gather()`: Tests async concurrency but not cross-thread access.
- Raw `threading.Thread`: More boilerplate, less clean teardown.

## R5: Event Loop Identity Verification

**Decision**: Inject a loop-identity check inside coroutines to verify they
execute on the correct loop.

**Pattern**:
```python
async def verify_loop_identity(expected_loop: asyncio.AbstractEventLoop):
    running = asyncio.get_running_loop()
    assert running is expected_loop, (
        f"Task running on wrong loop: expected {id(expected_loop)}, "
        f"got {id(running)}"
    )
```

Tests wrap cue coroutines with this check to satisfy FR-011 and FR-012.

**Rationale**: The only reliable way to verify loop affinity is from inside
the running coroutine. `asyncio.get_running_loop()` returns the loop of the
current thread, which must match the expected cue orchestration loop.

## R6: CueHandler.wait_for_cue — Missing Method

**Decision**: The test suite includes a test that calls `CueHandler.wait_for_cue()`
and expects `AttributeError`. This documents the gap and serves as a
regression anchor — when the method is implemented, the test is updated to
verify correct behavior.

**Rationale**: `NodeEngine.go_script()` (line 458) calls
`CUE_HANDLER.wait_for_cue(main_thread)` but the method does not exist in
`CueHandler`. The test exposes this as a failing contract (FR-013).

The expected signature (derived from call site):
```python
def wait_for_cue(self, task: asyncio.Task) -> None:
    """Block the calling thread until the cue task completes."""
```

Implementation would use `asyncio.run_coroutine_threadsafe` or
`concurrent.futures.Future.result()` to bridge the async/sync boundary.
