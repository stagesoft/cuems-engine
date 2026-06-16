# Tasks: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Input**: Design documents from `/specs/004-gradient-engine-phase6/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

---

## Phase 1: Foundational (Shared Infrastructure — blocks all stories)

**Purpose**: NNG routing filter and STATUS handler that every user story depends on.

> **TDD**: Write tests FIRST and confirm FAIL before implementing.

- [x] T005 Write failing tests for `NodeCommunications` gradient filter and STATUS registration in `tests/test_node_communications_gradient.py` — verify `gradientengine`-targeted COMMAND is swallowed; verify STATUS handler does not raise; verify `send_fade_command` injects envelope fields
- [x] T006 Implement `NodeCommunications` changes in `src/cuemsengine/comms/NodeCommunications.py`:
  - Early return in `_handle_command_operation` when `operation.target == "gradientengine"`
  - `OperationType.STATUS` callback registered (log-and-discard for gradientengine sender; no `on_fade_complete` needed)
  - `send_fade_command(payload, fade_id, timeout=None)` injects `command="start_fade"`, `fade_id`, `osc_host="127.0.0.1"`, `curve_params={}` envelope fields onto the body payload before sending
  - `send_cancel_all(timeout=None)` method

**Checkpoint**: Foundation ready — T005–T006 green ✅

---

## Phase 2: US3 — Gradient Engine Message Routing Isolation (Priority: P3)

**Goal**: NNG commands for gradient-motiond pass through; STATUS messages from gradient-motiond are silently discarded by ControllerEngine.

**Independent Test**: Send a synthetic `target="gradientengine"` NNG COMMAND; confirm NodeEngine does not execute it. Send a synthetic `sender="gradientengine_node1"` STATUS; confirm ControllerEngine does not log errors.

> **TDD**: Write tests FIRST.

- [x] T007 Write failing test for ControllerEngine sender guard in `tests/test_controller_engine_gradient.py` — STATUS with `sender="gradientengine_node1"` triggers no state change and no error log
- [x] T008 [P] [US3] Implement sender guard in `ControllerEngine.status_operation_callback` in `src/cuemsengine/ControllerEngine.py`:
  ```python
  if operation.sender and operation.sender.startswith("gradientengine_"):
      return
  ```

**Checkpoint**: US3 acceptance scenarios 1, 2 pass ✅

---

## Phase 3: US1 — Fade Action (Priority: P1) 🎯 MVP

**Goal**: Firing a FadeCue against a currently-playing target_cue dispatches a `FadeCommand` over NNG and the FadeCue occupies the cue runner for `duration`.

**Independent Test**: Unit-test `_handle_fade_action` with a mock `CueHandler` and stub `NodeCommunications`; verify FadeCommand body fields, `_end_mtc` set, `loop_fadeCue` blocks for duration. Verify target_cue is NOT disarmed and `_fade_initial_volume` is NOT set.

> **TDD**: Write tests FIRST.

- [x] T009 Write failing tests for `_handle_fade_action` in `tests/test_fade_action_handler.py`:
  - AudioCue target: correct osc_port, osc_path `/volmaster`, start_value from cache, target_value (raw 0–100), curve_type
  - VideoCue target: port 7000, osc_path pattern, start_value, target_value
  - NNG send failure → returns `"failed"` result, target_cue not mutated
  - target_cue must NOT be disarmed by handler (assert `ch.disarm.assert_not_called()`)
  - `_fade_initial_volume` must NOT be set on target_cue
  - `ch.go(target_cue, mtc)` must NOT be called (no envelope-from-silence)
  - `cue._start_mtc` and `cue._end_mtc` are set on the FadeCue itself for loop_fadeCue
- [x] T010 Write failing test in `tests/test_fade_action_handler.py` — verify `run_cue(FadeCue(...), mtc)` resolves to `run_actionCue` via singledispatch MRO (no explicit FadeCue branch); FadeCue is NOT registered in run_cue dispatch table
- [x] T012 [US1] Add `"fade_action"` to `SUPPORTED_CUE_ACTIONS` in `src/cuemsengine/cues/ActionHandler.py`
- [x] T013 [US1] Implement `_handle_fade_action` in `src/cuemsengine/cues/ActionHandler.py`:
  - Resolve `target_cue = cue._action_target_object`
  - Arm target_cue if not armed; return `"failed"` on arm failure
  - `start_time = mtc.timecode.milliseconds_rounded`
  - Build payload via `ActionHandler._build_payload(target_cue, cue, start_time)` (see T013b)
  - Set `cue._start_mtc` and `cue._end_mtc` on the FadeCue from start_time + duration so `loop_fadeCue` has a valid end-mtc
  - Call `ch.communications_thread.send_fade_command(payload, fade_id=str(cue.id))`; on error return `"failed"`, no target mutation
  - Return `ActionHandler._action_result("applied", "fade_action", target_id)`
  - MUST NOT: call `ch.disarm`, set `target_cue._fade_initial_volume`, call `ch.go(target_cue, mtc)`
- [x] T013b [US1] Implement `ActionHandler._build_payload(target_cue, fade_cue, start_time)` static helper in `src/cuemsengine/cues/ActionHandler.py`:
  - Resolve OSC port/path from target_cue type (AudioCue → `_osc.remote_port`, `/volmaster`; VideoCue → `7000`, `/videocomposer/layer/{_layer_ids[0]}/opacity`; else raise `ValueError`)
  - Read `start_value = target_cue._osc.get_value(osc_path)`
  - Return body dict: `{osc_port, osc_path, start_value, target_value=fade_cue.target_value, start_time, duration_ms=fade_cue.duration.milliseconds_rounded, curve_type=fade_cue.curve_type.value}`
