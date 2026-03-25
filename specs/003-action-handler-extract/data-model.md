# Data Model: Action Handler Extensibility

## Entity: ActionHandlerConfig

Runtime configuration for the dedicated action-handling component.

### Fields

- `cue_handler_ref`: reference to cue orchestration (for `arm`, `go`, armed lookups).
- `default_result_sink`: optional; if absent, derive from `cue_handler_ref.communications_thread`.
- `registry`: extension registry (see below).

### Validation Rules

- `cue_handler_ref` MUST be non-null before processing actions.
- If `default_result_sink` is null, `communications_thread` on the cue handler MUST be
  available for default NNG-backed sends when outcomes are emitted to the controller.

## Entity: ExtensionRegistration

### Fields

- `hook_id`: enum-like string, e.g. `before_dispatch`, `after_dispatch`, `wrap_dispatch`.
- `action_type_filter`: `None` (all) or specific action type string.
- `source`: `cue_layer` | `node_layer` (for diagnostics and ordering).
- `callable`: externally supplied behavior.
- `registered_at`: monotonic or wall clock for tie-breaking if needed.

### Validation Rules

- Registrations MUST be thread-safe (mutex around registry mutations).
- Duplicate `(hook_id, action_type_filter, phase)` follows product rule FR-008 (planned:
  last wins).

## Entity: ActionProcessingOutcome

Aligned with existing dict / contract (applied, applied_no_change, rejected, failed).

### Fields

- `status`: outcome category.
- `action_type`: string.
- `target_id`: optional cue id.
- `reason`: optional human-readable text.
- `source_cue_id`: optional ActionCue id.

### Validation Rules

- Exactly one outcome per processed action command.
- Suitable for logging and optional emission via result sink.

## Entity: ResultDeliverySink (conceptual interface)

### Operations

- `emit(outcome: ActionProcessingOutcome)` or equivalent async-safe method that schedules
  NNG send on the comms thread.

### Validation Rules

- MUST NOT block the NNG receive path indefinitely.
- Default implementation uses `NodeCommunications.send_operation` (or existing helpers).

## State Transitions

- **Register** → registry updated; no cue state change.
- **Execute action** → hooks run → handler mutates target cue state → outcome emitted
  (if enabled) → `after_dispatch` hooks run.
