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

**Decision**: Use `CTimecode.milliseconds_rounded` (returns `int`) directly — both for
`start_time` from MTC and for `duration_ms` from FadeCue.duration.

**Finding**:
- `CTimecode.milliseconds` is now deprecated (cuemsutils 0.1.0rc6+) in favour of
  `milliseconds_rounded` (int) and `milliseconds_exact` (float).
- `mtc.main_tc.milliseconds_rounded` and `cue.duration.milliseconds_rounded` both return
  `int` — directly JSON-serialisable, no extra conversion at the NNG marshalling layer.
- `MtcListener` exposes `.timecode` (the underlying `CTimecode`); call
  `.timecode.milliseconds_rounded` from inside the handler.

**Alternatives considered**: Converting via frame count × frame duration — rejected because
`milliseconds_rounded` is already available and avoids framerate coupling.

---

## R-003: `ActionHandler` registration pattern for `fade_action`

**Decision**: Add `"fade_action"` to `SUPPORTED_CUE_ACTIONS` frozenset and register
`_handle_fade_action` in `_ACTION_HANDLERS`.

**Finding**:
- `SUPPORTED_CUE_ACTIONS` is a `frozenset` defined at module level. Currently contains
  `"fade_in"` and `"fade_out"` (stubs) which remain for backward-compatibility.
- `_ACTION_HANDLERS` dict maps `action_type → handler fn`.
- The `execute_action` method dispatches via `handler = _ACTION_HANDLERS.get(action_type)`
  after validating against `SUPPORTED_CUE_ACTIONS`.
- `_handle_fade_action` signature must match the existing pattern:
  `(ch: Any, target: Cue, mtc: MtcListener) -> dict` — `ch` is the `CueHandler` instance.
  Note: for `fade_action`, the `target` argument received is the FadeCue itself (because
  `execute_action` passes `cue._action_target_object` to handlers, which for FadeCue is
  the actual target media cue — but the existing pattern in `_handle_fade_in/out` shows
  the handler receives the resolved target object). Re-verify in implementation: the
  helper resolves the target from `cue._action_target_object` if needed.

**Note**: `"fade_in"` and `"fade_out"` entries remain for backward compatibility with
existing ActionCue XML scripts. Their stub handlers continue unchanged.

---

## R-004: `NodeCommunications` filter and STATUS handling

**Decision**: Add early return in `_handle_command_operation` for `target == "gradientengine"`.

**Finding** (`src/cuemsengine/comms/NodeCommunications.py`):
- `_handle_command_operation` accesses `operation.type`, then sets
  `command_name = operation.target` — the `operation.target` field is checked first for
  `"gradientengine"` and discarded.
- gradient-motiond no longer notifies the Python engine of fade completion — the engine
  cannot do anything useful with the event (general cue lifecycle handles disarm of the
  FadeCue itself; target_cue is untouched). The STATUS callback registration is retained
  only as a defensive log-and-discard at the bus layer.

---

## R-006: `ControllerEngine` STATUS callback and sender guard

**Decision**: Guard in `status_operation_callback` using `operation.sender.startswith("gradientengine_")`.

**Finding** (`src/cuemsengine/ControllerEngine.py`):
- `status_operation_callback` dispatches on `operation.target` via `if/elif` chain.
- gradient-motiond STATUS messages have `sender="gradientengine_<node_name>"`. The guard
  `if operation.sender and operation.sender.startswith("gradientengine_"): return` is
  added at the top of `status_operation_callback` before the `if/elif` chain.

---

## R-007: `CueHandler` pre-arm path

**Decision**: Extend the `ActionCue` pre-arm block at line 286 to include `fade_action`
unconditionally (no `target_value` qualifier).

**Finding** (`src/cuemsengine/cues/CueHandler.py`):
- Existing block: `if isinstance(cue, ActionCue) and cue._action_target_object:
  if cue.action_type == 'play': self.arm(cue._action_target_object, init)`
