# Implementation Plan: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Branch**: `004-gradient-engine-phase6` | **Date**: 2026-04-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-gradient-engine-phase6/spec.md`

## Summary

Add Python-side support for `FadeCue` execution in `cuems-engine`: route NNG commands
destined for `gradient-motiond` transparently, dispatch `FadeCommand` payloads with
correct value/time mappings from `FadeCue` and the live Ossia cache of the target_cue,
pre-arm fade targets at load time, occupy the cue runner for the FadeCue's `duration`
via a `loop_fadeCue` block, and send `CANCEL_ALL` to gradient-motiond on project stop.
`FadeCue` (with `FadeCurveType`) is already implemented in `cuemsutils`; this plan wires
it into the cuems-engine runtime.

## Technical Context

**Language/Version**: Python 3.11 (managed via pyenv + Poetry)
**Primary Dependencies**:
- `cuemsutils` — `FadeCue`, `FadeCurveType`, `CTimecode` (with `.milliseconds_rounded`),
  `ActionCue`, `AudioCue`, `VideoCue`
- `pyossia` — Ossia node cache (`node.parameter.value` direct read for start_value)
- `nng` (via `NodesHub`/`NodeCommunications`) — NNG bus operations, `NodeOperation`,
  `OperationType`
- `cuemsutils.log` — `Logger`
**Testing**: `pytest` — test files under `tests/`, mirroring `src/cuemsengine/` module structure
**Target Platform**: Linux (Debian/Ubuntu, systemd service)
**Project Type**: Distributed engine (ControllerEngine + NodeEngine per node)
**Performance Goals**: `CANCEL_ALL` dispatched before any player stops; NNG dispatch
non-blocking (threaded)
**Constraints**: Must not mutate `target_cue` state if NNG dispatch fails

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Notes |
|-----------|-------|-------|
| Single Responsibility | PASS | `_build_payload` private to `ActionHandler` keeps payload construction in one place; `_handle_fade_action` orchestrates only. NNG send methods are thin wrappers on `NodeCommunications`. |
| Open/Closed | PASS | `ActionHandler` hook registry extended via `_ACTION_HANDLERS` dict; existing handlers untouched. `loop_cue` extended via `@singledispatch.register`. |
| Liskov Substitution | PASS | `FadeCue` extends `ActionCue` and is handled via the existing `execute_action` dispatch path without breaking it; the singledispatch MRO routes FadeCue to the existing `run_actionCue` branch. |
| Interface Segregation | PASS | No god-interface added; STATUS bus events handled in `NodeCommunications` callback chain. |
| Dependency Inversion | PASS | `_handle_fade_action` receives `communications_thread` via injection (existing `CueHandler` pattern). |
| TDD (NON-NEGOTIABLE) | REQUIRED | Every changed/new function MUST have a failing test written and confirmed before implementation. |
| Integration & Contract Testing | REQUIRED | NNG dispatch path tested with real `NodeOperation` round-trips (mock NNG in-process bus per existing test pattern). |
| Simplicity & YAGNI | PASS | No abstraction beyond the dispatch registry, the private payload builder, and a thin NNG send wrapper. No speculative extension; envelope-style fades explicitly deferred. |
| Observability | REQUIRED | Every dispatch and hard-fail MUST be logged with `fade_id` and `target_cue.id`. |

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
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
src/cuemsengine/
├── comms/
│   ├── NodeCommunications.py      ← MODIFY: gradientengine filter + send_fade_command envelope
│   ├── ControllerCommunications.py (unchanged)
│   └── NodesHub.py               (unchanged — COMMAND/STATUS reused)
├── cues/
│   ├── ActionHandler.py           ← MODIFY: add fade_action to SUPPORTED + implement handler + _build_payload helper
│   ├── CueHandler.py              ← MODIFY: pre-arm FadeCue targets (no on_fade_complete needed)
│   ├── loop_cue.py                ← MODIFY: add loop_fadeCue blocking until _end_mtc
│   └── run_cue.py                 (unchanged — FadeCue inherits run_actionCue via MRO)
├── ControllerEngine.py            ← MODIFY: STATUS sender guard + CANCEL_ALL on load/stop
└── NodeEngine.py                  (unchanged — filter is in NodeCommunications layer)

