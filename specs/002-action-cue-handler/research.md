# Research: Action Cue Handler Execution

## Decision 1: Keep ActionCue orchestration in `CueHandler`

- **Decision**: Route action execution through `CueHandler` as the orchestration layer,
  with `run_cue` delegating to it for `ActionCue`.
- **Rationale**: This satisfies the feature constraint that logic is handled in
  `CueHandler`, reduces duplicated branching, and keeps cue behavior in one lifecycle
  domain (arm/go/disarm + runtime updates).
- **Alternatives considered**:
  - Keep action branching only in `run_cue`: rejected because behavior remains fragmented.
  - Move logic to `BaseEngine`: rejected because it breaks cue-domain separation.

## Decision 2: Supported cue-level action set

- **Decision**: Supported cue-level actions include `play`, `pause`, `stop`, `enable`,
  `disable`, `fade-in`, `fade-out`, and `go-to`.
- **Rationale**: The planned feature must cover transition and navigation controls, not
  only binary execution toggles.
- **Alternatives considered**:
  - Defer `fade-in`/`fade-out`/`go-to`: rejected because it leaves expected action types
    undocumented across planning artifacts.

## Decision 3: Fail-safe behavior for unsupported/invalid actions

- **Decision**: Unsupported `action_type` or unresolved target is rejected with clear
  logging and no state mutation.
- **Rationale**: Live-show safety requires deterministic no-op on invalid commands rather
  than partial state changes.
- **Alternatives considered**:
  - Silent ignore: rejected due to poor diagnosability.
  - Exception propagation to caller: rejected because it can destabilize runtime flow.

## Decision 4: Idempotent state transitions

- **Decision**: Repeated equivalent actions (e.g., enable already-enabled cue) are
  treated as applied-without-change and do not trigger harmful side effects.
- **Rationale**: Received commands may duplicate under network retries; behavior must
  remain stable.
- **Alternatives considered**:
  - Hard error on duplicate command: rejected due to operator friction.
  - Always re-apply side effects: rejected due to risk of unnecessary transitions.

## Decision 5: Verification strategy

- **Decision**: Add targeted Poetry-managed `pytest` coverage for:
  - supported cue-level actions
  - `fade-in`, `fade-out`, and `go-to` behavior
  - invalid/unsupported actions
  - non-target side-effect protection
- **Rationale**: Constitution requires testing evidence for behavior changes and
  regression protection; using Poetry as the execution wrapper keeps dependencies and
  test runs consistent across environments.
- **Alternatives considered**:
  - Manual testing only: rejected by constitution testing principle.
  - Integration-only tests: rejected because unit-level action branching needs fast checks.
