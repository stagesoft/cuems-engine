<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tasks: Gradient OSC Transport

**Input**: `specs/005-gradient-osc-transport/`  
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Data model**: [data-model.md](data-model.md) | **Wire contract**: [contracts/gradient_osc.md](contracts/gradient_osc.md)

**Tests**: Included — TDD is NON-NEGOTIABLE (constitution). Write failing test → confirm failure → implement → green → refactor.

**Organization**: Tasks grouped by user story. Foundational phase (Tasks 1–4) must complete before any user story work begins.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel with other [P] tasks (different files, no blocking dependency)
- **[Story]**: User story this task belongs to ([US1], [US2], [US3])
- Exact file paths in all descriptions

---

## Phase 1: Setup

**Purpose**: Refresh `poetry.lock` to materialise the `cuemsutils = "0.1.0rc8"` pin in `pyproject.toml`. rc8 ships the `<gradient_osc_port>` XSD element required by FR-010 / Phase 5; running tests against the stale rc4 lock would mask XSD validation failures and produce green tests for the wrong reason.

**⚠️ Blocking**: T000 must complete before any other task — every settings-loading test depends on the rc8 schema being installed.

- [ ] T000 Run `poetry lock` to refresh `poetry.lock` from `pyproject.toml`'s `cuemsutils = "0.1.0rc8"` pin (Poetry 2.x: `--no-update` was removed; bare `poetry lock` is the right command and does not force-upgrade unrelated packages — they re-resolve at their existing constraints). Then `poetry install` to materialise the package; verify with `poetry show cuemsutils` reports `0.1.0rc8`. If resolution fails, fix the constraint conflict before continuing — do NOT downgrade `pyproject.toml` to rc4.

**Checkpoint**: `poetry show cuemsutils` reports `0.1.0rc8`.

---

## Phase 2: Foundational — GradientClient + PlayerHandler

**Purpose**: Establish the OSC send primitive (`GradientClient`) and its lifecycle hook in `PlayerHandler`. ALL three user stories depend on these two classes being correct before any can be worked.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T001 Write failing unit tests for `GradientClient` — 8 tests covering `/gradient/start_fade` emission, `,sssisffhiss` type-tag string, `node_uuid` self-injection at position 1, `start_mtc_ms` int64 `h` tag, `/gradient/cancel_all`, `/gradient/cancel_motion`, and OSC send error re-raise — in `tests/test_gradient_client.py`
- [ ] T002 Implement `GradientClient(host, port, node_uuid)` with `send_fade`, `send_cancel_motion`, `send_cancel_all` using `OscMessageBuilder` for `send_fade` (explicit `arg_type='h'` on `start_mtc_ms`) and `PyOscClient.send_message` for cancels — in `src/cuemsengine/players/GradientClient.py`
- [ ] T003 Write failing unit tests for `PlayerHandler.gradient_client` lifecycle — default `None`, `set_gradient_client(port, node_uuid)` constructs correct `GradientClient`, re-call replaces prior instance (reconnection safe-guard) — in `tests/test_player_handler_gradient.py`
- [ ] T004 Add `_gradient_client: GradientClient | None = None` attribute and implement `set_gradient_client(port, node_uuid)` + `get_gradient_client()` methods in `src/cuemsengine/players/PlayerHandler.py`

**Checkpoint**: `pytest tests/test_gradient_client.py tests/test_player_handler_gradient.py` green — client fires correct OSC packets and PlayerHandler lifecycle is wired.

---

## Phase 3: User Story 1 — FadeCue dispatches reach gradient-motiond (Priority: P1) 🎯 MVP

**Goal**: Replace the NNG `send_fade_command` call in `ActionHandler` with `PLAYER_HANDLER.get_gradient_client().send_fade(...)`. Rename all `fade_id` / `entry_fade_id` identifiers to `motion_id` / `entry_motion_id`.

**Independent Test**: `pytest tests/test_fade_action_handler.py` passes — all assertions verify the OSC call path and `motion_id` key semantics.

