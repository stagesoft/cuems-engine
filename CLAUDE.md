# cuems-engine Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-14

## Active Technologies

- Python 3.11 (managed via pyenv + Poetry) (004-gradient-engine-phase6)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11 (managed via pyenv + Poetry): Follow standard conventions

## Recent Changes
- 004-gradient-engine-phase6: Added Python 3.11 (managed via pyenv + Poetry)

- 004-gradient-engine-phase6: Added Python 3.11 (managed via pyenv + Poetry)

<!-- MANUAL ADDITIONS START -->
## Constitution

The full project constitution lives at `.specify/memory/constitution.md` (v1.1.0).
All agents MUST read and apply it. Key rules reproduced here for agent visibility:

- **TDD is NON-NEGOTIABLE**: write failing test → confirm failure → implement → green → refactor.
  No production code may be written before a failing test exists.
- **SOLID principles** apply to every module, class, and function.
- **No new runtime dependency** without documented justification and team review.
- **YAGNI**: every design decision must be justified by a current, concrete requirement.
- **Observability**: structured logging for all engine events; silent failures are forbidden.

### Documentation Artifact Layout (mandatory for all agents)

Artifacts MUST be placed in the correct location — misplaced files are a constitution violation:

| Location | Purpose |
|---|---|
| `specs/NNN-feature/` | Per-feature spec, plan, tasks, design notes. Owned by the feature branch. |
| `specs/planning/` | Cross-cutting planning docs spanning multiple features (roadmaps, migration strategies, phase handoff notes). Dev-internal only. |
| `docs/` (top-level) | End-user documentation and generated API reference (Doxygen/equivalent) ONLY. Hand-written dev planning artifacts MUST NOT go here. |

When creating or moving any documentation file, check this table first.
<!-- MANUAL ADDITIONS END -->

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
