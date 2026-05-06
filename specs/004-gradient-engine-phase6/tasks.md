# Tasks: Gradient Motion Engine — Python-Side Integration (Phase 6)

**Input**: Design documents from `/specs/004-gradient-engine-phase6/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

---

## Phase 1: Foundational (Shared Infrastructure — blocks all stories)

**Purpose**: NNG routing filter and STATUS handler that every user story depends on.

> **TDD**: Write tests FIRST and confirm FAIL before implementing.

- [x] T005 Write failing tests for `NodeCommunications` gradient filter and STATUS registration in `tests/test_node_communications_gradient.py` — verify `gradientengine`-targeted COMMAND is swallowed; verify STATUS with `event="fade_complete"` calls `CUE_HANDLER.on_fade_complete`
- [x] T006 Implement `NodeCommunications` changes in `src/cuemsengine/comms/NodeCommunications.py`:
  - Early return in `_handle_command_operation` when `operation.target == "gradientengine"`
  - Add `OperationType.STATUS: self._handle_status_operation` to `set_receive_callbacks` dict
  - New `_handle_status_operation(self, operation: NodeOperation)` that calls `CUE_HANDLER.on_fade_complete(fade_id)` for `event=="fade_complete"` on `target=="gradientengine"`
  - New `send_fade_command(self, payload: dict)` method
  - New `send_cancel_all(self)` method

**Checkpoint**: Foundation ready — T005–T006 green ✅

---

## Phase 2: US4 — Gradient Engine Message Routing Isolation (Priority: P4)

**Goal**: NNG commands for gradient-motiond pass through; STATUS messages from gradient-motiond are silently discarded by ControllerEngine.

**Independent Test**: Send a synthetic `target="gradientengine"` NNG COMMAND; confirm NodeEngine does not execute it. Send a synthetic `sender="gradientengine_node1"` STATUS; confirm ControllerEngine does not log errors.

> **TDD**: Write tests FIRST.

- [x] T007 Write failing test for ControllerEngine sender guard in `tests/test_controller_engine_gradient.py` — STATUS with `sender="gradientengine_node1"` triggers no state change and no error log
- [x] T008 [P] [US4] Implement sender guard in `ControllerEngine.status_operation_callback` in `src/cuemsengine/ControllerEngine.py`:
  ```python
  if operation.sender and operation.sender.startswith("gradientengine_"):
      return
  ```

**Checkpoint**: US4 acceptance scenarios 1, 3 pass ✅

---

## Phase 3: US1 — Fade-Up FadeCue (Priority: P1) 🎯 MVP

**Goal**: Firing a FadeCue with `target_value > 0` starts playback at 0 and dispatches `FadeCommand`.

**Independent Test**: Unit-test `_handle_fade_action` with a mock `CueHandler` and stub `NodeCommunications`; verify FadeCommand payload fields, start_value=0.0, end_value=target_value/100, MTC ms, curve_type string.

> **TDD**: Write tests FIRST.

- [x] T009 Write failing tests for `_handle_fade_action` (fade-up path) in `tests/test_fade_action_handler.py`:
  - AudioCue target: correct osc_port, osc_path `/volmaster`, start_value=0.0, end_value from target_value, curve_type lowercase string
  - VideoCue target: port 7000, osc_path pattern, start_value, end_value
  - NNG send failure → returns `"failed"` result, target_cue not mutated
  - Arm failure → FadeCommand NOT dispatched
- [x] T010 Write failing test for `run_cue.py` FadeCue singledispatch branch in `tests/test_fade_action_handler.py` — `run_cue(FadeCue(...), mtc)` resolves to `run_actionCue`
- [x] T012 [US1] Add `"fade_action"` to `SUPPORTED_CUE_ACTIONS` in `src/cuemsengine/cues/ActionHandler.py`
- [x] T013 [US1] Implement `_handle_fade_action` in `src/cuemsengine/cues/ActionHandler.py` (fade-up path):
  - Resolve `target_cue = cue._action_target_object`
  - Arm target_cue if not armed; return `"failed"` on arm failure
  - Set `target_cue._fade_initial_volume = 0.0`; call `ch.go(target_cue, mtc)`
  - Resolve osc_path/osc_port from target_cue type
  - Read `start_value = target_cue._osc.get_value(osc_path)` (0.0 from initial set)
  - Compute `end_value = cue.target_value / 100.0`
  - Build FadeCommand dict (all fields from data-model.md)
  - Call `ch.communications_thread.send_fade_command(payload)`; on error return `"failed"`, no target mutation
  - Return `ActionHandler._action_result("applied", "fade_action", target_id)`
- [x] T014 [US1] Register `_handle_fade_action` in `_ACTION_HANDLERS` dict in `src/cuemsengine/cues/ActionHandler.py`
- [ ] T015 [US1] Add `FadeCue` singledispatch branch to `src/cuemsengine/cues/run_cue.py`
- [ ] T016 [US1] Implement `CueHandler.on_fade_complete(fade_id: str)` in `src/cuemsengine/cues/CueHandler.py`:
  - Log receipt of fade_complete with fade_id; for fade-down: call `self.disarm(target_cue)` (resolution mechanism TBD)
- [ ] T018 [US1] Modify `run_audioCue` in `src/cuemsengine/cues/run_cue.py` to consume `_fade_initial_volume` side-channel attribute (check `getattr(cue, '_fade_initial_volume', None)`, use it for initial `/volmaster` write if set, then `del cue._fade_initial_volume`)

**Checkpoint**: US1 acceptance scenarios 1–2 pass. MTC-pause/resume (scenario 3) and pre-arm (scenario 4) handled in later tasks.

---

## Phase 4: US2 — Fade-Down FadeCue (Priority: P2)

**Goal**: Firing a FadeCue with `target_value=0` dispatches a fade-down command; on `fade_complete` the target is disarmed.

**Independent Test**: Unit-test `_handle_fade_action` with `target_value=0`; verify `start_value` from Ossia cache, `end_value=0.0`, disarm called on completion.

> **TDD**: Write tests FIRST.

- [ ] T019 Write failing tests for `_handle_fade_action` (fade-down path) in `tests/test_fade_action_handler.py`:
  - `target_value=0`: start_value from Ossia cache (not 0.0), end_value=0.0
  - Target not playing → logs warning, returns `"failed"`
- [ ] T020 Write failing tests for `CueHandler.on_fade_complete` (fade-down path) — `disarm` is called on target_cue
- [x] T022 [US2] Extend `_handle_fade_action` in `src/cuemsengine/cues/ActionHandler.py` — fade-down path:
  - If `target_value == 0` and target_cue not playing: log warning, return `"failed"`
  - `start_value = target_cue._osc.get_value(osc_path)` (from live cache)
  - `end_value = 0.0`

**Checkpoint**: US2 acceptance scenarios 1–4 pass.

---

## Phase 5: US3 — Clean Project Load and Stop (Priority: P3)

**Goal**: CANCEL_ALL dispatched to gradient-motiond before players stop on load and stop.

**Independent Test**: Start a long fade, trigger project stop, verify no OSC messages after stop (via mock NNG send spy).

> **TDD**: Write tests FIRST.

- [x] T024 Write failing tests for `ControllerEngine` CANCEL_ALL in `tests/test_controller_engine_gradient.py`:
  - `stop_script`: `_send_gradient_cancel_all()` called before `_forward_command_to_nodes`
  - `load_project`: `_send_gradient_cancel_all()` called before `_forward_load_to_nodes`
  - No fades in progress: call still succeeds without error
- [x] T025 [US3] Implement `ControllerEngine._send_gradient_cancel_all()` in `src/cuemsengine/ControllerEngine.py`:
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
- [x] T026 [US3] Call `self._send_gradient_cancel_all()` at the correct point in `stop_script` (before `_forward_command_to_nodes`)
- [x] T027 [US3] Call `self._send_gradient_cancel_all()` at the correct point in `load_project` (before `_forward_load_to_nodes`)

**Checkpoint**: US3 acceptance scenarios 1–3 pass ✅

---

## Phase 6: US1 (continued) — Pre-arm at Load (Priority: P1 supplement)

**Goal**: FadeCue targets with `target_value > 0` are pre-armed at project load.

> **TDD**: Write test FIRST.

- [x] T028 Write failing test for CueHandler pre-arm extension in `tests/test_fade_action_handler.py` — FadeCue with `target_value=100` triggers `arm(target_cue, init)` at load; FadeCue with `target_value=0` does NOT
- [ ] T029 [US1] Extend pre-arm block in `CueHandler.arm()` in `src/cuemsengine/cues/CueHandler.py`:
  ```python
  if isinstance(cue, ActionCue) and cue._action_target_object:
      should_prearm = cue.action_type == 'play' or (
          cue.action_type == 'fade_action' and
          getattr(cue, 'target_value', 0) > 0
      )
      if should_prearm:
          self.arm(cue._action_target_object, init)
  ```

**Checkpoint**: US1 acceptance scenario 4 passes.

---

## Phase 7: Polish & Integration

- [ ] T030 [P] Import `FadeCue` into `src/cuemsengine/cues/CueHandler.py` (needed for `isinstance` check if pre-arm uses FadeCue type)
- [ ] T031 [P] Verify `FadeCue` is imported in `src/cuemsengine/cues/run_cue.py`
- [ ] T032 Run full test suite; confirm no regressions in existing tests: `poetry run pytest tests/ -v`
- [ ] T033 Validate `quickstart.md` sequence diagrams match implemented call paths
- [ ] T034 Review all new Logger calls: confirm each includes `fade_id` and `target_cue.id` per FR-013

---

## Dependencies & Execution Order

```
Phase 1 (T005–T006) → BLOCKS all phases
Phase 2 (T007–T008) → can start after Phase 1
Phase 3 (T009–T018) → can start after Phase 1; MVP deliverable
Phase 4 (T019–T022) → can start after Phase 1 (needs T016 from Phase 3 for on_fade_complete)
Phase 5 (T024–T027) → can start after Phase 1 (independent of Phase 3/4)
Phase 6 (T028–T029) → depends on Phase 3 CueHandler changes
Phase 7 (T030–T034) → after all phases
```

**TDD order within each phase**: Write test → confirm FAIL → implement → confirm PASS → next.
