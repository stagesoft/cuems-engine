# Contract: Action Cue Processing

## Purpose

Define the behavioral contract for processing an `ActionCue` in the node runtime so
received actions deterministically affect the running show project.

## Input Contract

### Action Cue Fields

- `id`: unique cue identifier
- `action_type`: operation to execute
- `action_target` (optional): cue identifier for cue-level actions
- `_action_target_object` (resolved runtime object, optional)

### Supported Action Types

- Cue-level: `play`, `pause`, `stop`, `enable`, `disable`, `fade-in`, `fade-out`,
  `go-to`

## Processing Contract

1. Action processing is initiated from cue execution flow and delegated to
   `CueHandler` orchestration.
2. `CueHandler` validates action type and target.
3. Execution returns a result status for each command.
4. Unsupported or invalid actions are rejected safely with no unrelated state changes.

## Output Contract

Each processed action produces one outcome:

- `applied`: valid action executed and state changed.
- `applied_no_change`: valid action already satisfied desired state.
- `rejected`: invalid/unsupported action or invalid target.
- `failed`: runtime error while attempting an otherwise valid action.

## Error and Safety Guarantees

- Unknown action types MUST NOT alter cue state.
- Missing targets for cue-level actions MUST NOT alter unrelated cues.
- Failures MUST emit operator-diagnosable log messages.

## Performance Contract

- Action processing path must remain lightweight and in-process.
- Under normal runtime load, command-to-state reflection target is <= 1 second for
  at least 95% of action commands.

## Testing Contract

- Automated verification for this feature MUST be developed and executed through the
  Poetry-managed `pytest` workflow.
- Test execution commands MUST use Poetry wrappers (for example:
  `poetry run pytest -q`).