- [ ] T005 [P] [US1] Update `tests/test_fade_action_handler.py` — rename `fade_id=` kwargs to `motion_id=`, replace `ch.communications_thread.send_fade_command(...)` mock assertions with `PLAYER_HANDLER.get_gradient_client().send_fade(...)` patches (method-call access — parity with `get_video_client()` / `get_dmx_player_client()`), rename NNG-named test methods to OSC equivalents (`test_nng_send_failure_returns_failed` → `test_osc_send_failure_returns_failed`, etc.) — confirm tests FAIL before touching implementation
- [ ] T006 [US1] Rename `fade_id` → `motion_id` and `entry_fade_id` → `entry_motion_id` in `_build_fade_payload` (parameter, locals, dict key) in `src/cuemsengine/cues/ActionHandler.py`
- [ ] T007 [US1] Replace NNG dispatch in `ActionHandler._handle_fade_action` with `PLAYER_HANDLER.get_gradient_client().send_fade(motion_id=entry_motion_id, osc_host='127.0.0.1', osc_port=..., ...)` (no `node_name` arg — injected by client); add `None` guard returning `failed` if client not initialised; update log strings `"NNG dispatch"` → `"OSC dispatch"` — in `src/cuemsengine/cues/ActionHandler.py`

**Checkpoint**: `pytest tests/test_fade_action_handler.py` green — FadeCue GO emits correct OSC packet; failures return `failed` result and log at ERROR.

---

## Phase 4: User Story 2 — Cancel-all on STOP and project load (Priority: P1)

**Goal**: NodeEngine calls `send_cancel_all()` as the first action on STOP and on project load, freeing in-flight motions in the daemon. ControllerEngine must NOT send any gradient OSC.

**Independent Test**: `pytest tests/test_node_engine_gradient.py` passes — cancel_all ordering, setup orchestration, and `None` guard all verified.

- [ ] T008 [P] [US2] Write failing tests for NodeEngine cancel-all behaviour and setup wiring — `node_uuid` pass-through to `PLAYER_HANDLER.set_gradient_client`, `set_gradient_client()` invoked from setup orchestrator alongside `set_video_players` / `set_dmx_players`, `cancel_all` fires before `stop_all_cues` on STOP, `cancel_all` fires on project load, `None` guard prevents crash when client not yet set — assert via `caplog` that a DEBUG-level record matching `gradient_client not initialised` (or chosen wording) is emitted on skip — in `tests/test_node_engine_gradient.py` (port-binding test lives in Phase 5 / US3, T011). NOTE: no explicit `PORT_HANDLER.add_config_ports` assertion — registration is handled by the pre-existing `get_config_ports(node_conf)` helper, not by `set_gradient_client` (see plan Decision 6); a `test_set_gradient_client_defaults_to_7100` is also out of scope (rc8 XSD makes the element required).
- [ ] T009 [US2] Implement `NodeEngine.set_gradient_client()` method — reads `self.cm.node_conf['gradient_osc_port']` (direct dict access; no `.get()` fallback because the `cuemsutils >= 0.1.0rc8` XSD makes the element required, so a validated `node_conf` always contains it), calls `PLAYER_HANDLER.set_gradient_client(port=int(gradient_osc_port), node_uuid=self.cm.node_uuid)` — in `src/cuemsengine/NodeEngine.py`. Do NOT introduce a `GRADIENT_OSC_PORT_DEFAULT` constant (no caller would reference it — Constitution IV) and do NOT call `PORT_HANDLER.add_config_ports` explicitly (registration is handled by the pre-existing `get_config_ports(node_conf)` helper). This implementation makes BOTH the US2 setup-wiring tests (T008) AND the US3 port-binding test (T011) green.
- [ ] T010 [US2] Wire `self.set_gradient_client()` into node setup orchestrator alongside `set_video_players()` / `set_dmx_players()` calls; add guarded `cancel_all` block as first action in `stop_playback` (before `CUE_HANDLER.stop_all_cues`) and in `_load_project_inner` (before `CUE_HANDLER.stop_all_cues`) — guard pattern: `if gradient_client:` wrapping a `try` that logs ERROR on `send_cancel_all` exception; `else: Logger.debug(...)` on skip per spec edge case 4 — in `src/cuemsengine/NodeEngine.py`

**Checkpoint**: `pytest tests/test_node_engine_gradient.py` green — NodeEngine initialises the client and cancels in-flight fades on stop/load before any other cleanup.

---

## Phase 5: User Story 3 — Daemon port configurable via settings (Priority: P2)

