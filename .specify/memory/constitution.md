<!--
SYNC IMPACT REPORT
==================
Version change: [TEMPLATE] → 1.0.0
Status: Initial ratification — all placeholders replaced

Added sections:
  - I. SOLID Design Principles (new)
  - II. Test-Driven Development (new, NON-NEGOTIABLE)
  - III. Integration & Contract Testing (new)
  - IV. Simplicity & YAGNI (new)
  - V. Observability & Reliability (new)
  - Technology & Architecture Standards (new)
  - Development Workflow (new)
  - Governance (new)

Removed sections: none

Templates reviewed:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate present; no updates needed
  ✅ .specify/templates/spec-template.md — "User Scenarios & Testing (mandatory)" aligns with TDD principle
  ✅ .specify/templates/tasks-template.md — TDD language ("Tests MUST fail before implementation") already present
  ✅ No command template files found in .specify/templates/commands/

Deferred TODOs: none
-->

# CueMs Engine Constitution

## Core Principles

### I. SOLID Design Principles

Every module, class, and function in the codebase MUST adhere to the five SOLID principles:

- **Single Responsibility**: Each class or module MUST have one, and only one, reason to change.
  No class may conflate orchestration, business logic, I/O, and communication concerns.
- **Open/Closed**: Components MUST be open for extension and closed for modification.
  New cue types, player backends, and transport protocols MUST be added without modifying
  existing stable abstractions.
- **Liskov Substitution**: Subtypes MUST be substitutable for their base types without altering
  correctness. Any concrete Engine, Player, or Cue class MUST honour the contract of its interface.
- **Interface Segregation**: No component MUST depend on interfaces it does not use.
  Large god-interfaces MUST be split into focused protocols (e.g., separate `Playable`,
  `Stoppable`, `Seekable`).
- **Dependency Inversion**: High-level modules (ControllerEngine, NodeEngine) MUST depend on
  abstractions, not on concrete implementations. Dependencies MUST be injected, not constructed
  internally.

Rationale: The engine coordinates heterogeneous subsystems (OSC, media players, cues) across a
distributed controller/node topology. SOLID boundaries are the primary defence against coupling
that would make the system fragile in live-performance contexts.

### II. Test-Driven Development (NON-NEGOTIABLE)

TDD is MANDATORY for all production code changes. The Red-Green-Refactor cycle MUST be followed:

1. Write a failing test that precisely describes the intended behaviour.
2. Obtain explicit confirmation that the test suite shows the test failing.
3. Write the minimum production code required to make the test pass.
4. Refactor without changing observable behaviour, keeping all tests green.

No implementation code MAY be merged without a prior failing test. Tests are the specification;
implementation is the proof. Bypassing TDD (e.g., writing code first and retrofitting tests)
constitutes a constitution violation and MUST be flagged in code review.

Rationale: Live performance software has zero tolerance for regressions at showtime. TDD provides
the only reliable safety net in a codebase where a broken cue or timing error causes an immediate
visible failure in front of an audience.

### III. Integration & Contract Testing

Integration tests MUST cover every inter-component boundary:

- ControllerEngine ↔ NodeEngine communication (OSC and network).
- NodeEngine ↔ media player subprocess interactions.
- Engine ↔ settings.xml configuration parsing.
- Any new public CLI or IPC contract introduced.

Contract tests MUST be written before integration work begins (TDD applies here too).
Integration tests MUST run against real subsystems, not mocks, unless a subsystem is an
external third-party service with no test double available.

Rationale: The controller/node split means integration faults are the most common production
failures. Mocking OSC and subprocess boundaries has historically masked bugs that only surface
at runtime on stage hardware.

### IV. Simplicity & YAGNI

Every design decision MUST be justified by a current, concrete requirement — not a hypothetical
future one. Premature abstractions, unused extension points, and speculative generality are
constitution violations.

Rules:
- Three similar code blocks are acceptable before introducing an abstraction.
- A new dependency MUST solve a problem that cannot be solved with the standard library or
  existing project dependencies.
- No feature flag, compatibility shim, or dead code path MAY be introduced.
- Complexity, when unavoidable, MUST be documented with a single-line comment explaining WHY,
  not WHAT.

Rationale: CueMs runs on stage hardware with constrained resources and must be maintainable by
a small team under time pressure. Every unnecessary abstraction is a future liability.

### V. Observability & Reliability

All production code paths MUST be observable:

- Structured logging MUST be used for all engine events (cue execution, player start/stop,
  node communication, errors).
- Timing-sensitive operations (latency compensation, OSC dispatch) MUST emit measurable
  metrics or structured log entries sufficient to diagnose drift.
- Errors MUST be reported with enough context (component, cue ID, node, timestamp) to
  diagnose without replication.
- Silent failures are forbidden; every caught exception MUST be logged or re-raised.

Rationale: Stage problems must be diagnosable from logs alone, without attaching a debugger
to a running show.

## Technology & Architecture Standards

- **Language**: Python 3.11 (managed via pyenv; virtualenv via Poetry).
- **Packaging**: Poetry (`pyproject.toml`). No ad-hoc `setup.py` additions.
- **Test framework**: pytest. Test files live under `tests/` at repository root, mirroring
  `src/cuemsengine/` structure.
- **Linting / formatting**: Enforced via project toolchain; CI MUST block on lint failures.
- **Communication**: OSC for real-time engine-to-node messaging; XML (`settings.xml`) for
  static configuration.
- **Distribution**: Debian package (`cuems-engine` deb). The `scripts/link-dev.sh` symlink
  workflow MUST remain supported for developer iteration.
- **License**: GPL-3.0. All new source files MUST carry the appropriate SPDX header.

No new runtime dependency MAY be added without a documented justification and team review.

## Development Workflow

1. **Spec first**: Every non-trivial change MUST have a feature spec (`/speckit.spec`) and
   implementation plan (`/speckit.plan`) before coding begins.
2. **TDD cycle**: Write failing test → confirm failure → implement → green → refactor.
3. **Constitution Check**: The `plan.md` constitution check gate MUST pass before any Phase 0
   research begins, and MUST be re-verified after Phase 1 design.
4. **PR discipline**: Each PR MUST reference its spec, include test evidence (CI pass), and
   receive at least one peer review.
5. **Commit hygiene**: Commits MUST be atomic (one logical change), with a conventional-commit
   style message. Force-pushes to `master` are forbidden.
6. **Dev install**: Use `scripts/link-dev.sh` during development; never commit changes that
   only work with the installed deb package.

## Governance

This constitution supersedes all other informal practices, prior verbal agreements, and
individual preferences. Amendments require:

1. A written proposal describing the change and its rationale.
2. Consensus among active contributors (StageLab team).
3. A version bump per the versioning policy below and an update to `LAST_AMENDED_DATE`.
4. Propagation of changes to all dependent templates (plan, spec, tasks).

**Versioning policy**:
- **MAJOR**: Backward-incompatible governance changes — removal or fundamental redefinition
  of a core principle.
- **MINOR**: New principle, new mandatory section, or materially expanded guidance.
- **PATCH**: Clarifications, wording corrections, non-semantic refinements.

All PRs and code reviews MUST verify compliance with the principles above. Complexity
violations must be documented in the plan's Complexity Tracking table before merging.
Runtime development guidance lives in `.specify/memory/` and agent configuration files.

**Version**: 1.0.0 | **Ratified**: 2026-04-27 | **Last Amended**: 2026-04-27
