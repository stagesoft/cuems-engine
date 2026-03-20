# Feature Specification: Action Cue Execution

**Feature Branch**: `002-action-cue-handler`  
**Created**: 2026-03-19  
**Status**: Draft  
**Input**: User description: "Implement `cuemsutils.ActionCue` logic so recieved actions are implemented and affect running show project. All logic should be handled inside `CueHandler`"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Execute cue-level actions (Priority: P1)

As a show operator, I need received action cues to trigger expected cue behavior
immediately so live playback reacts correctly.

**Why this priority**: Cue-level actions directly impact live show control and are the
core expected behavior of action cues.

**Independent Test**: Send each supported cue-level action while a project is loaded
and verify the target cue state changes as expected without affecting unrelated cues.

**Acceptance Scenarios**:

1. **Given** a loaded project with armed cues, **When** an action cue to start a target
   cue is received, **Then** the target cue begins playback and its runtime state updates.
2. **Given** a running target cue, **When** a stop or disable action is received,
   **Then** the target cue stops or becomes inactive for subsequent playback.

---

### User Story 2 - Execute project-level actions (Priority: P2)

As a show operator, I need project-wide actions to affect the running show state so I
can pause and resume the full show flow safely.

**Why this priority**: Project-level actions are critical for operational control but are
secondary to basic cue action execution.

**Independent Test**: Trigger each supported project-level action while cues are active
and verify global show state transitions are applied and observable.

**Acceptance Scenarios**:

1. **Given** an active running show, **When** a project pause action is received,
   **Then** the show enters a paused state and cue progression stops until resumed.
2. **Given** a paused running show, **When** a project resume action is received,
   **Then** playback progression continues from the paused state.

---

### User Story 3 - Handle unsupported or invalid actions safely (Priority: P3)

As an operator, I need invalid action commands to fail safely so the running show
remains stable and diagnosable.

**Why this priority**: Safety and diagnosability reduce live-operation risk and prevent
silent failures.

**Independent Test**: Send invalid action types and malformed targets; verify the system
logs a clear failure and leaves current valid playback state unchanged.

**Acceptance Scenarios**:

1. **Given** an unknown action type, **When** the action is processed,
   **Then** no unintended state change occurs and a clear operational error is recorded.
2. **Given** a valid action type with a missing target, **When** the action is processed,
   **Then** the action is rejected safely and current show playback remains stable.

### Edge Cases

- Action arrives before its target cue or project context is available.
- Multiple action cues affecting the same target arrive in close succession.
- Action is received for a target that is already in the desired state.
- Action references a cue from a no-longer-active project.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST process received action cues through the centralized cue
  handling workflow.
- **FR-002**: System MUST execute supported cue-level actions so target cue state
  changes are applied to the currently running show.
- **FR-002a**: Supported cue-level actions MUST include `play`, `pause`, `stop`,
  `enable`, `disable`, `fade-in`, `fade-out`, and `go-to`.
- **FR-003**: System MUST execute supported project-level actions so global show state
  transitions are applied to the currently running project.
- **FR-004**: System MUST resolve action targets against the active project context and
  MUST reject actions with invalid or unavailable targets.
- **FR-005**: System MUST apply actions idempotently when possible (no harmful side
  effects when repeating equivalent commands).
- **FR-006**: System MUST record action processing outcomes (applied, ignored,
  rejected, failed) with enough detail for operator troubleshooting.
- **FR-007**: System MUST leave unrelated cues and project state unchanged when
  processing an action that targets a specific cue or transition.

### Non-Functional Requirements *(mandatory)*

- **NFR-001 (Code Quality)**: Action execution behavior MUST be encapsulated in a
  single cue-handling domain to keep responsibilities clear and reviewable.
- **NFR-002 (Testing)**: Automated tests MUST cover each supported action type plus
  invalid action handling and regression behavior, including `fade-in`, `fade-out`,
  and `go-to`. Tests MUST be developed and executed via the Poetry-managed `pytest`
  workflow.
- **NFR-003 (UX Consistency)**: Action outcomes and error messaging MUST be
  consistent with existing show-control terminology and status semantics.
- **NFR-004 (Performance)**: Action processing MUST complete quickly enough for live
  operations and MUST not introduce observable playback jitter.

### Key Entities *(include if feature involves data)*

- **Action Command**: A received instruction describing action type, target, and timing
  intent for live show control.
- **Action Target**: The cue or project-level state object that the action command
  intends to modify.
- **Show Runtime State**: The current in-memory state of running cues and project
  playback mode used to apply and validate actions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of supported action types produce the expected state transition in
  acceptance tests for cue-level and project-level flows, including `fade-in`,
  `fade-out`, and `go-to`.
- **SC-002**: 100% of invalid or unsupported actions are safely rejected without
  unintended changes to unrelated running cues.
- **SC-003**: Action results (success or failure) are visible in operational logs for
  100% of processed action commands.
- **SC-004**: In validation runs, action-triggered state changes are reflected within
  1 second for at least 95% of commands during normal show load.
- **SC-005**: Regression tests for existing cue playback behavior remain fully passing
  after action execution support is introduced.

## Assumptions

- The active project is already loaded before action cues are processed.
- A finite set of action types is defined by the cue data contract and treated as
  supported for this feature.
- Existing operator workflows for running, pausing, and resuming shows remain the
  baseline behavior model.
