# Phase 0 Research: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Date**: 2026-04-27
**Branch**: `004-gradient-engine-phase6`

---

## R-001: FadeCue implementation status in `cuemsutils`

**Decision**: `FadeCue` is already implemented and exported.

**Finding**:
- File: `/disk/Projects/StageLab/cuems-utils/src/cuemsutils/cues/FadeCue.py`
- Exported from `cuemsutils.cues.__init__` as `FadeCue`.
- Fields exactly match the spec: `curve_type` (`FadeCurveType` enum), `duration` (`CTimecode`),
  `target_value` (`int` 0–100), `action_type` locked to `"fade_action"`.
- `FadeCurveType` enum: `linear`, `exponential`, `logarithmic`, `sigmoid`.
- `duration` setter rejects zero/negative via `format_timecode(duration) <= _ZERO_TC`.
- `action_type` setter raises `ValueError` if mutated post-init.
- The engine (`cuems-engine`) does NOT currently import `FadeCue` anywhere.

**Implication**: No changes required to `cuemsutils`. Engine only needs to import and use it.

---

## R-002: `CTimecode` milliseconds conversion

**Decision**: Use `CTimecode.milliseconds` property directly.

**Finding**:
- `MtcListener` (`src/cuemsengine/tools/MtcListener.py` line 37): exposes a `.milliseconds`
  property that calls `self.main_tc.milliseconds`.
- `CTimecode` (from `cuemsutils.tools.CTimecode`) has a `.milliseconds` property confirmed by
  introspection of the installed package.
- At dispatch time: `start_mtc_ms = mtc.timecode.milliseconds` (integer ms from MTC listener).
- For `duration_ms`: `int(cue.duration.milliseconds)` where `cue.duration` is a `CTimecode`.

**Alternatives considered**: Converting via frame count × frame duration — rejected because
`milliseconds` is already available and avoids framerate coupling.

---

## R-003: `ActionHandler` registration pattern for `fade_action`

**Decision**: Add `"fade_action"` to `SUPPORTED_CUE_ACTIONS` frozenset and register
`_handle_fade_action` in `_ACTION_HANDLERS`.

**Finding**:
- `SUPPORTED_CUE_ACTIONS` (`ActionHandler.py` lines 21–30) is a `frozenset` defined at module
  level. Currently contains `"fade_in"` and `"fade_out"` (stubs).
- `_ACTION_HANDLERS` dict (`ActionHandler.py` lines 440+) maps `action_type → handler fn`.
- The `execute_action` method (`ActionHandler.py` line 197) dispatches via
  `handler = _ACTION_HANDLERS.get(action_type)` after validating against `SUPPORTED_CUE_ACTIONS`.
- `_handle_fade_action` signature must match the existing pattern:
  `(ch: Any, target: Cue, mtc: MtcListener) -> dict` — `ch` is the `CueHandler` instance.

**Note**: `"fade_in"` and `"fade_out"` entries remain for backward compatibility with
existing ActionCue XML scripts. Their stub handlers continue unchanged.

---

## R-004: `NodeCommunications` filter and STATUS registration

**Decision**: Modify `_handle_command_operation` for the early return; extend
`set_receive_callbacks` call in `__init__` to also register `OperationType.STATUS`.

**Finding** (`src/cuemsengine/comms/NodeCommunications.py`):
- `__init__` (line ~35–37): calls `self.nng_hub.set_receive_callbacks({OperationType.COMMAND: self._handle_command_operation})`.
- `_handle_command_operation` (line ~60+): first line accesses `operation.type`, then immediately
  sets `command_name = operation.target` — the `operation.target` field is available here and is
  the correct field to check for `"gradientengine"`.
- The early return `if operation.target == "gradientengine": return` must be added as the first
  check *after* the type guard (`if operation.type != OperationType.COMMAND: return`).
- `OperationType.STATUS` is already defined in `NodesHub.py` (line 21).
- The STATUS handler must be a new method `_handle_status_operation(self, operation: NodeOperation)`.
- `CUE_HANDLER` is accessible via the module-level singleton in `CueHandler.py`.

---

