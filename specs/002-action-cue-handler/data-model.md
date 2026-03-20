# Data Model: Action Cue Handler Execution

## Entity: ActionCommand

Represents a received action instruction to be applied during show runtime.

### Fields

- `action_type` (string, required): cue-level command category.
- `action_target` (string, optional): identifier of target cue for cue-level actions.
- `_action_target_object` (object, optional): resolved in-memory cue reference.
- `source_cue_id` (string, required): the `ActionCue` ID that emitted the command.

### Validation Rules

- `action_type` MUST map to a supported cue-level command set or be explicitly rejected.
- Cue-level actions MUST have a valid resolved target object.

### Supported Cue-Level Action Types

- `play`, `pause`, `stop`, `enable`, `disable`, `fade-in`, `fade-out`, `go-to`

## Entity: ActionTarget

Runtime target that receives the state transition.

### Variants

- `CueTarget`: cue object in the active script.

### Validation Rules

- Target MUST belong to active project context.
- Target transitions MUST not mutate unrelated cue/runtime objects.

## Entity: ActionExecutionResult

Outcome record for each processed command.

### Fields

- `status` (enum): `applied`, `applied_no_change`, `rejected`, `failed`.
- `reason` (string): human-readable reason for rejected/failed outcomes.
- `target_id` (string, optional): affected cue identifier.
- `timestamp` (runtime value): event emission time.

### Validation Rules

- Every processed action MUST produce one result outcome.
- Rejected/failed outcomes MUST include reason text.

## State Transitions

### Cue-Level

- `play` -> target enters running state.
- `pause` -> target enters paused state (if supported by target type).
- `stop` -> target exits running state.
- `fade-in` -> target ramps into active playback/output state.
- `fade-out` -> target ramps down and exits active playback/output state.
- `go-to` -> execution pointer navigates to the specified target cue.
- `enable` / `disable` -> target eligibility for execution toggles.

### Invalid Transitions

- Unknown `action_type` -> `rejected` with no state mutation.
- Missing/unresolvable target for cue-level action -> `rejected` with no state mutation.
