# Feature Specification: Async Cue Execution Test Suite

**Feature Branch**: `001-async-cue-tests`
**Created**: 2026-02-26
**Status**: Draft
**Input**: User description: "Create a complete test suite to check the asynchronous logic for cue execution"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single Cue Async Lifecycle (Priority: P1)

A developer runs the test suite and verifies that a single cue progresses
through its full asynchronous lifecycle: arm → go → prewait → run → postwait
→ loop → disarm. Each state transition completes within the expected time
budget and produces the correct observable side effects (player spawned,
media commands sent, player cleaned up).

**Why this priority**: The single-cue lifecycle is the foundational execution
path. Every other async behaviour (concurrency, error recovery, post_go
chaining) builds on top of it. If this is wrong, nothing else matters.

**Independent Test**: Run `pytest -m unit -k "single_cue_lifecycle"` — passes
with no external services, no media files, no hardware.

**Acceptance Scenarios**:

1. **Given** a mocked AudioCue in idle state, **When** `go()` is called,
   **Then** the cue transitions through armed → running → idle, and
   each transition fires within the latency budget defined in the constitution
   (≤ 50 ms trigger, ≤ 10 ms state transition).
2. **Given** a mocked VideoCue with a prewait of 100 ms, **When** `go()` is
   called, **Then** `run_cue()` is not invoked until at least 100 ms have
   elapsed.
3. **Given** a cue that has completed playback, **When** disarm runs, **Then**
   the player subprocess is terminated, its resources are released, and the
   cue returns to idle.

---

### User Story 2 - Concurrent Cue Execution (Priority: P2)

A developer verifies that multiple cues can execute simultaneously without
blocking each other or corrupting shared state. The async task scheduler
handles parallel cues correctly, and thread-safe data structures remain
consistent under concurrent access.

**Why this priority**: Live shows routinely fire multiple cues at once (e.g.,
audio + video + DMX). Concurrency correctness is the second most critical
property after basic lifecycle correctness.

**Independent Test**: Run `pytest -m unit -k "concurrent_cues"` — passes in
isolation.

**Acceptance Scenarios**:

1. **Given** three mocked cues (Audio, Video, Action), **When** all three are
   triggered via `go()` within the same event loop tick, **Then** all three
   complete their lifecycle independently and no shared state is corrupted.
2. **Given** two cues sharing the CueHandler singleton, **When** one cue
   errors during `run_cue()`, **Then** the other cue completes unaffected.
3. **Given** concurrent `go()` calls, **When** the armed-cues list is
   accessed, **Then** no race condition occurs (verified by stress-testing
   with repeated concurrent invocations).

---

### User Story 3 - Post-Go Chaining (Priority: P3)

A developer verifies that `post_go` modes (`'go'` and `'go_at_end'`) correctly
chain cue execution. An immediate `post_go: 'go'` fires the next cue right
after run, while `'go_at_end'` waits until the current cue's loop completes.

**Why this priority**: Post-go chaining is a key sequencing feature but depends
on the lifecycle (US1) and concurrency (US2) being correct first.

**Independent Test**: Run `pytest -m unit -k "post_go"` — passes in isolation.

**Acceptance Scenarios**:

1. **Given** cue A with `post_go: 'go'` pointing to cue B, **When** cue A
   finishes `run_cue()`, **Then** cue B's `go()` is invoked before cue A's
   postwait completes.
2. **Given** cue A with `post_go: 'go_at_end'` pointing to cue B, **When**
   cue A's loop completes, **Then** cue B's `go()` is invoked after the loop
   exits.
3. **Given** cue A with `post_go: 'go_at_end'` and cue A errors during loop,
   **Then** cue B is NOT triggered, and the error is reported.

---

### User Story 4 - MTC Synchronization in Loop (Priority: P4)

A developer verifies that the `loop_cue()` polling mechanism correctly
tracks MIDI Time Code, recalculates offsets on loop restart, and disconnects
MTC when the loop ends.

**Why this priority**: MTC sync is critical for live operation but is a
narrower concern than lifecycle, concurrency, or chaining.

**Independent Test**: Run `pytest -m unit -k "mtc_loop"` — uses a mock MTC
listener, no MIDI hardware required.

**Acceptance Scenarios**:

1. **Given** a cue with `loop: 3`, **When** the MTC reaches the cue's
   end timecode, **Then** the offset is recalculated and the loop counter
   increments toward the target.
2. **Given** a cue in its final loop iteration, **When** the MTC reaches the
   end timecode, **Then** MTC is disconnected and the cue proceeds to disarm.
3. **Given** a cue looping, **When** the MTC listener stalls (no updates for
   > 1 s), **Then** the cue remains in its current state and does not
   erroneously advance or crash.

---

### User Story 5 - Error Handling & Cleanup (Priority: P5)

A developer verifies that failures at any point in the async cue lifecycle
produce correct error states, log tracebacks, and clean up all resources
(subprocesses, file descriptors, OSC clients).

**Why this priority**: Robustness testing. Important for production reliability
but depends on all happy-path stories being correct first.

**Independent Test**: Run `pytest -m unit -k "error_cleanup"` — uses fault
injection, no external services.

**Acceptance Scenarios**:

1. **Given** a cue whose player subprocess crashes during `run_cue()`,
   **When** the error is caught, **Then** the cue transitions to an error
   state, a full traceback is logged, and the subprocess is reaped.
2. **Given** an OSC client that raises a connection error during arm,
   **When** the error propagates, **Then** the cue is not added to the
   armed-cues list and the partially allocated resources are freed.
3. **Given** a cue in the loop phase, **When** an unhandled exception occurs,
   **Then** the cue's asyncio task does not silently die; the error is logged
   and the cue is disarmed.

---

### Edge Cases