## R-006: `ControllerEngine` STATUS callback and sender guard

**Decision**: Guard in `status_operation_callback` using `operation.sender.startswith("gradientengine_")`.

**Finding** (`src/cuemsengine/ControllerEngine.py`):
- `status_operation_callback` (line ~371): dispatches on `operation.target` via `if/elif` chain.
  The `else` branch logs a debug warning. gradient-motiond STATUS messages have `target="gradientengine"`,
  which does not match any existing `elif`, so they currently hit the `else` debug log — harmless
  but generates noise.
- `operation.sender` will be `"gradientengine_<node_name>"` per the gradient-motion-engine spec
  FR-006 `sendStatus` schema.
- The guard `if operation.sender and operation.sender.startswith("gradientengine_"): return`
  is added at the top of `status_operation_callback` before the `if/elif` chain.
- Registered at `ControllerCommunications` level via `set_receive_callbacks({OperationType.STATUS: self.status_operation_callback})`.

---

## R-007: `CueHandler` pre-arm path

**Decision**: Extend the `ActionCue` pre-arm block at line 288 to include `fade_action` with `target_value > 0`.

**Finding** (`src/cuemsengine/cues/CueHandler.py`):
- Lines 283–290: `if isinstance(cue, ActionCue) and cue._action_target_object: if cue.action_type == 'play': self.arm(cue._action_target_object, init)`
- `FadeCue` is a subclass of `ActionCue`, so `isinstance(cue, ActionCue)` returns `True`.
- The condition can be extended to:
  ```python
  if isinstance(cue, ActionCue) and cue._action_target_object:
      should_prearm = cue.action_type == 'play' or (
          cue.action_type == 'fade_action' and
          getattr(cue, 'target_value', 0) > 0
      )
      if should_prearm:
          self.arm(cue._action_target_object, init)
  ```
- `getattr` with default guards against any non-FadeCue ActionCue that doesn't have `target_value`.

---

## R-008: `CANCEL_ALL` dispatch points in `ControllerEngine`

**Decision**: Add `_send_gradient_cancel_all()` private helper; call from `load_project` and `stop_script`.

**Finding** (`src/cuemsengine/ControllerEngine.py`):
- `load_project` (line ~650): calls `_forward_load_to_nodes(project_name)` after project
  state is set. `CANCEL_ALL` must fire BEFORE `_forward_load_to_nodes` (which triggers player
  startup on the node side) to guarantee stale fades are cancelled before new players start.
- `stop_script` (line ~806): calls `_forward_command_to_nodes('/engine/command/stop', value)`.
  `CANCEL_ALL` must fire BEFORE this call to ensure gradient-motiond stops OSC before players
  are stopped.
- `_send_gradient_cancel_all()` sends `NodeOperation(COMMAND, UPDATE, target="gradientengine", data={"command": "cancel_all"})` via `self.communications_thread.send_operation(...)`. `ControllerEngine` has a `communications_thread` attribute (confirmed in existing code at line 800+).

---

## R-009: `run_cue.py` FadeCue dispatch

**Decision**: Add `run_fadeCue` registered with `@run_cue.register(FadeCue)` that delegates to `run_actionCue`.

**Finding** (`src/cuemsengine/cues/run_cue.py`):
- Uses `@singledispatch` pattern from `functools`. `run_actionCue` is registered for `ActionCue`.
- Since `FadeCue` is a subclass of `ActionCue`, Python's `singledispatch` MRO resolution SHOULD
  already route `FadeCue` to `run_actionCue`. However, explicit registration is safer and required
  by the TDD principle (the test will verify this routing).
- Explicit registration: `@run_cue.register(FadeCue)` wrapping a call to `run_actionCue`.
- `FadeCue` import must be added to `run_cue.py` imports.

---

## R-011: NNG send helper location

**Decision**: Methods `send_fade_command` and `send_cancel_all` added to `NodeCommunications` directly (not a separate class).

**Rationale**: Two methods do not justify a new class (YAGNI / rule of three). The existing
`send_operation` method on `NodeCommunications` is the natural extension point. The new methods
are private implementation detail of the NNG transport layer, not a public protocol boundary.
