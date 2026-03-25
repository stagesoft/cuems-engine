# Implementation Plan: Dedicated Action Handler with Extensibility

**Branch**: `003-action-handler-extract` | **Date**: 2026-03-25 | **Spec**: `/disk/Projects/StageLab/cuems-engine/specs/003-action-handler-extract/spec.md`  
**Input**: Feature specification from `/disk/Projects/StageLab/cuems-engine/specs/003-action-handler-extract/spec.md`, plus planning note: external methods registrable from both `CueHandler` and `NodeEngine`; result output via NNG through `NodeCommunications` or a specific `AsyncCommsThread` subclass allowed.

## Summary

Extract action-cue execution from `CueHandler` into a dedicated `ActionHandler` module
(or class) that owns validation, dispatch, and per-action-type behavior. Provide
documented hook points for externally supplied callables, with **two registration
surfaces**: the cue orchestration singleton (`CueHandler`) and the node runtime
(`NodeEngine`), using a single merged registry with explicit precedence (see
`research.md`). Support **injectable result delivery**: default sends use the existing
`NodeCommunications` / `NodesHub` path (`send_operation`); tests and integrators may
supply an alternative implementing the same async send contract (another
`AsyncCommsThread` subclass or a thin adapter). Preserve behavioral parity with the
current action-cue baseline (feature `002-action-cue-handler`).

## Technical Context

**Language/Version**: Python 3.11  
**Primary Dependencies**: `cuemsutils` cue types, existing `CueHandler`, `NodeEngine`,
`NodeCommunications` (`AsyncCommsThread` + `NodesHub`), `pytest`, Poetry  
**Storage**: N/A (in-memory runtime)  
**Testing**: Poetry-managed `pytest` (`poetry run pytest`)  
**Target Platform**: Linux node runtime  
**Project Type**: Single Python package (`cuemsengine`)  
**Performance Goals**: No regression vs prior action path; retain ≤1s / ≥95% reflection
budget where applicable (see spec NFR-004 / SC-009).  
**Constraints**: Thread-safe registration; NNG sends must remain on the comms thread’s
event loop (`run_coroutine`); no blocking the NNG receiver.  
**Scale/Scope**: One node, many action commands per show; dual registration sources and
optional custom send sink.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Code Quality Gate**: PASS — Boundaries: new `ActionHandler` (or
  `cuemsengine/cues/action_handler.py`), thin delegation from `CueHandler` and wiring
  from `NodeEngine`; `ruff`/`black`/`isort` on touched modules.
- **Testing Gate**: PASS — Regression: existing `tests/test_action_cue.py` updated or
  mirrored; new tests for (1) hook invocation, (2) registration from both entry points,
  (3) mock/inject send sink receiving outcomes.
- **UX Consistency Gate**: PASS — Log messages and outcome vocabulary unchanged unless
  spec explicitly approves; extension errors logged with same severity patterns as today.
- **Performance Gate**: PASS — Action path remains in-process dispatch + optional
  `send_operation`; benchmark or timing test on hot path optional but recommended if send
  sink adds work.

## Project Structure

### Documentation (this feature)

```text
specs/003-action-handler-extract/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── action-handler-extensibility.md
└── tasks.md              # (/speckit.tasks — not created by this command)
```

### Source Code (repository root)

```text
src/cuemsengine/
├── cues/
│   ├── CueHandler.py          # delegates action execution; may expose register_* helpers
│   ├── run_cue.py             # unchanged delegation pattern to handler entry
│   └── action_handler.py      # NEW: ActionHandler + registry + hooks (planned)
├── comms/
│   ├── NodeCommunications.py  # default result sink / NNG send
│   └── AsyncCommsThread.py    # base for thread-safe coroutine dispatch
├── NodeEngine.py              # optional registration + inject send sink if needed
tests/
└── test_action_cue.py         # extend for hooks, dual registration, sink
```

**Structure Decision**: Add `action_handler.py` under `cues/`; keep `NodeCommunications`
as default outbound path; avoid duplicating `NodesHub` logic inside `ActionHandler`.

## Phase 0 Research Outcomes

See `research.md`.

## Phase 1 Design Outputs

- Data model: `data-model.md`
- Contracts: `contracts/action-handler-extensibility.md`
- Validation walkthrough: `quickstart.md`
- Agent context: run `.specify/scripts/bash/update-agent-context.sh cursor-agent`

## Post-Design Constitution Re-Check

- **Code Quality Gate**: PASS — Single action domain module; explicit interfaces for
  hooks and send sink.
- **Testing Gate**: PASS — Contract tests listed in quickstart.
- **UX Consistency Gate**: PASS — Outcome taxonomy unchanged.
- **Performance Gate**: PASS — Send remains async via existing thread machinery.

## Complexity Tracking

No constitution violations requiring justification.