- What happens when `go()` is called on a cue that is already running?
- What happens when `disarm()` is called while a cue's async task is mid-execution?
- What happens when the asyncio event loop is shut down while cues are still running?
- What happens when two cues share the same player (e.g., video player pool) and one errors?
- What happens when `prewait` or `postwait` is set to zero?
- What happens when `loop` is set to zero or a negative value? (`loop == 0` means no loop; `loop < 0` means infinite loop.)
- What happens when a caller invokes `CueHandler.wait_for_cue()` (currently undefined)?

## Clarifications

### Session 2026-02-26

- Q: Which object owns the asyncio event loop used for cue execution? → A: AsyncCommsThread owns multiple event loops. A dedicated cue orchestration loop (separate from the existing IPC loop) MUST be used for all cue async tasks. Tasks are submitted via run_coroutine_threadsafe from non-async callers. Tests MUST verify cue tasks run on the cue-specific loop, not on the IPC loop or ad-hoc loops.
- Q: Should the test suite cover the missing `wait_for_cue` method (called by NodeEngine but undefined in CueHandler)? → A: Yes — include a test verifying the caller can await cue task completion. This exposes the missing method as a test failure.
- Q: Should DmxCue (partially implemented) be included in the async lifecycle test matrix? → A: No — exclude DmxCue. Add tests when its implementation is complete.
- Q: Should cue tasks and IPC coroutines share the same event loop? → A: No. AsyncCommsThread MUST own two separate event loops: one for IPC (editor/hwdiscovery/nodeconf) and a new, dedicated loop for cue orchestration. Tests MUST verify cue tasks run on the cue-specific loop, not on the IPC loop.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Test suite MUST verify the complete single-cue async lifecycle
  (arm → go → prewait → run → postwait → loop → disarm) for each cue type
  (AudioCue, VideoCue, ActionCue, CueList). DmxCue is explicitly excluded
  until its implementation is complete.
- **FR-002**: Test suite MUST verify that concurrent cue execution does not
  corrupt shared state in CueHandler or PlayerHandler singletons.
- **FR-003**: Test suite MUST verify both `post_go` modes (`'go'` and
  `'go_at_end'`) chain cue execution in the correct order and timing.
- **FR-004**: Test suite MUST verify MTC polling in `loop_cue()` including
  offset recalculation, loop counter increment, and MTC disconnection.
- **FR-005**: Test suite MUST verify that failures at any lifecycle phase
  produce an error state, log a traceback, and clean up all resources.
- **FR-006**: Test suite MUST run without external hardware, media files,
  or network services — all external dependencies MUST be mocked.
- **FR-007**: Test suite MUST use pytest markers (`unit` for mocked tests,
  `integration` for tests requiring real subprocesses) consistent with
  the project's existing marker configuration.
- **FR-008**: Test suite MUST complete the full `unit`-marked subset in
  ≤ 30 seconds wall time.
- **FR-009**: Test suite MUST include thread-safety stress tests that
  exercise concurrent access to shared singletons under repeated
  invocations.
- **FR-010**: Test suite MUST verify that asyncio task cancellation during
  any lifecycle phase results in clean resource release.
- **FR-011**: Test suite MUST verify that `CueHandler.go()` submits tasks
  to AsyncCommsThread's dedicated cue orchestration loop, not to the IPC
  loop or an ad-hoc thread-local event loop.
- **FR-012**: Test suite MUST verify that cross-thread callers use
  `run_coroutine_threadsafe` to submit cue coroutines to the cue
  orchestration loop owned by AsyncCommsThread.
- **FR-013**: Test suite MUST include a test that verifies the caller
  (e.g., `NodeEngine.go_script`) can await cue task completion via
  CueHandler. This test MUST expose the currently missing `wait_for_cue`
  method as a failure until the method is implemented.
- **FR-014**: Test suite MUST verify that the cue orchestration loop and the
  IPC loop are isolated — a blocking or slow operation on one MUST NOT
  stall the other.

### Key Entities

- **Cue**: The schedulable unit of execution. Types: AudioCue, VideoCue,
  ActionCue, CueList. Key attributes: state, prewait, postwait, loop, post_go.
  `loop == 0` means no loop (play once); `loop < 0` means infinite loop.
- **AsyncCommsThread**: Daemon thread that owns multiple asyncio event loops:
  (1) an IPC loop for editor/hwdiscovery/nodeconf communication, and
  (2) a dedicated cue orchestration loop for all cue async tasks. The two
  loops MUST be isolated so IPC and cue execution cannot block each other.
- **CueHandler**: Singleton managing cue lifecycle. Maintains the armed-cues
  list and submits asyncio tasks to AsyncCommsThread's cue orchestration
  loop for each `go()` call.
- **PlayerHandler**: Singleton managing player subprocess allocation.
  Thread-safe access guarded by a lock.
- **MtcListener**: Daemon thread providing MIDI Time Code updates consumed
  by `loop_cue()` polling.
- **Player**: Thread subclass wrapping a subprocess (AudioPlayer, VideoPlayer,
  DmxPlayer). Lifecycle: start → run → kill → join.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of the acceptance scenarios defined in user stories 1–5
  have corresponding passing tests.
- **SC-002**: The `unit`-marked test subset runs in ≤ 30 s on a single core.
- **SC-003**: Branch coverage of async cue execution code paths
  (`arm_cue.py`, `CueHandler`, `PlayerHandler`) reaches ≥ 80 %.
- **SC-004**: Concurrent stress tests (≥ 50 iterations of 3 simultaneous
  cues) complete with zero race-condition failures.
- **SC-005**: Every edge case listed in this spec has at least one dedicated
  test.
- **SC-006**: The test suite introduces zero new external dependencies beyond
  what is already in `[project.optional-dependencies].dev`.
