# cuems-engine Agent Guidelines

## Constitution (Mandatory)

The authoritative constitution is `.specify/memory/constitution.md` (v1.1.0).
All agents MUST read and apply it before substantive planning, implementation, or review.

Required principles:

- **SOLID**: keep responsibilities focused and depend on abstractions.
- **TDD (non-negotiable)**: failing test -> confirm failure -> minimal implementation -> green -> refactor.
- **Integration and contract testing**: cover component boundaries with realistic integration tests.
- **YAGNI and simplicity**: avoid speculative abstractions, dead paths, and unnecessary dependencies.
- **Observability and reliability**: structured logging for engine events; no silent failures.
- **Dependency governance**: no new runtime dependency without documented justification and team review.

## Project Standards

- Language/runtime: Python 3.11 managed via Poetry.
- Tests: `pytest` under `tests/`.
- Lint/format: project toolchain and CI quality gates must pass.

## Documentation Placement (Mandatory)

- `specs/NNN-feature/`: per-feature specs, plans, tasks, design artifacts.
- `specs/planning/`: cross-feature planning and migration/refactor notes.
- `docs/`: end-user docs and generated API reference only.

## Active Technologies
- Python 3.11 (managed via pyenv + Poetry) (004-gradient-engine-phase6)

## Recent Changes
- 004-gradient-engine-phase6: Added Python 3.11 (managed via pyenv + Poetry)
