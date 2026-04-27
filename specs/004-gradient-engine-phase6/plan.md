# Implementation Plan: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Branch**: `004-gradient-engine-phase6` | **Date**: 2026-04-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-gradient-engine-phase6/spec.md`

## Summary

Add Python-side support for `FadeCue` execution in `cuems-engine`: route NNG commands destined
for `gradient-motiond` transparently, dispatch `FadeCommand` payloads with correct value/time
mappings from `FadeCue` and the live Ossia cache of the target_cue, receive `fade_complete`
STATUS messages to trigger disarm, pre-arm fade-in targets at load time, and send `CANCEL_ALL`
to gradient-motiond on project stop.  `FadeCue` (with `FadeCurveType`) is already implemented
in `cuemsutils`; this plan wires it into the cuems-engine runtime.

## Technical Context

**Language/Version**: Python 3.11 (managed via pyenv + Poetry)
**Primary Dependencies**:
- `cuemsutils` — `FadeCue`, `FadeCurveType`, `CTimecode`, `ActionCue`, `AudioCue`, `VideoCue`
- `pyossia` — Ossia node cache (`node.parameter.value` direct-write for quiet cache update)
- `nng` (via `NodesHub`/`NodeCommunications`) — NNG bus operations, `NodeOperation`, `OperationType`
- `cuemsutils.log` — `Logger`
- `threading`, `time` — timeout management for fade-down watchdog
**Storage**: In-process registry (`dict[str, FadeDispatchRecord]`) keyed by `fade_id`
**Testing**: `pytest` — test files under `tests/`, mirroring `src/cuemsengine/` module structure
**Target Platform**: Linux (Debian/Ubuntu, systemd service)
**Project Type**: Distributed engine (ControllerEngine + NodeEngine per node)
**Performance Goals**: `CANCEL_ALL` dispatched before any player stops; `fade_complete` watchdog expires within `duration + 1 s` of dispatch; NNG dispatch non-blocking (threaded)
**Constraints**: Must not mutate `target_cue` state if NNG dispatch fails; OSC cache update must not re-emit OSC to the player

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Notes |
|-----------|-------|-------|
| Single Responsibility | PASS | New `FadeDispatchRegistry` owns only the dispatch record; `GradientEngineClient` owns only NNG send. ActionHandler handler fn stays narrow. |
| Open/Closed | PASS | `ActionHandler` hook registry extended via `_ACTION_HANDLERS` dict; existing handlers untouched. |
| Liskov Substitution | PASS | `FadeCue` extends `ActionCue` and is handled via the existing `execute_action` dispatch path without breaking it. |
| Interface Segregation | PASS | No god-interface added; STATUS callback registered separately from COMMAND callback in `NodeCommunications`. |
| Dependency Inversion | PASS | `_handle_fade_action` receives `communications_thread` via injection (existing `CueHandler` pattern). |
| TDD (NON-NEGOTIABLE) | REQUIRED | Every changed/new function MUST have a failing test written and confirmed before implementation. |
| Integration & Contract Testing | REQUIRED | NNG dispatch path tested with real `NodeOperation` round-trips (mock NNG in-process bus per existing test pattern). |
| Simplicity & YAGNI | PASS | No abstraction beyond the dispatch registry and a thin NNG send wrapper. No speculative extension. |
| Observability | REQUIRED | Every dispatch, fade_complete receipt, timeout expiry, and hard-fail MUST be logged with `fade_id` and `target_cue.id`. |

**Post-Phase-1 re-check**: All gates remain PASS after design (no new violations introduced).

## Project Structure

### Documentation (this feature)

```text
specs/004-gradient-engine-phase6/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── fade_command.json
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
src/cuemsengine/
├── comms/
│   ├── NodeCommunications.py      ← MODIFY: gradientengine filter + STATUS callback
│   ├── ControllerCommunications.py (unchanged)
│   └── NodesHub.py               (unchanged — COMMAND/STATUS reused)
├── cues/
│   ├── ActionHandler.py           ← MODIFY: add fade_action to SUPPORTED + implement handler
│   ├── CueHandler.py              ← MODIFY: pre-arm FadeCue targets; inject registry
│   ├── FadeDispatchRegistry.py    ← NEW: dispatch record + timeout watchdog
│   └── run_cue.py                 ← MODIFY: add FadeCue branch (mirrors ActionCue branch)
├── ControllerEngine.py            ← MODIFY: STATUS sender guard + CANCEL_ALL on load/stop
└── NodeEngine.py                  (unchanged — filter is in NodeCommunications layer)

tests/
├── test_fade_dispatch_registry.py  ← NEW
├── test_fade_action_handler.py     ← NEW
├── test_node_communications_gradient.py  ← NEW (STATUS filter + gradientengine passthrough)
└── test_controller_engine_gradient.py    ← NEW (sender guard + CANCEL_ALL)
```

