# Developer Quickstart: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Branch**: `004-gradient-engine-phase6`
**Date**: 2026-04-27

---

## What this feature does

Wires `FadeCue` (already in `cuemsutils`) into the cuems-engine runtime so that firing a
`FadeCue` dispatches a `FadeCommand` over NNG to `gradient-motiond`, which then drives
the actual OSC value changes on the player. Covers:

- NNG routing filter so `gradient-motiond`-targeted commands pass through without being
  executed by the Python NodeEngine.
- `fade_action` handler in `ActionHandler` that builds (via `_build_payload`) and
  dispatches `FadeCommand`.
- `loop_fadeCue` block that occupies the cue runner for the FadeCue's `duration`.
- Pre-arm of fade targets at project load.
- `CANCEL_ALL` on project stop/load.

Out of scope for Phase 6 (deferred to a future iteration):

- Envelope-style "fade from silence" semantics (`_fade_initial_volume` side-channel).
- Disarming `target_cue` on fade completion (general cue lifecycle handles disarms).

---

## Key files

| File | Change |
|------|--------|
| [src/cuemsengine/cues/ActionHandler.py](../../../src/cuemsengine/cues/ActionHandler.py) | `fade_action` in SUPPORTED_CUE_ACTIONS + `_handle_fade_action` + `_build_payload` private helper |
| [src/cuemsengine/cues/CueHandler.py](../../../src/cuemsengine/cues/CueHandler.py) | Pre-arm FadeCue targets |
| [src/cuemsengine/cues/loop_cue.py](../../../src/cuemsengine/cues/loop_cue.py) | `loop_fadeCue` blocking until `_end_mtc` |
| [src/cuemsengine/comms/NodeCommunications.py](../../../src/cuemsengine/comms/NodeCommunications.py) | `gradientengine` filter + `send_fade_command` envelope + `send_cancel_all` |
| [src/cuemsengine/ControllerEngine.py](../../../src/cuemsengine/ControllerEngine.py) | Sender guard in STATUS callback + CANCEL_ALL |

---

## Dependency

`FadeCue` and `FadeCurveType` are in `cuemsutils` (already a project dependency).
`CTimecode.milliseconds_rounded` (returning `int`) is required and present.
No new package dependencies required.

---

## Running the tests

```bash
# From repo root, with the dev venv active:
poetry run pytest tests/test_fade_action_handler.py -v
poetry run pytest tests/test_loop_fade_cue.py -v
poetry run pytest tests/test_node_communications_gradient.py -v
poetry run pytest tests/test_controller_engine_gradient.py -v
```

---

## Key invariants

1. **Never mutate target_cue if NNG dispatch fails.** The `_handle_fade_action` handler
   must arm the target only before payload construction; the dispatch call itself is the
   commit point. If `send_fade_command` raises, return `failed` and leave nothing else
   touched.
2. **CANCEL_ALL fires before players stop.** In both `stop_script` and `load_project`,
   the `_send_gradient_cancel_all()` call must precede the node-forward call.
3. **Hard-fail on NNG error.** If `send_fade_command` raises, return
   `ActionHandler._action_result("failed", ...)` and do not start the loop.
4. **fade_action MUST NOT disarm target_cue.** General cue lifecycle handles disarms.
5. **No `_fade_initial_volume` side-channel.** `run_audioCue` is unchanged.
6. **No `run_cue` singledispatch branch for FadeCue.** It inherits the `ActionCue`
   branch via Python's MRO/singledispatch.

---

## Sequence diagram

```
Operator fires FadeCue
  → CueHandler.go(fade_cue, mtc) → go_threaded(fade_cue, mtc, ...)
  → run_cue(fade_cue, mtc) → run_actionCue (via singledispatch MRO)
  → ActionHandler.execute_action(fade_cue, mtc)
  → _handle_fade_action(ch, fade_cue, mtc)
      1. Resolve target_cue = fade_cue._action_target_object
      2. Arm target_cue if not armed (general cue logic)
      3. start_time = mtc.timecode.milliseconds_rounded
      4. payload = ActionHandler._build_payload(target_cue, fade_cue, start_time)
         (returns body: osc_port, osc_path, start_value [from cache], target_value,
          duration_ms, start_time, curve_type)
      5. fade_cue._start_mtc / _end_mtc set from start_time + duration
         (so loop_fadeCue has a valid _end_mtc)
      6. ch.communications_thread.send_fade_command(payload, fade_id=fade_cue.id)
         (envelope adds: command="start_fade", fade_id, osc_host, curve_params)
      7. Return ActionHandler._action_result("applied", "fade_action", target_id)
  → loop_cue(fade_cue, mtc) → loop_fadeCue blocks until _end_mtc
  → go_threaded end-of-cue path → ch.disarm(fade_cue)  (FadeCue only)

gradient-motiond drives OSC over `duration_ms` independently.
target_cue remains armed; its disarm is the responsibility of subsequent cues.
```
