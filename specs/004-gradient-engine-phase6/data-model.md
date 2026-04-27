# Data Model: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Date**: 2026-04-27
**Branch**: `004-gradient-engine-phase6`

---

## Entities

### FadeCue (existing — `cuemsutils.cues.FadeCue`)

Extends `ActionCue`. Fully implemented in `cuemsutils`; no changes needed.

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `uuid` | `str` | Unique, set at construction | Used as `fade_id` in FadeCommand |
| `action_type` | `str` | Locked to `"fade_action"` | Mutation raises `ValueError` |
| `action_target` | `str` | Required | UUID of the target_cue |
| `_action_target_object` | `Cue \| None` | Set at arm time | Resolved to ActionCue's target object |
| `curve_type` | `FadeCurveType` | Default `linear` | Enum: `linear`, `exponential`, `logarithmic`, `sigmoid` |
| `duration` | `CTimecode \| None` | Positive non-zero; `None` only transient | Validated by setter |
| `target_value` | `int` | `[0, 100]` | Destination level in UI units |

**State transitions**: FadeCue itself does not transition state. It acts as a trigger; state
transitions affect the `target_cue` (arm → playing → disarmed after fade-down).

---

### FadeDispatchRecord (new — in-memory only, never persisted)

Stored in `FadeDispatchRegistry` keyed by `fade_id`. Exists for the lifetime of one active fade.

| Field | Type | Notes |
|-------|------|-------|
| `fade_id` | `str` | Equals `FadeCue.uuid` |
| `fade_cue` | `FadeCue` | The originating cue (for UUID logging) |
| `target_cue` | `Cue` | The AudioCue or VideoCue being faded |
| `osc_path` | `str` | Resolved OSC path (`/volmaster` or `/videocomposer/layer/N/opacity`) |
| `end_value` | `float` | `FadeCue.target_value / 100.0`, clamped `[0.0, 1.0]` |
| `is_fade_down` | `bool` | `True` if `target_value == 0` (watchdog armed for this) |
| `watchdog` | `threading.Timer \| None` | Active only when `is_fade_down` is `True` |

**Lifecycle**:
1. Created by `FadeDispatchRegistry.register()` at FadeCue dispatch time.
2. Cancelled by `FadeDispatchRegistry.complete(fade_id)` on `fade_complete` STATUS receipt.
3. Expired by `FadeDispatchRegistry._on_watchdog_timeout(fade_id)` if `fade_complete` is not
   received within `duration + 1 s`.
4. Removed from the registry in both cases (2) and (3).

**Concurrency**: Registry dict access is guarded by `threading.Lock`.

---

### FadeCommand (NNG wire payload — outbound)

JSON-serialisable dict sent inside `NodeOperation.data` with `target="gradientengine"`.
Shape defined by gradient-motion-engine spec FR-011.

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `command` | `str` | Literal `"start_fade"` | Discriminator for gradient-motiond |
| `fade_id` | `str` | `FadeCue.uuid` | Controller-assigned; arbitrary string |
| `osc_host` | `str` | `"127.0.0.1"` | Always localhost |
| `osc_port` | `int` | `target_cue._osc.remote_port` (audio) or `7000` (video) | From target_cue |
| `osc_path` | `str` | `"/volmaster"` or `"/videocomposer/layer/{id}/opacity"` | From target_cue |
| `start_value` | `float` | `target_cue._osc.get_value(osc_path)` or `0.0` | `[0.0, 1.0]` |
| `end_value` | `float` | `FadeCue.target_value / 100.0` | `[0.0, 1.0]` |
| `start_mtc_ms` | `int` | `mtc.timecode.milliseconds` at dispatch time | MTC clock |
| `duration_ms` | `int` | `int(FadeCue.duration.milliseconds)` | Must be > 0 |
| `curve_type` | `str` | `str(FadeCue.curve_type)` | `"linear"` / `"exponential"` / `"logarithmic"` / `"sigmoid"` |
| `curve_params` | `dict` | `{}` | Reserved; always empty dict for Phase 6 |

**Validation rules**:
- `end_value` and `start_value` clamped to `[0.0, 1.0]`.
- `duration_ms > 0` (enforced by FadeCue.duration setter, but verified at dispatch).
- `osc_path` must be non-empty.