**Structure Decision**: Single-project layout (existing). New `FadeDispatchRegistry` is a
separate module to respect SRP; all other changes are modifications to existing files.

## Complexity Tracking

> No constitution violations requiring justification.

---

## Phase 0: Research

*See [research.md](research.md) for full findings.*

All NEEDS CLARIFICATION items from the spec were resolved prior to planning (see spec
`## Clarifications` section). Phase 0 research focused on verifying concrete APIs,
integration points, and edge-case behaviours within the current codebase.

---

## Phase 1: Design

*See [data-model.md](data-model.md) for entity model and [contracts/](contracts/) for wire format.*

### Key Design Decisions

**D-001 — `fade_action` replaces `fade_in`/`fade_out` in `ActionHandler`**
`SUPPORTED_CUE_ACTIONS` gains `"fade_action"`. The existing `"fade_in"` / `"fade_out"` entries
and their stub handlers are retained for backward-compatibility during the transition (existing
XML scripts using those action types still parse; the new handler only fires for FadeCue
objects). Implementation adds `_handle_fade_action` registered under `"fade_action"`.

**D-002 — `FadeDispatchRegistry` as a standalone module**
`CueHandler` receives a `FadeDispatchRegistry` instance at startup (injected). The registry
stores `fade_id → FadeDispatchRecord` and owns the timeout watchdog thread per fade-down.
This isolates the record-keeping from both `CueHandler` (orchestration) and `ActionHandler`
(handler fns), satisfying SRP.

**D-003 — Ossia quiet-cache update via `node.parameter.value` direct assignment**
`OssiaNodes.set_value()` calls `push_value()` which re-emits OSC. After `fade_complete`, the
engine must update the target_cue's Ossia node cache *without* re-emitting. The safe path is
`target_cue._osc.nodes[osc_path].parameter.value = end_value` (direct Python attribute write
to the pyossia parameter — does not trigger the push/send path). A thin helper
`OssiaNodes.set_cached_value(path, value)` wraps this to avoid raw attribute access in
`FadeDispatchRegistry`.

**D-004 — `GradientEngineClient` thin wrapper in `NodeCommunications`**
Rather than a separate class file, gradient-motiond dispatch is added as two methods on
`NodeCommunications`: `send_fade_command(payload: dict)` and `send_cancel_all()`. Both
construct `NodeOperation(COMMAND, UPDATE, target="gradientengine", data=payload)` and call
`self.send_operation(...)`. This avoids an extra module for what is two small methods.

**D-005 — STATUS handler in `NodeCommunications` (not `NodeEngine`)**
`NodeCommunications.set_receive_callbacks` gains `OperationType.STATUS: self._handle_status_operation`.
The STATUS handler checks `operation.target == "gradientengine"` and `operation.data.get("event") == "fade_complete"`,
then calls `CUE_HANDLER.on_fade_complete(operation.data["fade_id"])`. `CueHandler.on_fade_complete`
looks up the dispatch record, updates the Ossia cache, and disarms the target_cue.

**D-006 — `NodeCommunications._handle_command_operation` early return**
At the top of `_handle_command_operation`, before extracting `command_name`, add:
```python
if operation.target == "gradientengine":
    return
```
This prevents `gradient-motiond`-targeted COMMAND messages from being dispatched to the Python
NodeEngine's command callback.

**D-007 — `ControllerEngine.status_operation_callback` sender guard**
At the top of `status_operation_callback`, add:
```python
if operation.sender and operation.sender.startswith("gradientengine_"):
    return
```
This silently discards gradient-motiond STATUS broadcasts that arrive on the Controller's NNG
bus listener in multi-node setups.

**D-008 — `CueHandler` pre-arm extended to `fade_action` targets with `target_value > 0`**
The pre-arm block in `CueHandler.arm()` (~line 288) adds `FadeCue` and checks `target_value > 0`:
```python
if isinstance(cue, ActionCue) and cue._action_target_object:
    if cue.action_type in ('play', 'fade_action') and (
        cue.action_type != 'fade_action' or cue.target_value > 0
    ):
        self.arm(cue._action_target_object, init)
```

**D-009 — `run_cue.py` adds `FadeCue` dispatch branch**
`run_cue.py` imports `FadeCue` and adds a `@singledispatch`-compatible branch (or a
`run_fadeCue` function registered with `@run_cue.register(FadeCue)`) that calls
`run_actionCue(cue, mtc)` — `FadeCue` is a subclass of `ActionCue`, so `execute_action`
handles the dispatch via `ActionHandler`.

**D-010 — CANCEL_ALL dispatch on load and stop**
`ControllerEngine.load_project` (before `_forward_load_to_nodes`) and `stop_script` (before
`_forward_command_to_nodes`) each call `self._send_gradient_cancel_all()`, a new private method
that constructs and sends `NodeOperation(COMMAND, UPDATE, target="gradientengine", data={"command": "cancel_all"})`.
This must fire before players are stopped to prevent stale OSC delivery.