- `FadeCue` is a subclass of `ActionCue`, so `isinstance(cue, ActionCue)` returns `True`.
- Extension:
  ```python
  if isinstance(cue, ActionCue) and cue._action_target_object:
      if cue.action_type in ('play', 'fade_action'):
          self.arm(cue._action_target_object, init)
  ```

---

## R-008: `CANCEL_ALL` dispatch points in `ControllerEngine`

**Decision**: Add `_send_gradient_cancel_all()` private helper; call from `load_project`
and `stop_script`.

**Finding** (`src/cuemsengine/ControllerEngine.py`):
- `load_project` calls `_forward_load_to_nodes(project_name)` after project state is set.
  `CANCEL_ALL` must fire BEFORE `_forward_load_to_nodes`.
- `stop_script` calls `_forward_command_to_nodes('/engine/command/stop', value)`.
  `CANCEL_ALL` must fire BEFORE this call.
- `_send_gradient_cancel_all()` sends `NodeOperation(COMMAND, UPDATE,
  target="gradientengine", data={"command": "cancel_all"})` via
  `self.communications_thread.send_operation(...)`.

---

## R-011: NNG send helper location

**Decision**: Methods `send_fade_command` and `send_cancel_all` added to
`NodeCommunications` directly (not a separate class).

**Rationale**: Two methods do not justify a new class (YAGNI / rule of three). The
existing `send_operation` method on `NodeCommunications` is the natural extension point.
`send_fade_command(payload, fade_id)` injects the four envelope fields (`command`,
`fade_id`, `osc_host`, `curve_params`) on top of the body returned by
`ActionHandler._build_payload`.

---

## R-012: `loop_fadeCue` retention block

**Decision**: Register `loop_fadeCue(cue: FadeCue, mtc: MtcListener)` in `loop_cue.py`
that blocks until `mtc.main_tc.milliseconds >= cue._end_mtc.milliseconds`, polling
`_stop_requested` every 20 ms. No looping (FadeCue.loop is not a concept).

**Finding** (`src/cuemsengine/cues/loop_cue.py`):
- Existing `loop_actionCue` is a no-op (`pass`) — appropriate for instant actions like
  play/stop/enable/disable that have zero duration. But FadeCue has a real `duration`,
  so it must NOT inherit the no-op via MRO; an explicit `loop_fadeCue` registration is
  required.
- `loop_audioCue` provides the polling pattern: `while mtc.main_tc.milliseconds <
  cue._end_mtc.milliseconds: if cue._stop_requested: return; sleep(0.02)`.
- `_handle_fade_action` is responsible for setting `cue._start_mtc` and `cue._end_mtc`
  on the FadeCue *before* the cue runner enters `loop_cue`. Since `loop_cue` is called
  from `go_threaded` *after* `run_cue`, and `run_cue` for a FadeCue routes through
  `run_actionCue` → `execute_action` → `_handle_fade_action`, the `_end_mtc` will be set
  by the time `loop_cue(cue, mtc)` is called.

---

## R-013: `run_cue` singledispatch — FadeCue inherits ActionCue branch

**Decision**: NO explicit `@run_cue.register(FadeCue)` branch. FadeCue inherits the
existing `run_actionCue` branch via Python's `singledispatch` MRO resolution because
`FadeCue` is a subclass of `ActionCue`.

**Rationale**: Constraint #1 — FadeCue MUST NOT have a branch in `run_cue` singledispatch.
Verification path: `singledispatch` walks MRO when no exact-type registration exists, so
`FadeCue → ActionCue → Cue` resolves to the `ActionCue` registration without code change.

---

## R-014: No `_fade_initial_volume` side-channel

**Decision**: `run_audioCue` is unchanged. The handler MUST NOT set
`target_cue._fade_initial_volume` and MUST NOT call `ch.go(target_cue, mtc)` to start
playback at vol=0. Envelope-style fade-from-silence is deferred to a future iteration.

**Rationale**: Constraint #2. The target_cue is expected to already be playing when its
FadeCue fires; the handler's job is to read the current OSC value via
`target_cue._osc.get_value(path)` and dispatch. No state mutation on target_cue beyond
arming (if not already armed via pre-arm path).
