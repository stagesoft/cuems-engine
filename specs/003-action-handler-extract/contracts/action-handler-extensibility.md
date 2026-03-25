# Contract: Action Handler Extensibility

## Purpose

Define how action cues are executed after extraction from `CueHandler`, how extensions
register from **CueHandler** and **NodeEngine**, and how **results** reach the controller
via NNG.

## Orchestration Contract

1. `run_cue` dispatches `ActionCue` to the dedicated `ActionHandler.execute_action`.
2. `CueHandler` no longer contains per-action-type handler bodies; it may expose thin
   `register_action_hook(...)` helpers that forward to `ActionHandler`.
3. `NodeEngine` MAY call the same registration API during startup (after
   `set_communications`) to add node-policy hooks.

## Registration Contract

| Hook | When invoked | May mutate target? |
|------|----------------|---------------------|
| `before_dispatch` | After validation, before default handler | Read-only recommended |
| `wrap_dispatch` | Around default handler (if used) | Per implementation contract |
| `after_dispatch` | After default handler, before return | Read-only recommended |

- **FR-009**: Registrations from `cue_layer` are applied first; `node_layer`
  registrations for the same hook phase run after, unless superseded by last-wins rule.
- **FR-008**: Same hook + same filter + same phase: **last registration wins**;
  optional explicit `unregister(id)` in implementation.

### Callable signature

```python
def hook(ctx: ActionHookContext) -> None:
    ...
```

`ActionHookContext` fields (stable):

| Field | Type | Populated when |
|-------|------|---------------|
| `cue` | `ActionCue` | always |
| `target` | `Cue \| None` | always (None if missing target) |
| `mtc` | `MtcListener` | always |
| `action_type` | `str` | always |
| `target_id` | `str \| None` | always |
| `outcome` | `dict \| None` | `after_dispatch` only |
| `cue_handler` | `Any` | always (bound CueHandler instance) |

### `wrap_dispatch` replacement rule

```python
def wrap_hook(ctx: ActionHookContext, run_default: Callable[[], dict]) -> dict:
    ...
```

- The wrapper **must** call `run_default()` to invoke the default handler.
- Returning without calling `run_default()` skips the default handler entirely.
- Only one `wrap_dispatch` per (source, filter_key) is active (last-wins).
- Wraps are applied outer-to-inner: cue_layer wraps node_layer wraps default.

### Invocation order

- `before_dispatch`: cue_layer hooks first, then node_layer hooks.
- `after_dispatch`: cue_layer hooks first, then node_layer hooks. **Skipped** if the
  default handler raised an exception.

### Regression baseline

No intentional behavioral deviations from the original `CueHandler` action handlers.
Identical action semantics, idempotency, and logging behavior are preserved.

## Result delivery contract

- **Default**: Outcomes that must reach the controller use `NodeCommunications` methods
  that ultimately call `send_operation` on the hub (same thread/async rules as today).
- **Injectable sink**: `ActionHandler` MUST accept an object implementing
  `emit_action_result(outcome)` (or equivalent) that:
  - Uses `AsyncCommsThread.run_coroutine` if NNG I/O is required, **or**
  - Delegates to another `AsyncCommsThread` subclass that performs the send.
- **Tests**: MAY pass a fake sink that records outcomes without network.

## Safety

- Unknown action type / missing target: **rejected** before hooks that assume a target.
- Extension exception: log, map to `failed` or `rejected` per spec; do not corrupt
  unrelated armed cues.

## Performance

- Hook chains are linear; no unbounded recursion.
- Default path adds at most O(number of registrations) calls per action.