**Goal**: `settings.xml` accepts `<gradient_osc_port>` under `<node>`; engine reads it at startup and sends all gradient OSC to that port.

**Independent Test**: `pytest tests/test_node_engine_gradient.py -k port_binding` (or equivalent) passes — only the custom-port path is exercised; the absent-element path is unreachable per the rc8 XSD (validation rejects at settings-load layer, not at the engine).

- [ ] T011 [P] [US3] Write a failing test for `gradient_osc_port` settings binding — a custom value in `node_conf` (e.g. 7200) flows through `NodeEngine.set_gradient_client()` into `PLAYER_HANDLER.set_gradient_client(port=7200, ...)` — in `tests/test_node_engine_gradient.py`. The absence/default path is intentionally NOT tested: `cuemsutils >= 0.1.0rc8` XSD makes the element required, so any `node_conf` without `gradient_osc_port` is rejected at the settings-loader layer (cuemsutils' own tests cover that boundary).
- [ ] T012 [P] [US3] Add `<gradient_osc_port>7100</gradient_osc_port>` as a flat child of `<node>` block (alongside other flat node config elements; place it after `<nng_hub_port>` to match the XSD field order) in `dev/test_xml_files/settings.xml`. The `cuemsutils >= 0.1.0rc8` schema requires this element — without it, **any** test loading the fixture via `ConfigManager` (e.g. `tests/test_controller_commands.py`, `tests/test_nodeengine_helpers.py`, `tests/test_core_baseengine_status.py`, `tests/test_default_mappings_valid.py`, plus the `env_config_path` fixture in `tests/fixtures.py`) will fail XSD validation. Audit other test files for inline settings XML strings and add the element there as well if found. **Do NOT mark tests `pytest.mark.xfail`** — the schema has shipped in rc8; failures indicate a fixture or lockfile bug, not a schema-availability gap.

**Checkpoint**: `grep gradient_osc_port dev/test_xml_files/settings.xml` shows the element; T011 test green (US2 setup-wiring tests already green from T009); the four ConfigManager-using test files above all load the fixture without XSD errors.

---

## Phase 6: Polish — Remove NNG gradient code

**Purpose**: Delete dead NNG methods (`send_fade_command`, `send_cancel_all`, `_send_gradient_cancel_all`) and their obsolete tests now that no callers remain.

**⚠️ Order matters**: T013 → T014 → T015 (NodeCommunications); T016 → T017 (ControllerEngine) — confirm `pytest -x` green after each step.

- [ ] T013 Run `grep -rn "send_fade_command\|NodeCommunications.*send_cancel_all" src/` to confirm no callers remain; delete `send_fade_command` and `send_cancel_all` methods from `src/cuemsengine/comms/NodeCommunications.py`
- [ ] T014 Create `tests/test_node_communications_gradient_filter.py` by moving `TestGradientEngineCommandFilter` and `TestGradientStatusDiscarded` test classes from `tests/test_node_communications_gradient.py` (these filter/status tests are unaffected by the NNG removal)
- [ ] T015 Delete `tests/test_node_communications_gradient.py` in full (remaining tests cover `send_fade_command` / `send_cancel_all` which are now gone)
- [ ] T016 Delete `TestSendGradientCancelAll`, `TestStopScriptCancelAllOrder`, `TestLoadProjectCancelAllOrder` test classes from `tests/test_controller_engine_gradient.py`; retain `TestGradientEngineSenderGuard` (status sender guard is unchanged)
- [ ] T017 Delete `_send_gradient_cancel_all` method and its two call sites (`load_project` ~line 773, `stop_script` ~line 903) from `src/cuemsengine/ControllerEngine.py`
- [ ] T018 [P] Full regression sweep: confirm `poetry show cuemsutils` reports `0.1.0rc8`; run `poetry run pytest -x` and confirm `tests/test_controller_commands.py`, `tests/test_nodeengine_helpers.py`, `tests/test_core_baseengine_status.py`, `tests/test_default_mappings_valid.py` all import & run cleanly against the updated fixture (no XSD validation errors); confirm `grep -rn "fade_id\|entry_fade_id" src/ tests/ | grep -v ".pyc"` has no hits outside intentional cue-type names; confirm `grep -rn "send_fade_command\|_send_gradient_cancel_all" src/` has no hits; confirm `grep -rn "GRADIENT_OSC_PORT_DEFAULT" src/ tests/` has no hits (constant deliberately not introduced — see T009)

**Checkpoint**: Full suite green; no lingering NNG gradient references in source or tests.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T000 is blocking for everything else — `poetry.lock` must reflect `cuemsutils 0.1.0rc8` before any test runs (rc4 silently masks XSD validation gaps).
- **Foundational (Phase 2)**: requires Phase 1 complete
- **User Stories (Phase 3–5)**: All require Phase 2 complete
  - US1 (Phase 3) and US2 (Phase 4) can proceed in parallel once Phase 2 is green (different files)
  - US3 (Phase 5 — `settings.xml` only) can run in parallel with US1 and US2; T012 (fixture update) SHOULD ideally precede the first run of any test that loads `dev/test_xml_files/settings.xml` once Phase 1 has bumped cuemsutils to rc8
- **Polish (Phase 6)**: Requires US1 complete (no NNG callers remain) and US2 complete (ControllerEngine NNG path confirmed superseded)

### Within Each User Story

- Tests MUST be written and confirmed FAILING before implementation
- T005 (tests) before T006–T007 (implementation)
- T008 (US2 tests) AND T011 (US3 tests) both before T009 (implementation makes BOTH suites green)
- T006 before T007 (both in `ActionHandler.py` — `_build_fade_payload` rename feeds `_handle_fade_action` call site)
- T009 before T010 (both in `NodeEngine.py` — constant and method must exist before wiring)
- T014 before T015 (move filter tests, THEN delete the source file)

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no dependency on US2 or US3
- **US2 (P1)**: Can start after Phase 2 — no dependency on US1 or US3
- **US3 (P2)**: Can start after Phase 2 — owns its own port-binding tests (T011); the implementation that satisfies them (T009) is in US2 but is shared by both stories

---

## Parallel Opportunities

```bash
# Phase 2 — GradientClient tests and PlayerHandler tests (both foundational):
# T001 (test_gradient_client.py) — write failing tests
# T003 (test_player_handler_gradient.py) — write failing tests
# NOTE: T003 needs T002 green (GradientClient must import) before T004 can pass

# Once Phase 2 complete — US1, US2 and US3 test-writing can start together:
# T005 [P] — test_fade_action_handler.py updates (US1)
# T008 [P] — test_node_engine_gradient.py setup/cancel tests (US2)
# T011 [P] — test_node_engine_gradient.py port-binding tests (US3)
# T012 [P] — settings.xml fixture (US3)
# NOTE: T009 implementation in NodeEngine.py makes both T008 and T011 green.
```

---

## Implementation Strategy

### MVP (US1 + US2 Only — P1 stories)

1. Complete Phase 2: Foundational (GradientClient + PlayerHandler)
2. Complete Phase 3: US1 (ActionHandler dispatch via OSC)
3. Complete Phase 4: US2 (NodeEngine cancel_all on stop/load)
4. **STOP and VALIDATE**: `poetry run pytest -x` green; manual `fade-test` run on node-002
5. Complete Phase 5 (US3) and Phase 6 (Polish) in a follow-up

### Incremental Delivery

1. Phase 2 → Foundation ready; OSC primitive exists and is tested
2. Phase 3 (US1) → FadeCue GO emits correct OSC; NNG path replaced
3. Phase 4 (US2) → STOP/load cancel-all wired; daemon always cleaned up
4. Phase 5 (US3) → Port configurable without code change
5. Phase 6 (Polish) → Dead NNG code removed; full suite clean

---

## Post-Implementation Verification

Per plan.md success criteria:

- `poetry run pytest tests/test_gradient_client.py -v` — all 8+ tests pass (SC-004)
- `poetry run pytest -x` — full suite green, no regressions (SC-005)
- Manual: FadeCue GO on node-002 `fade-test` project, 5s linear to 0 — smooth fade, no bounce (SC-001)
- Manual: press STOP after fade — no stale fade in daemon between runs (SC-002)
- `ldd /usr/bin/gradient-motiond | grep -i nng` — no output (SC-003, already true for v0.3.0)
- Engine log: no `gradientengine` NNG routing errors or `controller.local` warnings during fade run (SC-006)
