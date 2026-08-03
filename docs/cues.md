# Cue Architecture

## ActionHandler (action_handler.py)

Owns all `ActionCue` processing — validation, dispatch, hooks, and result delivery.

- **Hook phases**: `before_dispatch`, `after_dispatch`, `wrap_dispatch`
- **Registration layers**: `cue_layer` (from CueHandler), `node_layer` (from NodeEngine)
- **Result sink**: injectable callable; defaults to NNG `NodeOperation.STATUS` via `NodeCommunications.send_operation`

See [action-handler-extensibility contract](../specs/003-action-handler-extract/contracts/action-handler-extensibility.md) for integration details.

::: cuemsengine.cues.ActionHandler
::: cuemsengine.cues.CueHandler
::: cuemsengine.cues.arm_cue
::: cuemsengine.cues.loop_cue
::: cuemsengine.cues.run_cue
