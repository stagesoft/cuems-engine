# Developer Quickstart: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Branch**: `004-gradient-engine-phase6`
**Date**: 2026-04-27

---

## What this feature does

Wires `FadeCue` (already in `cuemsutils`) into the cuems-engine runtime so that firing a
`FadeCue` dispatches a `FadeCommand` over NNG to `gradient-motiond`, which then drives the
actual OSC value changes on the player. Covers:

- NNG routing filter so `gradient-motiond`-targeted commands pass through without being
  executed by the Python NodeEngine.
- `fade_action` handler in `ActionHandler` that builds and dispatches `FadeCommand`.
- `fade_complete` STATUS receiver that disarms the target cue (fade-down path).
- Pre-arm of fade-in targets at project load.
- `CANCEL_ALL` on project stop/load.

---

## Key files

| File | Change |
|------|--------|
| [src/cuemsengine/cues/ActionHandler.py](../../../src/cuemsengine/cues/ActionHandler.py) | `fade_action` in SUPPORTED_CUE_ACTIONS + `_handle_fade_action` |
| [src/cuemsengine/cues/CueHandler.py](../../../src/cuemsengine/cues/CueHandler.py) | Pre-arm FadeCue targets; `on_fade_complete` |
| [src/cuemsengine/cues/run_cue.py](../../../src/cuemsengine/cues/run_cue.py) | `FadeCue` singledispatch branch |
| [src/cuemsengine/comms/NodeCommunications.py](../../../src/cuemsengine/comms/NodeCommunications.py) | `gradientengine` filter + STATUS callback + send helpers |
| [src/cuemsengine/ControllerEngine.py](../../../src/cuemsengine/ControllerEngine.py) | Sender guard in STATUS callback + CANCEL_ALL |

---

## Dependency

`FadeCue` and `FadeCurveType` are in `cuemsutils` (already a project dependency).
No new package dependencies required.

---

## Running the tests

```bash
# From repo root, with the dev venv active:
poetry run pytest tests/test_fade_action_handler.py -v
poetry run pytest tests/test_node_communications_gradient.py -v
poetry run pytest tests/test_controller_engine_gradient.py -v
```

---

## Key invariants

1. **Never mutate target_cue if NNG dispatch fails.** The `_handle_fade_action` handler must
   arm and potentially start playback only after confirming the NNG send succeeded.
2. **CANCEL_ALL fires before players stop.** In both `stop_script` and `load_project`, the
   `_send_gradient_cancel_all()` call must precede the node-forward call.
3. **Hard-fail on NNG error.** If `send_fade_command` raises or returns an error, return
   `ActionHandler._action_result("failed", ...)` and do not call `ch.go(target_cue, mtc)`.

---

## Sequence diagram (fade-up)

```
Operator fires FadeCue
  → CueHandler.execute_action(fade_cue, mtc)
  → ActionHandler._handle_fade_action(ch, fade_cue, mtc)
      1. Resolve target_cue = fade_cue._action_target_object
      2. Arm target_cue (if not armed)
      3. Start target_cue playback at vol=0 (ch.go with _fade_initial_volume=0.0)
      4. Resolve osc_path, osc_port from target_cue
      5. Read start_value = target_cue._osc.get_value(osc_path)  → 0.0 (just started)
      6. Compute end_value = fade_cue.target_value / 100.0
      7. Build FadeCommand dict
      8. ch.communications_thread.send_fade_command(payload)  → NNG → gradient-motiond
      9. Return ActionHandler._action_result("applied", "fade_action", ...)

gradient-motiond drives OSC /volmaster 0.0 → end_value over duration_ms ...

gradient-motiond sends fade_complete STATUS on NNG bus
  → NodeCommunications._handle_status_operation(operation)
      if target=="gradientengine" and event=="fade_complete":
        CUE_HANDLER.on_fade_complete(fade_id)
          (fade-up: log receipt, no disarm)
```

## Sequence diagram (fade-down)

```
Operator fires FadeCue (target_value=0)
  → ActionHandler._handle_fade_action(ch, fade_cue, mtc)
      1. Resolve target_cue (must be playing)
      2. Read start_value from Ossia cache
      3. end_value = 0.0
      4. Build FadeCommand
      5. send_fade_command → NNG

gradient-motiond drives OSC to 0 ...

fade_complete STATUS received:
  → CUE_HANDLER.on_fade_complete(fade_id)
      1. ch.disarm(target_cue)
```