tests/
├── test_fade_action_handler.py     ← NEW
├── test_loop_fade_cue.py           ← NEW (loop_fadeCue blocks until _end_mtc)
├── test_node_communications_gradient.py  ← NEW (STATUS filter + gradientengine passthrough)
└── test_controller_engine_gradient.py    ← NEW (sender guard + CANCEL_ALL)
```

**Structure Decision**: Single-project layout (existing). All changes are modifications to
existing files plus three new test files.

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

**D-001 — `fade_action` is the single fade action_type**
`SUPPORTED_CUE_ACTIONS` gains `"fade_action"`. The existing `"fade_in"` / `"fade_out"`
entries and their stub handlers are retained for backward-compatibility with existing
ActionCue XML scripts. fade-up vs fade-down distinction is explicitly removed; one
`fade_action` handler covers all directions because the operation is symmetric (read
current value, dispatch fade to target_value).

**D-004 — Gradient-motiond dispatch lives on `NodeCommunications`**
Rather than a separate class file, gradient-motiond dispatch is two methods on
`NodeCommunications`: `send_fade_command(payload: dict)` and `send_cancel_all()`.
`send_fade_command` injects the four envelope fields (`command="start_fade"`, `fade_id`
[supplied by caller via payload], `osc_host="127.0.0.1"`, `curve_params={}`) on top of
the helper-built payload, then constructs `NodeOperation(COMMAND, UPDATE,
target="gradientengine", data=payload)` and calls `self.send_operation(...)`.

**D-006 — `NodeCommunications._handle_command_operation` early return**
At the top of `_handle_command_operation`, before extracting `command_name`, add:
```python
if operation.target == "gradientengine":
    return
```
This prevents `gradient-motiond`-targeted COMMAND messages from being dispatched to the
Python NodeEngine's command callback.

**D-007 — `ControllerEngine.status_operation_callback` sender guard**
At the top of `status_operation_callback`, add:
```python
if operation.sender and operation.sender.startswith("gradientengine_"):
    return
```
This silently discards gradient-motiond STATUS broadcasts that arrive on the Controller's
NNG bus listener in multi-node setups.

**D-008 — `CueHandler` pre-arm extended to `fade_action` targets**
The pre-arm block in `CueHandler.arm()` adds `fade_action` alongside `play`:
```python
if isinstance(cue, ActionCue) and cue._action_target_object:
    if cue.action_type in ('play', 'fade_action'):
        self.arm(cue._action_target_object, init)
```
No `target_value` qualifier — every fade pre-arms its target.

**D-009 — Payload helper lives on ActionHandler**
`ActionHandler._build_payload(target_cue, fade_cue, start_time)` is a static private
helper that returns the body of the FadeCommand (no envelope fields). Placement on
`ActionHandler` rather than `FadeCue` keeps `FadeCue` as a pure data class (cuemsutils
stays unchanged) and keeps OSC-endpoint resolution colocated with the handler that owns
the dispatch path.

**D-010 — CANCEL_ALL dispatch on load and stop**
`ControllerEngine.load_project` (before `_forward_load_to_nodes`) and `stop_script`
(before `_forward_command_to_nodes`) each call `self._send_gradient_cancel_all()`, a
private method that constructs and sends `NodeOperation(COMMAND, UPDATE,
target="gradientengine", data={"command": "cancel_all"})`. This must fire before players
are stopped to prevent stale OSC delivery.

**D-011 — `loop_fadeCue` occupies the cue runner for `duration`**
`loop_cue.py` registers `loop_fadeCue(cue: FadeCue, mtc: MtcListener)` that blocks
until `mtc.main_tc.milliseconds >= cue._end_mtc.milliseconds`, polling `_stop_requested`
every 20 ms. This keeps the FadeCue alive in the cue runner for `duration` so general
cue lifecycle (auto-disarm of the FadeCue itself via `go_threaded`'s end-of-cue path)
fires only after the gradient fade has elapsed. The handler must set `cue._start_mtc`
and `cue._end_mtc` from the dispatch-time MTC and FadeCue.duration so the loop has a
real end-mtc to wait on.
