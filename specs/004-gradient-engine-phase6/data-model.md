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
| `target_value` | `int` | `[0, 100]` | Destination level in UI units (0–100 scale) |

**State transitions**: FadeCue itself transitions through the general cue lifecycle:
`armed → playing (loop_fadeCue blocks for duration) → disarmed`. The target_cue's state
is NOT mutated by the FadeCue lifecycle; it remains armed throughout and any subsequent
disarm is the responsibility of player-stop or follow-up cues.

---

### FadeCommand (NNG wire payload — outbound)

JSON-serialisable dict sent inside `NodeOperation.data` with `target="gradientengine"`.

The payload is built in two layers:

1. **Body** built by `ActionHandler._build_payload(target_cue, fade_cue, start_time)`
   — fields derived from FadeCue + target_cue.
2. **Envelope** injected by `NodeCommunications.send_fade_command(payload)` —
   `command`, `fade_id`, `osc_host`, `curve_params`.

| Field | Source | Layer | Notes |
|-------|--------|-------|-------|
| `command` | Literal `"start_fade"` | envelope | Discriminator for gradient-motiond |
| `fade_id` | `str(FadeCue.uuid)` | envelope | Controller-assigned correlation key |
| `osc_host` | `"127.0.0.1"` | envelope | Always localhost |
| `osc_port` | `target_cue._osc.remote_port` (audio) or `7000` (video) | body | From target_cue |
| `osc_path` | `"/volmaster"` (audio) or `"/videocomposer/layer/{id}/opacity"` (video) | body | From target_cue |
| `start_value` | `target_cue._osc.get_value(osc_path)` | body | Float, current cached OSC value |
| `target_value` | `FadeCue.target_value` | body | Integer 0–100 (UI scale, NOT normalised) |
| `start_time` | `CTimecode.milliseconds_rounded` (int) | body | MTC clock at dispatch time |
| `duration_ms` | `FadeCue.duration.milliseconds_rounded` (int) | body | Must be > 0 |
| `curve_type` | `FadeCue.curve_type` (enum value, str) | body | `"linear"` / `"exponential"` / `"logarithmic"` / `"sigmoid"` |
| `curve_params` | `{}` | envelope | Reserved for future curve parameterisation |

**Validation rules**:
- `start_value` is the raw cached OSC value; clamping is the consumer's responsibility.
- `target_value ∈ [0, 100]` (enforced by FadeCue setter).
- `duration_ms > 0` (enforced by FadeCue.duration setter).
- `osc_path` must be non-empty.

---

### CANCEL_ALL Command (NNG wire payload — outbound)

| Field | Type | Value |
|-------|------|-------|
| `command` | `str` | `"cancel_all"` |

Sent as `NodeOperation(type=COMMAND, action=UPDATE, target="gradientengine", data={"command": "cancel_all"})`.

---

## Relationships

```
FadeCue ──── uuid ─────────────────► fade_id (envelope, set by send_fade_command)
FadeCue ──── action_target ────────► target_cue (AudioCue | VideoCue)
FadeCue ──── target_value ─────────► FadeCommand.target_value (raw 0–100, NOT normalised)
FadeCue ──── duration ─────────────► FadeCommand.duration_ms (int via .milliseconds_rounded)
FadeCue ──── duration ─────────────► loop_fadeCue _end_mtc (cue runner retention)
FadeCue ──── curve_type ───────────► FadeCommand.curve_type (enum value, str)

target_cue._osc.get_value(path) ──► FadeCommand.start_value
target_cue._osc.remote_port ──────► FadeCommand.osc_port (AudioCue)
target_cue._layer_ids[0] ─────────► FadeCommand.osc_path (VideoCue)

mtc.main_tc.milliseconds_rounded ─► FadeCommand.start_time (int)
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

## State Machine: FadeCue lifecycle

```
[not armed] ──arm (pre-arm at load, with target_cue)──► [armed/idle]
[armed/idle] ──FadeCue fires──► _handle_fade_action ──► dispatch FadeCommand via NNG ──► [running]
[running] ──loop_fadeCue blocks until _end_mtc──► [duration elapsed]
[duration elapsed] ──general cue lifecycle──► [disarmed (FadeCue only — target_cue untouched)]
```

The target_cue remains `loaded=True` throughout. Whether the target_cue is later disarmed
(e.g., after audio reaches end-of-file, or by a separate stop ActionCue) is independent
of the FadeCue lifecycle.
