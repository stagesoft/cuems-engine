<!--
Sync Impact Report
- Version change: N/A (template) -> 1.0.0
- Modified principles:
  - Placeholder Principle 1 -> I. Code Quality Is Non-Negotiable
  - Placeholder Principle 2 -> II. Testing Evidence Is Required
  - Placeholder Principle 3 -> III. User Experience Must Stay Consistent
  - Placeholder Principle 4 -> IV. Performance Budgets Are First-Class Requirements
  - Placeholder Principle 5 -> V. Small, Reviewable, and Reversible Delivery
- Added sections:
  - Operational Standards
  - Delivery Workflow & Quality Gates
- Removed sections:
  - None
- Templates requiring updates:
  - ✅ updated: .specify/templates/plan-template.md
  - ✅ updated: .specify/templates/spec-template.md
  - ✅ updated: .specify/templates/tasks-template.md
  - ⚠ pending: .specify/templates/commands/*.md (directory not present in repository)
  - ✅ updated: README.md
- Follow-up TODOs:
  - None
-->
# CueMs Engine Constitution

## Core Principles

### I. Code Quality Is Non-Negotiable
All production code MUST be readable, deterministic, and maintainable. Changes MUST
preserve existing architectural boundaries, include clear naming, and avoid hidden side
effects. Every change MUST pass formatting, linting, and static checks before merge.
Rationale: defects and ambiguity compound quickly in engine software and directly raise
operational risk.

### II. Testing Evidence Is Required
Every behavior change MUST be backed by automated tests at the appropriate level
(unit, integration, or contract). Bug fixes MUST include a regression test that fails
before the fix and passes after it. A feature is incomplete until tests and local quality
gates pass with evidence captured in the implementing work.
Rationale: unverified changes are unacceptable in cue execution and timing-sensitive flows.

### III. User Experience Must Stay Consistent
User-facing behavior MUST remain predictable across interfaces, workflows, and error
handling. Similar operations MUST use consistent terminology, interaction patterns,
and response formats. Any intentional UX deviation MUST be documented in the spec
with explicit rationale and acceptance criteria.
Rationale: operators rely on stable interaction patterns under live show conditions.

### IV. Performance Budgets Are First-Class Requirements
Each feature MUST define measurable performance targets (latency, throughput, memory,
or startup cost) relevant to its path. Implementations MUST not degrade critical
workflows beyond agreed budgets. Performance-sensitive changes MUST include benchmark
or profiling evidence proportional to risk.
Rationale: timing fidelity and responsiveness are core product characteristics.

### V. Small, Reviewable, and Reversible Delivery
Work MUST be delivered in small increments with clear intent, bounded scope, and
rollback-safe behavior. Pull requests MUST include: requirements traceability, test
evidence, UX impact notes, and performance impact notes. Large refactors MUST be
split into staged changes whenever feasible.
Rationale: smaller increments reduce regressions and improve review quality.

## Operational Standards

- Specifications MUST include functional requirements, UX consistency expectations,
  testing strategy, and measurable performance criteria.
- Plans MUST define explicit Constitution Check gates for code quality, testing, UX,
  and performance before implementation starts.
- Tasks MUST include work items for automated tests, UX validation, and performance
  verification when behavior can impact user workflows or runtime characteristics.
- Reviewers MUST block merges that lack evidence for any mandatory gate.

## Delivery Workflow & Quality Gates

1. Define scope with explicit acceptance criteria and measurable outcomes.
2. Run Constitution Check during planning and re-run after design decisions.
3. Implement in small slices with corresponding tests and documentation updates.
4. Validate with lint/static checks, automated tests, and targeted performance checks.
5. Review for UX consistency and operational safety before merge.

## Governance

This constitution supersedes conflicting local practices for feature definition, planning,
and implementation in this repository.

Amendment policy:
- Any amendment MUST include a clear rationale and explicit impact on templates.
- Versioning policy uses semantic versioning for governance:
  - MAJOR: Removing or redefining a principle in a backward-incompatible way.
  - MINOR: Adding a principle/section or materially expanding obligations.
  - PATCH: Clarifications or editorial improvements without new obligations.
- Compliance review is mandatory in planning, implementation, and review workflows.
  Non-compliant work MUST be corrected before merge.

**Version**: 1.0.0 | **Ratified**: 2026-03-20 | **Last Amended**: 2026-03-20
