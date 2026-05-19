# C++ Node-Level GradientEngine — Implementation Plan

## Context

CUEMS needs fade support for ActionCues (fade_in/fade_out). Currently these are stubs that alias to play/stop. The gradient engine must generate smooth parametric curves (sigmoid, bezier, etc.) synchronized to MTC timecode, sending interpolated values via UDP OSC to AudioMixer (volume) and VideoComposer (opacity). After evaluating controller-side, node-side, and player-side approaches, we chose **node-side** for: localhost zero-jitter OSC, fault isolation per node, no player modifications, and natural fit with the existing Controller→Node architecture.

The engine is designed as a general-purpose timecode-driven signal evaluation system (`GradientEngine`). Fade-in/fade-out is the first signal output type, implemented as a sub-component (`FadeRegistry`, `FadeCommand`, `ActiveFade`). The architecture supports future signal output types (e.g., LFOs, envelopes, DMX sequences) without restructuring the core engine.

**Key architectural decisions:**
- Standalone C++ process per node (like VideoComposer), not embedded in NodeEngine
- Joins NNG bus directly as a dialer — receives commands from Controller/NodeEngine
- MTC quarter-frame-driven tick loop (not free-running timer) — evaluations track transport
- Audio fades target AudioPlayer `/volmaster` directly (mixer is reserved for UI volume control)
- Video fades target VideoComposer `/layer/N/opacity` — separate from NodeEngine's `/visible`, `/offset`, `/mtcfollow`
- DMX keeps existing player-side fade mechanism unchanged
- Core library (`libgradient_motion`) with `gme::*` namespace modules, separate from daemon code
- `GradientEngine` is the top-level orchestrator; `Fade*` classes are sub-elements for the fade signal output use case

## Repository: `../gradient-motion-engine/`

Actual development status of `gradient-motion-engine` resides on the parent folder of this repository. It also follows a SDD using `spec-kit` and all development can be traced inside `specs/` folder.

The source layout follows the README architecture: `libgradient_motion` (the reusable library) organized by `gme::*` namespace modules, and `gradient-motiond` (the daemon) in a separate directory tree.

```
gradient-motion-engine/
├── CMakeLists.txt
├── src/                                    ← libgradient_motion (static library)
│   ├── CMakeLists.txt                      ← collects all module sources
│   ├── gradient/                           ← gme::gradient — keyframes and interpolation
│   │   ├── Curve.h                         ← abstract base
│   │   ├── LinearCurve.h
│   │   ├── SigmoidCurve.h / .cpp           ← parametric: steepness, midpoint
│   │   ├── EaseInCurve.h                   ← power curve: t^exp
│   │   ├── EaseOutCurve.h                  ← 1-(1-t)^exp
│   │   ├── SCurve.h                        ← smoothstep: 3t^2-2t^3
│   │   ├── BezierCurve.h / .cpp            ← cubic bezier, 2 control points
│   │   ├── ScaledCurve.h                   ← decorator: remap input/output ranges
│   │   ├── ResampledCurve.h / .cpp         ← LUT pre-compute + interpolation
│   │   ├── CrossfadePair.h                 ← generates complementary paired values
│   │   └── CurveFactory.h / .cpp           ← string→Curve from JSON params
│   ├── time/                               ← gme::time — timecode, clocks, scheduling
│   │   └── MtcTickSource.h / .cpp          ← wraps MtcReceiver, quarter-frame callback
│   ├── signal/                             ← gme::signal — evaluated value representation
│   │   ├── FadeCommand.h                   ← command data struct
│   │   └── LockFreeQueue.h                 ← SPSC ring buffer (NNG→tick thread)
│   ├── engine/                             ← gme::engine — orchestration and execution pipeline
│   │   ├── ActiveFade.h                    ← one running fade instance
│   │   ├── FadeRegistry.h / .cpp           ← active fade map + tick evaluation
│   │   └── GradientEngine.h / .cpp          ← wires subsystems, owns tick loop
│   ├── osc/                                ← gme::osc — OSC encoding and transport
│   │   └── OscSender.h / .cpp              ← liblo UDP OSC wrapper
│   └── motion/                             ← gme::motion — trajectories (future)
│       └── (reserved for future use)
├── daemon/                                 ← gradient-motiond (executable)
│   ├── main.cpp
│   ├── GradientEngineApplication.h / .cpp
│   ├── config/
│   │   └── ConfigurationManager.h / .cpp
│   └── comms/
│       └── NngBusClient.h / .cpp           ← NNG dialer, JSON parse, command queue
├── cuemslogger/                            ← git submodule → github.com/stagesoft/cuemslogger
│   ├── cuemslogger.h / .cpp
│   └── CMakeLists.txt
├── mtcreceiver/                            ← git submodule → github.com/stagesoft/mtcreceiver
│   ├── mtcreceiver.h / .cpp                ←   pinned to commit 63ce3de (RtMidi 5.x fix)
│   └── CMakeLists.txt
├── tests/
│   ├── test_curves.cpp
│   ├── test_fade_registry.cpp
│   └── test_nng_parse.cpp
├── systemd/
│   └── gradient-motiond.service
└── debian/
    └── (packaging files)
```

