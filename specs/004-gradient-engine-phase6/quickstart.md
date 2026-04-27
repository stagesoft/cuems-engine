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
- In-memory `FadeDispatchRegistry` for tracking active fades and running the fade-down watchdog.
- `fade_complete` STATUS receiver that updates the Ossia cache and disarms the target cue.
- Pre-arm of fade-in targets at project load.
- `CANCEL_ALL` on project stop/load.

---

## Key files

| File | Change |
|------|--------|
| [src/cuemsengine/cues/FadeDispatchRegistry.py](../../../src/cuemsengine/cues/FadeDispatchRegistry.py) | **NEW** — dispatch record + watchdog |
| [src/cuemsengine/cues/ActionHandler.py](../../../src/cuemsengine/cues/ActionHandler.py) | `fade_action` in SUPPORTED_CUE_ACTIONS + `_handle_fade_action` |
| [src/cuemsengine/cues/CueHandler.py](../../../src/cuemsengine/cues/CueHandler.py) | Pre-arm FadeCue targets; inject registry; `on_fade_complete` |
| [src/cuemsengine/cues/run_cue.py](../../../src/cuemsengine/cues/run_cue.py) | `FadeCue` singledispatch branch |
| [src/cuemsengine/comms/NodeCommunications.py](../../../src/cuemsengine/comms/NodeCommunications.py) | `gradientengine` filter + STATUS callback + send helpers |
| [src/cuemsengine/osc/OssiaNodes.py](../../../src/cuemsengine/osc/OssiaNodes.py) | `set_cached_value()` quiet-update helper |
| [src/cuemsengine/ControllerEngine.py](../../../src/cuemsengine/ControllerEngine.py) | Sender guard in STATUS callback + CANCEL_ALL |

---

## Dependency

`FadeCue` and `FadeCurveType` are in `cuemsutils` (already a project dependency).
No new package dependencies required.

---

## Running the tests

```bash
# From repo root, with the dev venv active:
poetry run pytest tests/test_fade_dispatch_registry.py -v
poetry run pytest tests/test_fade_action_handler.py -v
poetry run pytest tests/test_node_communications_gradient.py -v
poetry run pytest tests/test_controller_engine_gradient.py -v
```

---

## Key invariants

1. **Never mutate target_cue if NNG dispatch fails.** The `_handle_fade_action` handler must
   arm and potentially start playback only after confirming the NNG send succeeded.
2. **Quiet cache update only.** After `fade_complete`, call
   `target_cue._osc.set_cached_value(osc_path, end_value)` — never `set_value()` (which would
   re-emit OSC to the player).
3. **CANCEL_ALL fires before players stop.** In both `stop_script` and `load_project`, the
   `_send_gradient_cancel_all()` call must precede the node-forward call.
4. **Hard-fail on NNG error.** If `send_fade_command` raises or returns an error, return
   `ActionHandler._action_result("failed", ...)` and do not call `ch.go(target_cue, mtc)`.
5. **Watchdog per fade-down only.** `is_fade_down` (`target_value == 0`) triggers the timer;
   fade-up completes when gradient-motiond naturally emits `fade_complete` (no extra timeout).

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
      8. ch.fade_registry.register(FadeDispatchRecord(...))
      9. ch.communications_thread.send_fade_command(payload)  → NNG → gradient-motiond
      10. Return ActionHandler._action_result("applied", "fade_action", ...)

gradient-motiond drives OSC /volmaster 0.0 → end_value over duration_ms ...

gradient-motiond sends fade_complete STATUS on NNG bus
  → NodeCommunications._handle_status_operation(operation)
      if target=="gradientengine" and event=="fade_complete":
        CUE_HANDLER.on_fade_complete(fade_id)
          1. record = registry.complete(fade_id)
          2. target_cue._osc.set_cached_value(osc_path, record.end_value)
          3. (no disarm for fade-up)
```

## Sequence diagram (fade-down)

```
Operator fires FadeCue (target_value=0)
  → ActionHandler._handle_fade_action(ch, fade_cue, mtc)
      1. Resolve target_cue (must be playing)
      2. Read start_value from Ossia cache
      3. end_value = 0.0
      4. Build FadeCommand
      5. registry.register(record with watchdog timer = duration+1s)
      6. send_fade_command → NNG

gradient-motiond drives OSC to 0 ...

fade_complete STATUS received:
  → CUE_HANDLER.on_fade_complete(fade_id)
      1. record = registry.complete(fade_id)  → cancels watchdog
      2. set_cached_value(osc_path, 0.0)
      3. ch.disarm(record.target_cue)

  OR watchdog expires:
  → registry._on_watchdog_timeout(fade_id)
      1. Logger.warning(...)
      2. ch.disarm(record.target_cue)
```
