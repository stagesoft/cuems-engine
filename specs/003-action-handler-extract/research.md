# Research: Dedicated Action Handler with Extensibility

## Decision 1: Extract action logic into `ActionHandler`

- **Decision**: Move `execute_action`, `SUPPORTED_CUE_ACTIONS`, `_handle_*`, and
  `_ACTION_HANDLERS` from `CueHandler` into a dedicated `ActionHandler` type (module
  `cuemsengine/cues/action_handler.py`), holding a reference to `CueHandler` (or a
  narrow protocol) for `arm`, `go`, and armed-cue queries.
- **Rationale**: Satisfies FR-001/FR-002 and User Story 3; keeps `CueHandler` focused on
  lifecycle and players.
- **Alternatives considered**:
  - Keep methods on `CueHandler` with nested class: rejected — does not improve boundary
    clarity.
  - Move to `NodeEngine`: rejected — violates cue-domain ownership and test isolation.

## Decision 2: Dual registration surfaces (`CueHandler` + `NodeEngine`)

- **Decision**: Expose registration API on `ActionHandler` (or a small `ActionExtensionRegistry`).
  Both `CueHandler` (after singleton init) and `NodeEngine` (e.g. during
  `set_communications`) call the same registry methods. **Merge order**: node-runtime
  registrations run after cue-handler registrations for the same hook phase (e.g.
  `after_default`), unless documented otherwise; duplicate hook + same phase uses FR-008
  rule (recommend: **last registration wins** per hook key, with optional `unregister`).
- **Rationale**: Integrators need node-level policy (NNG, scripting) and cue-level
  policy (player routing) without a single god object.
- **Alternatives considered**:
  - Only `CueHandler` registers: rejected — contradicts planning input and node-level
    integration needs.
  - Only `NodeEngine` registers: rejected — breaks locality for cue-only tests and
    helpers.

## Decision 3: Result delivery — `NodeCommunications` default, injectable sink

- **Decision**: `ActionHandler` accepts an optional **result sink** protocol:
  `emit_action_result(outcome: dict | ActionOutcome)` that defaults to calling
  `communications_thread.send_operation(...)` with a documented `NodeOperation` shape
  (new operation type or reuse CUE/STATUS pattern — to be finalized in implementation).
  Injecting a custom object is allowed if it implements the same contract (typically
  another `AsyncCommsThread` subclass exposing `run_coroutine` + send).
- **Rationale**: FR-010 and user requirement for NNG via `NodeCommunications` or
  compatible subclass; tests can inject a mock sink without NNG.
- **Alternatives considered**:
  - Hard-code only `NodeCommunications`: rejected — blocks tests and alternate transports.
  - Direct `NodesHub` in `ActionHandler`: rejected — duplicates thread/async rules already
    in `AsyncCommsThread`.

## Decision 4: Hook phases

- **Decision**: Support at minimum: `before_dispatch`, `after_dispatch` (with outcome),
  and optional `wrap_dispatch` (callable can run default and post-process). Whether
  `wrap_dispatch` can **skip** default is documented in contract (default: cannot skip
  unless explicitly returning a sentinel handled by registry).
- **Rationale**: Covers “redirect” language in original spec without undefined control flow.
- **Alternatives considered**:
  - Unlimited plugin chains: rejected — complexity and ordering bugs.

## Decision 5: Verification strategy

- **Decision**: Poetry `pytest`; extend `tests/test_action_cue.py` with registry and sink
  fakes; one test registering from a helper simulating `NodeEngine` path.
- **Rationale**: Constitution II; consistent with `002-action-cue-handler`.

## Decision 6: Wire-up

- **Decision**: `run_cue.run_actionCue` calls `ACTION_HANDLER.execute_action` (singleton
  or factory) instead of `CUE_HANDLER.execute_action`; `CueHandler` holds or imports the
  shared `ACTION_HANDLER` and passes `self` + `communications_thread` at init.
- **Rationale**: Minimal churn to `run_cue` singledispatch; clear entry point.