**Key structural rules:**
- `src/` contains ONLY `libgradient_motion` code — no daemon logic, no systemd, no CLI
- `daemon/` contains ONLY `gradient-motiond` code — links the library but library has no daemon dependencies
- `cuemslogger/` and `mtcreceiver/` are git submodules at repo root (peer siblings for include path compatibility)
- NNG bus client lives in `daemon/comms/` because it is daemon-specific (the library is protocol-agnostic per README design goals)

### Build Dependencies
- C++17, CMake
- `libnng-dev` — NNG C library (nanomsg-next-gen)
- `nlohmann-json3-dev` — JSON parsing (header-only)
- `libtinyxml2-dev` — XML config parsing (`/etc/cuems/settings.xml`)
- `liblo-dev` — OSC sending
- `librtmidi-dev` >= 5.0 — MIDI/MTC reception (RtMidi 5.x compatibility fixed upstream in stagesoft/mtcreceiver#2)
- `libasound2-dev` — ALSA (for MIDI)

---


# Integration into `cuems-engine`
Specific adaptation that should be conducted in the present repository is part of the global implementation plan, and must adhere to the following development phase.


## Phase 6: Python-Side Changes — PREREQUISITE: 6b-NodeEngine filter must deploy BEFORE gradient-motiond runs

### 6b: cuems-engine (DEPLOY ORDER: NodeEngine filter FIRST)

**Modify** [NodeCommunications.py](../cuems-engine/src/cuemsengine/comms/NodeCommunications.py) — **PREREQUISITE, deploy before gradient-motiond**:
- In `_handle_command_operation` (line 60): add early return `if operation.target == "gradientengine": return` at line 73, before `command_name = operation.target`. This is the correct layer — the full `NodeOperation` with the `target` field is available here, unlike in `NodeEngine._handle_nng_command` which only receives `(command_name, value, address)`. The filter is on the uniform target `"gradientengine"` regardless of which fade sub-command the message carries inside `data`.
- Also add `OperationType.STATUS` handler to `set_receive_callbacks` (line 35-37) for receiving `data.event: "fade_complete"` status messages from gradient-motiond (envelope target is `"gradientengine"`; the handler inspects `data.event`).

**Modify** [ControllerEngine.py](../cuems-engine/src/cuemsengine/ControllerEngine.py):
- In STATUS handler: ignore/skip status messages from gradient-motiond (`sender.startswith("gradientengine_")`) to prevent confusion in multi-node setups where Bus0 broadcasts to all peers

**Modify** [ActionHandler.py](../cuems-engine/src/cuemsengine/cues/ActionHandler.py) `_handle_fade_in` (line 402):
1. Arm target (existing)
2. Set `target._fade_initial_volume = 0.0` on the cue object (side-channel for run_cue)
3. Go target — `ch.go(target, mtc)` launches `go_threaded` in background thread
4. Resolve target's OSC endpoint (after arm, before go returns):
   - **AudioCue** → AudioPlayer's OSC port + `/volmaster`. Port is at `target._osc.remote_port` (set during arm by `PlayerHandler.new_audio_output()` → `PlayerClient(remote_port=port)`).
   - **VideoCue** → port 7000 + `/videocomposer/layer/{layer_id}/opacity`. Layer ID in `target._layer_ids` after arm.
5. Send NNG `NodeOperation(COMMAND, UPDATE, target="gradientengine", data={command: "start_fade", ...})` via `CUE_HANDLER.communications_thread` — the fade sub-kind lives in `data.command`, not on the envelope's `target`
6. **Unit conversion:** `start_value=0.0, end_value=float(target.master_vol) / 100.0` (UI uses 0-100%, OSC expects 0.0-1.0 — see run_cue.py line 140)

**Volume conflict with run_cue:** `run_audioCue` (run_cue.py line 134-150) sets `/volmaster` once at cue start. Use a **side-channel on the cue object** to override:
- ActionHandler sets `target._fade_initial_volume = 0.0` before calling `ch.go()`
- Modify `run_audioCue` to check `getattr(cue, '_fade_initial_volume', None)` — if set, use that value instead of `cue.master_vol / 100.0` for the initial `/volmaster` write, then delete the attribute
- This avoids changing the `@singledispatch` signature or `go_threaded` parameters
- **Race condition:** `go_threaded` runs `run_audioCue` in a background thread. ActionHandler sends NNG to gradient-motiond after `ch.go()` returns. Since `run_audioCue` sets vol=0 first and gradient-motiond starts on the next MTC quarter frame (up to 5ms later), the initial vol=0 is set before the first tick. Acceptable ordering.

**Modify** `_handle_fade_out` (line 417):
1. Resolve start_value: `float(target.master_vol) / 100.0` — the cue's configured volume as 0.0-1.0 gain. This matches what `run_audioCue` initially set. (If a previous fade changed the volume, track the last-known value on the cue: `getattr(target, '_current_volume', float(target.master_vol) / 100.0)`)
2. Resolve port: same as fade_in — `target._osc.remote_port`
3. Send NNG start_fade with `start_value=current_vol, end_value=0.0`
4. On `fade_complete` NNG status from gradient-motiond → trigger disarm. **Implementation:** Add `OperationType.STATUS` to `NodeCommunications.set_receive_callbacks()` (currently only registers COMMAND — line 35-37). The new STATUS handler checks `operation.target == "gradientengine"` AND `operation.data.get("event") == "fade_complete"` (the envelope target is always `"gradientengine"`; the fade-specific discriminator is `data.event`), then calls `CUE_HANDLER.disarm(cue_by_fade_id)`. The `fade_id` carried in `data.fade_id` maps back to the target cue.

**Modify** [CueHandler.py](../cuems-engine/src/cuemsengine/cues/CueHandler.py) pre-arm path (~line 267):
- Add `fade_in` to the pre-arm condition alongside `play`. Currently only `action_type == 'play'` triggers pre-arm of the ActionCue's target at script load. Since `fade_in` also starts playback (from silence), the target should be pre-armed to avoid arm-at-go-time delay:
  ```python
  if isinstance(cue, ActionCue) and cue._action_target_object:
      if cue.action_type in ('play', 'fade_in'):
          self.arm(cue._action_target_object, init)
  ```

**Modify** project load/stop flow:
- In `ControllerEngine.load_project()` and `ControllerEngine.stop_script()`: send `CANCEL_ALL` to gradient-motiond via NNG before killing players. This prevents stale fades from sending OSC to dead player ports.

**Modify** [NodesHub.py](../cuems-engine/src/cuemsengine/comms/NodesHub.py):
- No new OperationType needed — reuse `COMMAND` with `target="gradientengine"` (uniform for all inbound messages destined to gradient-motiond). The fade-specific sub-kind is inside `data.command`; GradientEngine filters on the target field first, then dispatches on `data.command`.

---
