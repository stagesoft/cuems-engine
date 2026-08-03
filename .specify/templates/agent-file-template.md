# [PROJECT NAME] Development Guidelines

Auto-generated from all feature plans. Last updated: [DATE]

## Active Technologies

[EXTRACTED FROM ALL PLAN.MD FILES]

## Project Structure

```text
[ACTUAL STRUCTURE FROM PLANS]
```

## Commands

[ONLY COMMANDS FOR ACTIVE TECHNOLOGIES]

## Code Style

[LANGUAGE-SPECIFIC, ONLY FOR LANGUAGES IN USE]

## Recent Changes

[LAST 3 FEATURES AND WHAT THEY ADDED]

<!-- MANUAL ADDITIONS START -->
## Constitution

The authoritative project constitution is `.specify/memory/constitution.md`.
All agents MUST read and apply it before substantive planning, implementation, or review.

Non-negotiable principles:

- **SOLID** across modules, classes, and functions.
- **TDD is mandatory**: failing test -> confirm fail -> implement -> green -> refactor.
- **Integration and contract testing** across component boundaries.
- **YAGNI and simplicity**: no speculative abstractions or dead paths.
- **Observability**: structured logging required; silent failures forbidden.
- **No new runtime dependency** without documented justification and team review.

Documentation placement rules:

- `specs/NNN-feature/`: feature-local spec/plan/tasks/design notes.
- `specs/planning/`: cross-feature planning artifacts.
- `docs/`: end-user documentation and generated API reference only.

<!-- MANUAL ADDITIONS END -->