- [x] T014 [US1] Register `_handle_fade_action` in `_ACTION_HANDLERS` dict in `src/cuemsengine/cues/ActionHandler.py`

**Checkpoint**: US1 acceptance scenarios 1–3 pass. Pre-arm (scenario 4) handled in Phase 5.

---

## Phase 4: US2 — Clean Project Load and Stop (Priority: P2)

**Goal**: CANCEL_ALL dispatched to gradient-motiond before players stop on load and stop.

**Independent Test**: Start a long fade, trigger project stop, verify no OSC messages after stop (via mock NNG send spy).

> **TDD**: Write tests FIRST.

- [x] T024 Write failing tests for `ControllerEngine` CANCEL_ALL in `tests/test_controller_engine_gradient.py`:
  - `stop_script`: `_send_gradient_cancel_all()` called before `_forward_command_to_nodes`
  - `load_project`: `_send_gradient_cancel_all()` called before `_forward_load_to_nodes`
  - No fades in progress: call still succeeds without error
- [x] T025 [US2] Implement `ControllerEngine._send_gradient_cancel_all()` in `src/cuemsengine/ControllerEngine.py`:
  ```python
  def _send_gradient_cancel_all(self):
      try:
          op = NodeOperation(type=OperationType.COMMAND, action=ActionType.UPDATE,
                             sender=..., target="gradientengine",
                             data={"command": "cancel_all"})
          self.communications_thread.send_operation(op, timeout=0.1)
      except Exception as e:
          Logger.warning(f"Failed to send CANCEL_ALL to gradient-motiond: {e}")
  ```
- [x] T026 [US2] Call `self._send_gradient_cancel_all()` at the correct point in `stop_script` (before `_forward_command_to_nodes`)
- [x] T027 [US2] Call `self._send_gradient_cancel_all()` at the correct point in `load_project` (before `_forward_load_to_nodes`)

**Checkpoint**: US2 acceptance scenarios 1–3 pass ✅

---

## Phase 5: US1 (continued) — Pre-arm at Load (Priority: P1 supplement)

**Goal**: FadeCue targets are pre-armed at project load (no `target_value` qualifier).

> **TDD**: Write test FIRST.

- [x] T028 Write failing test for CueHandler pre-arm extension in `tests/test_fade_action_handler.py` — FadeCue triggers `arm(target_cue, init)` at load regardless of target_value
- [ ] T029 [US1] Extend pre-arm block in `CueHandler.arm()` in `src/cuemsengine/cues/CueHandler.py`:
  ```python
  if isinstance(cue, ActionCue) and cue._action_target_object:
      if cue.action_type in ('play', 'fade_action'):
          self.arm(cue._action_target_object, init)
  ```

**Checkpoint**: US1 acceptance scenario 4 passes.

---

## Phase 6: `loop_fadeCue` retention block

**Goal**: A FadeCue occupies the cue runner for `duration` so general cue lifecycle disarms the FadeCue itself only after gradient-motiond's fade has elapsed.

> **TDD**: Write tests FIRST.

- [ ] T030 Write failing test in `tests/test_loop_fade_cue.py`:
  - `loop_fadeCue(cue, mtc)` blocks until `mtc.main_tc.milliseconds >= cue._end_mtc.milliseconds`
  - Returns early when `cue._stop_requested = True` set during the wait
  - FadeCue is registered in `loop_cue` singledispatch table (verify via direct dispatch)
- [ ] T031 Implement `loop_fadeCue(cue: FadeCue, mtc: MtcListener)` in `src/cuemsengine/cues/loop_cue.py`:
  - Block until `mtc.main_tc.milliseconds >= cue._end_mtc.milliseconds`
  - Poll `cue._stop_requested` every 20 ms; return early on stop
  - No looping (FadeCue.loop is not a concept)

---

## Phase 7: Polish & Integration

- [ ] T032 Run full test suite; confirm no regressions in existing tests: `poetry run pytest tests/ -v`
- [ ] T033 Validate `quickstart.md` sequence diagram matches implemented call paths
- [ ] T034 Review all new Logger calls: confirm each includes `fade_id` and `target_cue.id` per FR-013

---

## Dependencies & Execution Order

```
Phase 1 (T005–T006) → BLOCKS all phases
Phase 2 (T007–T008) → can start after Phase 1
Phase 3 (T009–T014) → can start after Phase 1; MVP deliverable
Phase 4 (T024–T027) → can start after Phase 1 (independent of Phase 3)
Phase 5 (T028–T029) → depends on Phase 3 CueHandler changes
Phase 6 (T030–T031) → depends on Phase 3 (T013 sets cue._end_mtc)
Phase 7 (T032–T034) → after all phases
```

**TDD order within each phase**: Write test → confirm FAIL → implement → confirm PASS → next.

---

## Removed tasks (no longer applicable)

- old T011, old T015 (FadeCue singledispatch branch in `run_cue.py`) — constraint #1: FadeCue inherits ActionCue via MRO; no branch needed.
- old T016 (`CueHandler.on_fade_complete`) — constraint #4: fade_action must not disarm target_cue; no follow-up Python state change required on `fade_complete`.
- old T017, old T018 (`_fade_initial_volume` side-channel in `run_audioCue`) — constraint #2: envelope-style fades deferred.
- old T019, old T020 (fade-down test class + on_fade_complete disarm tests) — constraint #3: fade-up/down distinction stripped.
- old T021, old T022, old T023 (fade-down extension to `_handle_fade_action`) — constraint #3.