---

### CANCEL_ALL Command (NNG wire payload — outbound)

| Field | Type | Value |
|-------|------|-------|
| `command` | `str` | `"cancel_all"` |

Sent as `NodeOperation(type=COMMAND, action=UPDATE, target="gradientengine", data={"command": "cancel_all"})`.

---

### fade_complete STATUS (NNG wire payload — inbound)

Received from gradient-motiond when a fade finishes. Shape from gradient-motion-engine FR-006.

| Field | Type | Notes |
|-------|------|-------|
| `type` | `str` | `"status"` |
| `action` | `str` | `"update"` |
| `sender` | `str` | `"gradientengine_<node_name>"` |
| `target` | `str` | `"gradientengine"` |
| `data.event` | `str` | `"fade_complete"` |
| `data.fade_id` | `str` | Matches `FadeCommand.fade_id` |
| `data.node_name` | `str` | Node identifier from gradient-motiond |

**Note**: `fade_complete` does NOT carry the final value. The Python engine recovers the
correct end value from `FadeDispatchRecord.end_value` (keyed by `fade_id`).

---

### FadeDispatchRegistry (new module — `src/cuemsengine/cues/FadeDispatchRegistry.py`)

Owns all in-flight `FadeDispatchRecord` instances. Injected into `CueHandler` at startup.

**Public interface**:

```python
class FadeDispatchRegistry:
    def register(self, record: FadeDispatchRecord) -> None: ...
    def complete(self, fade_id: str) -> FadeDispatchRecord | None: ...
    def cancel_all(self) -> None: ...  # called on CANCEL_ALL / project stop
    def _on_watchdog_timeout(self, fade_id: str) -> None: ...  # internal
```

**Thread safety**: All methods acquire `self._lock` (`threading.Lock`).

---

## Relationships

```
FadeCue ──── uuid ────────────────► fade_id (FadeCommand + FadeDispatchRecord key)
FadeCue ──── action_target ────────► target_cue (AudioCue | VideoCue)
FadeCue ──── target_value / 100 ──► FadeCommand.end_value
FadeCue ──── duration.milliseconds► FadeCommand.duration_ms
FadeCue ──── curve_type ──────────► FadeCommand.curve_type (str)

target_cue._osc.get_value(path) ──► FadeCommand.start_value
target_cue._osc.remote_port ──────► FadeCommand.osc_port (AudioCue)
target_cue._layer_ids[0] ─────────► FadeCommand.osc_path (VideoCue)

FadeDispatchRecord.end_value ─────► OssiaNodes quiet cache update on fade_complete
FadeDispatchRecord.watchdog ──────► threading.Timer (fade-down only)
FadeDispatchRecord.target_cue ────► CueHandler.disarm(target_cue) on complete/timeout
```

---

## OSC Path Resolution

| target_cue type | osc_host | osc_port | osc_path |
|-----------------|----------|----------|----------|
| `AudioCue` | `"127.0.0.1"` | `target_cue._osc.remote_port` | `"/volmaster"` |
| `VideoCue` | `"127.0.0.1"` | `7000` | `f"/videocomposer/layer/{target_cue._layer_ids[0]}/opacity"` |

Both `_osc.remote_port` (AudioCue) and `_layer_ids` (VideoCue) are set during arm; they
are available before `ActionHandler._handle_fade_action` dispatches the FadeCommand.

---

## State Machine: target_cue during fade-up (FadeCue.target_value > 0)

```
[not armed] ──arm (pre-arm at load)──► [armed/idle]
[armed/idle] ──FadeCue fires──► start playback at vol=0 ──► [playing, vol=0]
[playing, vol=0] ──FadeCommand dispatched──► [fading, gradient-motiond controls OSC]
[fading] ──fade_complete STATUS──► Ossia cache updated to end_value ──► [playing, vol=end_value]
```

## State Machine: target_cue during fade-down (FadeCue.target_value = 0)

```
[playing] ──FadeCue fires──► FadeCommand dispatched + watchdog started ──► [fading]
[fading] ──fade_complete STATUS (within duration+1s)──► cache updated, disarm ──► [disarmed]
[fading] ──watchdog expires (no fade_complete)──► warning logged, disarm ──► [disarmed]
```
