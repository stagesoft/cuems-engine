<!--
  Sync Impact Report
  ═══════════════════
  Version change: 0.0.0 → 1.0.0 (initial ratification)
  Added principles:
    - I. Code Quality & Consistency
    - II. Testing Discipline
    - III. Real-Time Performance
    - IV. User Experience Consistency
    - V. Reliability & Fault Tolerance
  Added sections:
    - Performance & Resource Standards
    - Development Workflow & Quality Gates
  Templates requiring updates:
    - plan-template.md   ✅ no changes needed (Constitution Check is dynamic)
    - spec-template.md   ✅ no changes needed (requirements section is generic)
    - tasks-template.md  ✅ no changes needed (phase structure is generic)
  Follow-up TODOs: none
-->

# CueMS Engine Constitution

## Core Principles

### I. Code Quality & Consistency

All Python source MUST comply with `black` (line-length 88) and `isort`
(profile black). `flake8` MUST pass with zero warnings before merge.

- Every public function and class MUST have a type-annotated signature.
- Module-level docstrings MUST state the module's single responsibility.
- Circular imports are forbidden; dependency direction flows inward
  (utilities → models → services → controllers → scripts).
- Magic numbers and string literals used more than once MUST be named
  constants.

**Rationale**: The engine mixes async control, multiprocess IPC, and
real-time media protocols. Strict formatting and type discipline prevent
an entire class of integration bugs.

### II. Testing Discipline

Every merged feature MUST include tests. The test suite uses `pytest`
with markers `unit`, `integration`, `slow`, and `cuems`.

- **Unit tests** (`@pytest.mark.unit`): Pure logic, no I/O, no
  subprocesses. Target: ≥ 80 % branch coverage on `src/`.
- **Integration tests** (`@pytest.mark.integration`): Validate IPC,
  OSC, MIDI, and player-subprocess contracts. May use fixtures that
  start/stop real processes.
- **Cuems tests** (`@pytest.mark.cuems`): Full engine lifecycle tests
  that require running CueMS node/controller engines. Automatic cleanup
  MUST be enforced via fixtures.
- Tests MUST be deterministic. Flaky tests MUST be quarantined
  immediately with a linked issue.
- `pytest --strict-markers --strict-config` MUST remain enabled.

**Rationale**: A show-control system cannot ship regressions that
surface during a live performance. Rigorous, layered testing is the
primary safety net.

### III. Real-Time Performance

Operations on the critical playback path MUST meet hard latency budgets:

- **Cue trigger → first media frame**: ≤ 50 ms.
- **OSC/MIDI message processing**: ≤ 5 ms per message.
- **State-machine transitions** (go, pause, stop): ≤ 10 ms excluding
  media-player startup.

Non-negotiable rules:

- No blocking I/O on the main event loop or any thread that handles
  cue execution.
- Subprocess and socket operations MUST use timeouts; infinite waits
  are forbidden.
- Memory-intensive allocations (media loading, XML parsing) MUST occur
  outside the hot path (e.g., during arm/preload).
- CPU-bound work MUST be offloaded to worker processes; the controller
  loop stays responsive.

**Rationale**: CueMS drives live shows. A missed cue or a stalled UI
is a production-visible failure with no retry opportunity.

### IV. User Experience Consistency

All cue types MUST present a uniform lifecycle to operators and API
consumers:

- Every cue MUST implement the canonical state machine:
  `idle → armed → running → (paused ↔ running) → stopped → idle`.
- Error states MUST surface through a consistent reporting channel
  (OSC status messages, log entries) with human-readable descriptions.
- Configuration changes (XML edits, OSC commands) MUST validate inputs
  before mutating state; invalid input MUST be rejected with a clear
  diagnostic, never silently ignored.
- Behavioral differences between cue types (audio, video, DMX, action)
  MUST be limited to the media-specific layer; the control API MUST
  remain identical.

**Rationale**: Operators learn one mental model and trust it across all
media types. Inconsistency erodes confidence during high-pressure live
operation.

### V. Reliability & Fault Tolerance

The engine MUST degrade gracefully; a single subsystem failure MUST NOT
cascade to unrelated cues or crash the controller.

- Every spawned subprocess MUST be tracked and cleaned up on shutdown,
  crash, or signal (SIGTERM, SIGINT).
- IPC channels (Unix sockets, OSC ports) MUST implement reconnection
  or explicit failure notification within 2 s of disconnection.
- Resource leaks (file descriptors, zombie processes, leaked threads)
  are P0 bugs.
- All exception handlers on the critical path MUST log the full
  traceback and transition the affected cue to an error state rather
  than swallowing the exception.

**Rationale**: Show-control software runs unattended for hours. Silent
resource leaks and swallowed exceptions compound into system-wide
failures at the worst possible moment.

## Performance & Resource Standards

| Metric | Target | Measurement |
|---|---|---|
| Cue trigger latency | ≤ 50 ms p99 | Timestamp delta: OSC go → first media callback |
| Idle CPU (controller) | < 3 % single core | `top`/`psutil` with no active cues |
| Memory per cue player | < 50 MB RSS | `psutil.Process.memory_info()` |
| Subprocess startup | ≤ 200 ms | arm → ready ACK |
| Graceful shutdown | ≤ 2 s | SIGTERM → all children reaped |
| Test suite (unit) | ≤ 30 s | `pytest -m unit` wall time |

Performance regressions against these targets MUST be treated as bugs.
New features that cannot meet the latency budget MUST document the
deviation and obtain explicit approval before merge.

## Development Workflow & Quality Gates

### Branch & Commit

- Feature branches follow `feat/<topic>`, bug fixes `fix/<topic>`.
- Commits MUST be atomic and pass the full `unit` test suite
  individually (`git rebase --exec "pytest -m unit"`).

### Pre-Merge Checklist

1. `black --check .` and `isort --check .` pass.
2. `flake8` reports zero issues.
3. `pytest -m "unit"` passes with ≥ 80 % branch coverage.
4. `pytest -m "integration"` passes (may be run in CI only if hardware
   dependent).
5. No new `# type: ignore` without an inline justification comment.
6. No new `TODO` without a linked issue identifier.

### Code Review

- Every PR MUST be reviewed by at least one other contributor.
- Reviewer MUST verify constitution compliance for changed modules.
- Performance-sensitive changes MUST include benchmark evidence.

## Governance

This constitution is the highest-authority document for engineering
decisions in `cuems-engine`. It supersedes informal conventions,
chat agreements, and individual preferences.

- **Amendments** require: (1) a written proposal referencing the
  principle(s) affected, (2) approval from at least one maintainer,
  (3) a version bump following SemVer rules below.
- **Versioning**: MAJOR for principle removal/redefinition, MINOR for
  new principles or material expansion, PATCH for clarifications.
- **Compliance review**: At least once per release cycle, the team
  MUST audit the codebase against these principles and file issues for
  any violations found.

**Version**: 1.0.0 | **Ratified**: 2026-02-26 | **Last Amended**: 2026-02-26
