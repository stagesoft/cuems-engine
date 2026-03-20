# Implementation Plan: Action Cue Handler Execution

**Branch**: `002-action-cue-handler` | **Date**: 2026-03-20 | **Spec**: `/disk/Projects/StageLab/cuems-engine/specs/002-action-cue-handler/spec.md`
**Input**: Feature specification from `/disk/Projects/StageLab/cuems-engine/specs/002-action-cue-handler/spec.md`

## Summary

Implement executable `ActionCue` behavior so received action cues affect cue state and
project runtime state through a single orchestration domain in `CueHandler`. The plan
keeps cue execution routing centralized, provides deterministic handling for unsupported
actions, and adds automated verification for cue-level and project-level transitions.
Supported cue-level actions explicitly include `fade-in`, `fade-out`, and `go-to`.

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: `cuemsutils` cue types, `pytest`, existing engine runtime
services (`BaseEngine`, `NodeEngine`, `CueHandler`)  
**Storage**: N/A (in-memory show runtime state)  
**Testing**: Poetry-managed `pytest` (`poetry run pytest`) with unit and integration
coverage in `tests/`  
**Target Platform**: Linux node/controller runtime environment  
**Project Type**: Single Python package/service runtime  
**Performance Goals**: 95% of action commands reflected in runtime state within 1 second  
**Constraints**: Preserve existing cue playback behavior; no cross-project side effects;
logic concentrated in cue-handling layer  
**Scale/Scope**: Action processing for loaded active project across local cue graph

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Code Quality Gate**: PASS  
  Implementation boundary set to `src/cuemsengine/cues/CueHandler.py` orchestration and
  existing cue dispatch modules. New behavior is centralized instead of distributed.
- **Testing Gate**: PASS  
  Plan requires regression tests for supported actions, unknown actions, missing targets,
  and non-target side-effect protection, developed and executed through Poetry with
  `pytest`.
- **UX Consistency Gate**: PASS  
  Action outcomes use existing cue/show control semantics (go, stop, pause, resume,
  enabled/disabled, fade-in, fade-out, go-to) and current operator-facing logging style.
- **Performance Gate**: PASS  
  Action execution remains in-process and bounded; plan includes latency validation under
  normal command flow (no polling loop additions).

## Project Structure

### Documentation (this feature)

```text
specs/002-action-cue-handler/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── action-cue-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
src/
└── cuemsengine/
    ├── cues/
    │   ├── CueHandler.py
    │   ├── run_cue.py
    │   └── loop_cue.py
    ├── core/
    │   └── BaseEngine.py
    └── NodeEngine.py

tests/
├── test_core_baseengine.py
├── test_project_go.py
└── test_*.py
```

**Structure Decision**: Keep a single-project Python layout and implement behavior inside
the existing cue orchestration path, with tests added under `tests/` in current style.

## Phase 0 Research Outcomes

See `research.md`. All technical unknowns were resolved: action handling remains in cue
domain, project-level action propagation uses existing engine state/control interfaces,
and unsupported actions fail safely with explicit logging.

## Phase 1 Design Outputs

- Data model: `data-model.md`
- Contracts: `contracts/action-cue-contract.md`
- Validation walkthrough: `quickstart.md`
- Agent context update: executed via `.specify/scripts/bash/update-agent-context.sh cursor-agent`

## Post-Design Constitution Re-Check

- **Code Quality Gate**: PASS - design keeps a single action orchestration entrypoint.
- **Testing Gate**: PASS - design requires direct coverage for all supported action types.
- **UX Consistency Gate**: PASS - naming and outcomes map to existing show-control terms.
- **Performance Gate**: PASS - no new long-running loops; action path remains O(1) per command.

## Complexity Tracking

No constitution violations requiring justification.
