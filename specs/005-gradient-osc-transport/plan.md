<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Implementation Plan: Gradient OSC Transport

**Branch**: `005-gradient-osc-transport` | **Date**: 2026-05-14 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/005-gradient-osc-transport/spec.md`

## Summary

Replace the NNG-over-bus0 gradient-motiond dispatch path in cuems-engine with
direct localhost UDP OSC, using a new `GradientClient` class that wraps
`PyOscClient` / `OscMessageBuilder` from the already-declared `python-osc`
dependency. `GradientClient` is initialised by a dedicated
`NodeEngine.set_gradient_client()` method following the established
`set_video_client` / `set_dmx_players` pattern; the client holds the node
UUID at construction and injects it on every `send_fade`.
`NodeCommunications.send_fade_command` and `send_cancel_all` are deleted;
`ControllerEngine._send_gradient_cancel_all` and its call sites are deleted;
`ActionHandler` is updated to call `PLAYER_HANDLER.gradient_client` directly;
all `fade_id` identifiers are renamed `motion_id` per FR-013.
`<gradient_osc_port>` is consumed via the `cuemsutils >= 0.1.0rc8` settings
XSD as a required element under `<node>` — no engine-side default-fallback;
port registration with `PORT_HANDLER` is handled automatically by the
pre-existing `get_config_ports(node_conf)` helper.

## Technical Context

**Language/Version**: Python 3.11 (pyenv + Poetry)  
**Primary Dependencies**: `python-osc 1.9.3` (already in `pyproject.toml`); `pytest`  
**Storage**: N/A  
**Testing**: pytest (`tests/` at repo root)  
**Target Platform**: Linux (Debian node hardware)  
**Project Type**: Background service / library  
**Performance Goals**: Fire-and-forget UDP; no latency target beyond what the OS UDP stack provides  
**Constraints**: No new runtime dependencies. `GradientClient` must not allocate a local OSC port (no server-side binding needed).  
**Scale/Scope**: One `GradientClient` instance per node process; one daemon per node.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Assessment | Evidence / Risk |
|-----------|------------|-----------------|
| **TDD** | ✅ Compliant | All tasks below: failing test first, then implementation. Test files listed before production files in each task. |
| **SOLID — SRP** | ✅ `GradientClient` owns only OSC send; `PlayerHandler` owns lifecycle; `ActionHandler` owns dispatch orchestration. |
| **SOLID — OCP** | ✅ `send_cancel_motion` generic by design (future motion types reuse without modifying `GradientClient`). |
| **SOLID — DIP** | ✅ `ActionHandler` depends on `PlayerHandler` singleton (already the project pattern), not on `GradientClient` concrete type directly. |
| **YAGNI** | ✅ Single `GradientClient` (no `GradientPlayer` stub); no NNG compatibility shim; no feature flag. |
| **Observability** | ✅ FR-011: all errors logged at ERROR; all silent failures forbidden. |
| **No new deps** | ✅ `python-osc 1.9.3` already declared in `pyproject.toml`. |

**Constitution violations**: None. No Complexity Tracking table needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-gradient-osc-transport/
├── plan.md              # This file
├── research.md          # Phase 0 — OSC type-tag verification + pattern decisions
├── data-model.md        # Phase 1 — entities and state model
├── contracts/
│   └── gradient_osc.md  # Phase 1 — OSC wire contract (daemon-authoritative)
└── tasks.md             # Phase 2 — /speckit-tasks output (not yet created)
```

### Source Code

```text
src/cuemsengine/
├── players/
│   └── GradientClient.py          # NEW — OSC send-only client
├── players/
│   └── PlayerHandler.py           # MODIFY — add _gradient_client, init_gradient_client, get_gradient_client
├── cues/
│   └── ActionHandler.py           # MODIFY — fade_id→motion_id; send via PLAYER_HANDLER.gradient_client
├── comms/
│   └── NodeCommunications.py      # MODIFY — delete send_fade_command, send_cancel_all
├── ControllerEngine.py            # MODIFY — delete _send_gradient_cancel_all + call sites
└── NodeEngine.py                  # MODIFY — init gradient_client; cancel_all on stop + load

dev/test_xml_files/
└── settings.xml                   # MODIFY — add <gradient_osc_port>7100</gradient_osc_port>

tests/
├── test_gradient_client.py        # NEW — GradientClient unit tests (SC-004)
├── test_fade_action_handler.py    # MODIFY — motion_id rename; OSC path assertions
├── test_node_communications_gradient.py   # DELETE (FR-012)
├── test_controller_engine_gradient.py     # PARTIAL DELETE (keep sender-guard tests)
└── [test_node_communications_gradient_filter.py]  # NEW if sender-guard tests need a home
```

## Implementation Tasks

Tasks are ordered to maintain a green test suite throughout. Each task
follows the TDD Red → Green → Refactor cycle.

---

### Task 1 — `GradientClient` (new class + unit tests)

**Files**: `tests/test_gradient_client.py` (new), `src/cuemsengine/players/GradientClient.py` (new)

**Why first**: All downstream changes (ActionHandler, NodeEngine) depend on this class existing and behaving correctly.

**Key design points** (from analysis decisions):
- `node_uuid` is held by the client and injected as `node_name` on every `send_fade` (parity with `VideoClient(player_port=port)` which is constructed with its config and reused).
- `send_fade`'s signature no longer takes `node_name` from callers — they don't need to know it.
- Tests use a real UDP listener socket bound to an ephemeral port; messages parsed via `python-osc`'s public `OscMessage(data)` constructor.

**TDD steps**:

1. Create `tests/test_gradient_client.py` with failing tests, each binding a `socket.AF_INET/SOCK_DGRAM` listener on an ephemeral port, constructing `GradientClient(host='127.0.0.1', port=<that_port>, node_uuid='node-test')`, calling the method under test, and parsing the received datagram with `pythonosc.osc_message.OscMessage(data)`:
   - `test_send_fade_emits_correct_osc_address` — received message address is `/gradient/start_fade`
   - `test_send_fade_type_tags` — `OscMessage(data).dgram` decoded type-tag string is `,sssisffhiss`
   - `test_send_fade_motion_id_at_position_0` — `params[0] == motion_id`
   - `test_send_fade_node_uuid_injected_as_node_name` — `params[1] == 'node-test'` (the constructor-supplied uuid)
   - `test_send_fade_start_mtc_ms_is_int64` — type tag at index 7 is `h`; value round-trips for `int` values that exceed int32 range (e.g., `2**33`)
   - `test_send_cancel_all_emits_correct_address` — received message address is `/gradient/cancel_all`, no params
   - `test_send_cancel_motion_emits_correct_address` — address `/gradient/cancel_motion`, `params[0] == motion_id`
   - `test_send_fade_osc_error_is_raised` — when the underlying `SimpleUDPClient.send` raises (patch to raise `OSError`), `send_fade` logs ERROR and re-raises

2. Confirm all 8 tests fail (`pytest tests/test_gradient_client.py`).

3. Create `src/cuemsengine/players/GradientClient.py`:
   ```python
   from pythonosc.osc_message_builder import OscMessageBuilder
   from ..osc.PyOsc import PyOscClient
   from cuemsutils.log import Logger

   class GradientClient:
       """Fire-and-forget UDP OSC client for gradient-motiond v0.3.0.

       Holds node_uuid at construction (analogous to VideoClient(player_port=port))
       and injects it as `node_name` on every send_fade — callers don't need to
       know the node identity. Safe to construct multiple times; each new
       instance replaces the prior one in PlayerHandler.
       """

       def __init__(self, host: str = '127.0.0.1', port: int = 7100,
                    node_uuid: str = ''):
           self._host = host
           self._port = port
           self._node_uuid = node_uuid
           self._osc = PyOscClient(host=host, port=port)

       def send_fade(self, motion_id, osc_host, osc_port, osc_path,
                     start_value, end_value, start_mtc_ms, duration_ms,
                     curve_type, curve_params_json='{}'):
           builder = OscMessageBuilder(address='/gradient/start_fade')
           builder.add_arg(motion_id,              arg_type='s')
           builder.add_arg(self._node_uuid,        arg_type='s')   # node_name
           builder.add_arg(osc_host,               arg_type='s')
           builder.add_arg(int(osc_port),          arg_type='i')
           builder.add_arg(osc_path,               arg_type='s')
           builder.add_arg(float(start_value),     arg_type='f')
           builder.add_arg(float(end_value),       arg_type='f')
           builder.add_arg(int(start_mtc_ms),      arg_type='h')   # int64
           builder.add_arg(int(duration_ms),       arg_type='i')
           builder.add_arg(curve_type,             arg_type='s')
           builder.add_arg(curve_params_json,      arg_type='s')
           try:
               self._osc.client.send(builder.build())
           except Exception as exc:
               Logger.error(f'GradientClient.send_fade failed: {exc}')
               raise

       def send_cancel_motion(self, motion_id: str):
           try:
               self._osc.send_message('/gradient/cancel_motion', motion_id)
           except Exception as exc:
               Logger.error(f'GradientClient.send_cancel_motion failed: {exc}')
               raise

       def send_cancel_all(self):
           try:
               self._osc.send_message('/gradient/cancel_all', [])
           except Exception as exc:
               Logger.error(f'GradientClient.send_cancel_all failed: {exc}')
               raise
   ```

4. Run `pytest tests/test_gradient_client.py` — all tests green.

5. Add SPDX header to `GradientClient.py`.

---

### Task 2 — `PlayerHandler`: add `gradient_client` attribute

**Files**: `src/cuemsengine/players/PlayerHandler.py`, `tests/test_player_handler_gradient.py` (new)

**Naming parity** (decision C1): use `set_gradient_client(self, port, node_uuid)` to match the existing `set_video_client(self, port)` shape. No `@property` — method-only access via `get_gradient_client()` for parity with `get_video_client()` / `get_dmx_player_client()`.

**Multi-call safety** (decision C9): re-calling `set_gradient_client` replaces the prior client (reconnection safe-guard). No teardown of the prior client is needed — `PyOscClient` is a fire-and-forget UDP sender with no held resources.

**TDD steps**:

1. Add failing tests (new file `tests/test_player_handler_gradient.py`):
   - `test_player_handler_gradient_client_default_none` — freshly reset `PlayerHandler._instance._gradient_client` is `None`.
   - `test_set_gradient_client_constructs_client` — after `PLAYER_HANDLER.set_gradient_client(port=7200, node_uuid='node-002')`, `PLAYER_HANDLER.get_gradient_client()` returns a `GradientClient` with `_port == 7200` and `_node_uuid == 'node-002'`.
   - `test_set_gradient_client_replaces_prior` — calling `set_gradient_client` twice with different ports yields a new client instance whose `_port` matches the second call (reconnection safe-guard).

2. In `PlayerHandler.__new__` init block, add:
   ```python
   cls._instance._gradient_client = None
   ```
   And declare type annotation:
   ```python
   _gradient_client: 'GradientClient | None'
   ```

3. Add methods:
   ```python
   def set_gradient_client(self, port: int, node_uuid: str) -> None:
       """Construct (or replace) the GradientClient for this node.

       Safe to call multiple times: any new call replaces the prior client.
       This is the reconnection safe-guard — if settings change, callers can
       re-invoke this method to swap in a fresh client without restarting
       the engine.
       """
       from .GradientClient import GradientClient
       self._gradient_client = GradientClient(
           host='127.0.0.1', port=port, node_uuid=node_uuid,
       )
       Logger.info(
           f'GradientClient: bound to 127.0.0.1:{port} node_uuid={node_uuid}'
       )

   def get_gradient_client(self) -> 'GradientClient | None':
       return self._gradient_client
   ```

4. Green on new tests.

---

### Task 3 — `NodeEngine`: initialise `GradientClient` + cancel on stop/load

**Files**: `src/cuemsengine/NodeEngine.py`, `tests/test_node_engine_gradient.py` (new)

**Pattern parity** (decisions C1, C3, C4, C5, plus rc8 alignment):
- Dedicated setup method `set_gradient_client(self)` on `NodeEngine`, called from the same orchestrator that calls `set_video_players` / `set_dmx_players` / `set_audio_outputs`.
- Direct dict access on `self.cm.node_conf['gradient_osc_port']` — the element is XSD-required (`cuemsutils >= 0.1.0rc8`), so a validated `node_conf` always contains it; no `.get()` fallback, no `GRADIENT_OSC_PORT_DEFAULT` constant.
- Port registration with `PORT_HANDLER` happens automatically via the existing `get_config_ports(node_conf)` helper in `NodeEngine.py` — `set_gradient_client` does NOT call `add_config_ports` explicitly (would create a duplicate entry under a different label for the same UDP port).

**TDD steps**:

1. Write failing tests (new file `tests/test_node_engine_gradient.py`):
   - `test_set_gradient_client_reads_port_from_node_conf` — when `self.cm.node_conf['gradient_osc_port'] == 7200`, `set_gradient_client()` calls `PLAYER_HANDLER.set_gradient_client(port=7200, node_uuid=<cm.node_uuid>)`.
   - `test_set_gradient_client_passes_node_uuid` — `node_uuid` kwarg equals `self.cm.node_uuid`.
   - `test_set_gradient_client_called_during_node_setup` — patch `set_gradient_client` and assert it's called once from the same orchestrator that calls `set_video_players` (or whichever method holds the setup sequence).
   - `test_stop_playback_calls_cancel_all` — patch `PLAYER_HANDLER.get_gradient_client`; call `stop_playback()`; assert `send_cancel_all` invoked.
   - `test_load_project_calls_cancel_all` — same for `_load_project_inner` (FR-005 — cancel_all on project unload to free any lingering motions in the daemon).
   - `test_cancel_all_before_cue_stop_on_stop` — `send_cancel_all` fires before `CUE_HANDLER.stop_all_cues` (FR-004: "before other stop-cleanup actions").
   - `test_cancel_all_does_not_block_when_client_none` — `PLAYER_HANDLER.get_gradient_client()` returns `None`; `stop_playback` / `_load_project_inner` must not raise; `caplog` captures a DEBUG-level record matching `gradient_client not initialised` (or chosen wording — assert exact text once chosen).

   NOTE: a `test_set_gradient_client_defaults_to_7100` test is intentionally
   NOT in this list — the `cuemsutils >= 0.1.0rc8` XSD makes
   `<gradient_osc_port>` required, so the absent-element code path is
   unreachable and must not be implemented (Constitution IV). Settings-load
   failures are the cuemsutils loader's responsibility and are covered by
   cuemsutils' own tests. A `test_set_gradient_client_registers_port` test
   is also out of scope here — port registration is handled by the
   pre-existing `get_config_ports(node_conf)` helper.

2. Add a dedicated `set_gradient_client(self)` method on `NodeEngine`, modelled on `set_video_players`:
   ```python
   def set_gradient_client(self):
       """Initialise (or replace) the local GradientClient.

       gradient-motiond is a systemd service; the engine only needs an OSC
       sender bound to its UDP port. The only configurable parameter is the
       UDP port (flat <gradient_osc_port> under <node> in settings.xml),
       which is REQUIRED by the cuemsutils >= 0.1.0rc8 settings XSD —
       validation rejects a missing element before this method runs, so no
       default-fallback branch is needed. Port registration with
       PORT_HANDLER is handled automatically by the existing
       `get_config_ports(node_conf)` helper in this module.
       """
       gradient_osc_port = int(self.cm.node_conf['gradient_osc_port'])
       PLAYER_HANDLER.set_gradient_client(
           port=gradient_osc_port,
           node_uuid=self.cm.node_uuid,
       )
   ```

3. Call `self.set_gradient_client()` from the same node setup orchestrator that already calls `set_video_players()` and `set_dmx_players()` (locate via `grep -n "set_video_players\|set_dmx_players" NodeEngine.py`).

4. In `stop_playback` (line 926), insert `send_cancel_all` as FIRST cleanup action (before `CUE_HANDLER.stop_all_cues` at line 940), per FR-004:
   ```python
   gradient_client = PLAYER_HANDLER.get_gradient_client()
   if gradient_client:
       try:
           gradient_client.send_cancel_all()
       except Exception as e:
           Logger.error(f'gradient cancel_all failed on stop: {e}')
   else:
       Logger.debug('gradient_client not initialised; skipping cancel_all')
   ```

5. In `_load_project_inner` (line 566), insert the same block before `CUE_HANDLER.stop_all_cues()` at line 574 — this frees any lingering motions in the daemon before the new project loads (FR-005, decision C9).

6. Green on all new tests.

---

### Task 4 — `ActionHandler`: rename `fade_id`→`motion_id`, use `GradientClient`

**Files**: `src/cuemsengine/cues/ActionHandler.py`, `tests/test_fade_action_handler.py`

This is the largest rename + refactor. TDD mandates updating the tests first
to reflect the new interface, confirming they fail, then updating the implementation.

**TDD steps**:

1. **Update test file first** (`test_fade_action_handler.py`):
   - Replace all `fade_id=` kwargs with `motion_id=`
   - Replace all `entry["fade_id"]` with `entry["motion_id"]`
   - Replace all `ch.communications_thread.send_fade_command(...)` assertions with
     `PLAYER_HANDLER.gradient_client.send_fade(...)` assertions (patch `PLAYER_HANDLER`)
   - Rename test methods that mention `nng`:
     - `test_arm_failure_no_nng_dispatch` → `test_arm_failure_no_osc_dispatch`
     - `test_nng_send_failure_returns_failed` → `test_osc_send_failure_returns_failed`
     - `test_nng_failure_target_cue_unchanged` → `test_osc_failure_target_cue_unchanged`
     - `test_video_nng_failure_aborts_remaining_layers` → `test_video_osc_failure_aborts_remaining_layers`
   - Update `_build` helpers in `TestBuildFadePayloadAudio` etc. to pass `motion_id=` instead of `fade_id=`
   - Update `TestHandleFadeActionAudio`:
     - `test_send_fade_command_called_once` → assert `PLAYER_HANDLER.gradient_client.send_fade.call_count == 1`
     - `test_send_fade_command_passes_base_fade_id` → assert `motion_id` arg equals `str(cue.id)`
   - Update wire contract test class (to be renamed `TestStartFadeOSCContract`):
     - Remove `REQUIRED_KEYS` that are envelope fields (now handled inside `GradientClient`)
     - Assert `send_fade` called with correct positional args
   - Confirm tests FAIL (because implementation still uses NNG path)

2. **Update `_build_fade_payload`**:
   - Rename parameter `fade_id` → `motion_id`
   - Rename local `entry_fade_id` → `entry_motion_id`
   - Dict key `"fade_id"` → `"motion_id"` in `_entry()` result

3. **Update `_handle_fade_action`**:
   - Rename `fade_id` → `motion_id`
   - Replace:
     ```python
     ch.communications_thread.send_fade_command(entry, fade_id=entry_fade_id)
     ```
     with:
     ```python
     from ..players.PlayerHandler import PLAYER_HANDLER
     gradient_client = PLAYER_HANDLER.get_gradient_client()
     if gradient_client is None:
         Logger.error(f"FadeCue {motion_id}: GradientClient not initialised")
         return ActionHandler._action_result(
             "failed", "fade_action", target_id,
             "GradientClient not initialised",
         )
     # ... inside the per-entry loop:
     gradient_client.send_fade(
         motion_id=entry_motion_id,
         osc_host='127.0.0.1',
         osc_port=entry['osc_port'],
         osc_path=entry['osc_path'],
         start_value=entry['start_value'],
         end_value=entry['end_value'],
         start_mtc_ms=entry['start_mtc_ms'],
         duration_ms=entry['duration_ms'],
         curve_type=entry['curve_type'],
         curve_params_json='{}',
     )
     ```
   - **`node_name` is not passed** (decisions C6 + C11): the client was constructed with `node_uuid` and injects it on every send. Callers don't need to know the node identity. This removes the previous TBD around `ch.node_name` and prevents a placeholder fallback that would have caused silent `NodeMismatch` drops on the daemon (Constitution V observability gate).
   - Update log message: `"NNG dispatch"` → `"OSC dispatch"`
   - Update error message: `"NNG dispatch failed"` → `"OSC dispatch failed"`

4. Green on all tests in `test_fade_action_handler.py`.

---

### Task 5 — Delete NNG gradient methods from `NodeCommunications`

**Files**: `src/cuemsengine/comms/NodeCommunications.py`

**Precondition**: Task 4 complete (no remaining callers).

**Steps**:
1. Verify no callers remain: `grep -rn "send_fade_command\|send_cancel_all" src/`
2. Delete `send_fade_command` method (lines ~131–160 in current file).
3. Delete `send_cancel_all` method (lines ~161–180 in current file).
4. `pytest -x` must remain green.
5. Delete `test_node_communications_gradient.py` in full (FR-012).
   - **Before deleting**: move `TestGradientEngineCommandFilter` and
     `TestGradientStatusDiscarded` tests to `test_node_communications_gradient_filter.py`
     (they test the command filter / status discard logic which is unchanged).
6. `pytest -x` green.

---

### Task 6 — Delete `ControllerEngine._send_gradient_cancel_all`

**Files**: `src/cuemsengine/ControllerEngine.py`, `tests/test_controller_engine_gradient.py`

**Steps**:
1. In `test_controller_engine_gradient.py`:
   - Delete `TestSendGradientCancelAll`, `TestStopScriptCancelAllOrder`,
     `TestLoadProjectCancelAllOrder` class bodies (FR-012).
   - Keep `TestGradientEngineSenderGuard` (status sender guard is unchanged).
2. Confirm `test_controller_engine_gradient.py` passes with only sender-guard tests.
3. In `ControllerEngine.py`:
   - Delete `_send_gradient_cancel_all` method (~line 868).
   - Delete the two call sites:
     - In `load_project` (~line 773): `self._send_gradient_cancel_all()`
     - In `stop_script` (~line 903): `self._send_gradient_cancel_all()`
4. `pytest -x` green.

---

### Task 7 — `settings.xml`: add `<gradient_osc_port>`

**Files**: `dev/test_xml_files/settings.xml`

**Schema shape decision** (C8): `<gradient_osc_port>` is a **flat child of `<node>`**
(not nested under a hypothetical `<gradient_motiond>` parent block). Rationale: the
UDP port is the **only** configurable parameter for gradient-motion-engine on the
engine side — there is no `path`, no `args`, no `osc_input_port` vs `osc_output_port`
to distinguish. A nested block would be a one-element pseudo-namespace.

**Steps**:
1. Open `dev/test_xml_files/settings.xml`.
2. Add `<gradient_osc_port>7100</gradient_osc_port>` inside the `<node>` block,
   alongside other flat node config elements.
3. Verify the XSD in `cuems-utils` (external repo) is updated as a tracked dependency.
   If XSD update is blocked, annotate with TODO and continue — the engine reads the
   value permissively; the XSD update is a packaging concern.
4. The fixture-based assertion (port 7200 → `GradientClient` on 7200) is already
   covered by `test_set_gradient_client_reads_port_from_node_conf` in Task 3.

---

### Task 8 — Full regression sweep

**Steps**:
1. `poetry run pytest -x` — full suite green.
2. Check for any lingering `fade_id` or `entry_fade_id` references:
   ```
   grep -rn "fade_id\|entry_fade_id" src/ tests/ | grep -v ".pyc"
   ```
   All hits must be in comments or strings that are intentionally fade-specific
   (e.g., `FadeCue`, `fade_action` — these are exempt per FR-013 scope).
3. Check for any lingering `send_fade_command` or `send_cancel_all` references in `NodeCommunications`:
   ```
   grep -rn "send_fade_command\|send_cancel_all" src/
   ```
   No hits expected.
4. Check for any `_send_gradient_cancel_all` or `gradientengine` NNG routing
   references in `ControllerEngine`:
   ```
   grep -rn "_send_gradient_cancel_all" src/
   ```
   No hits expected.

---

## Key Architectural Decisions (from research.md + analysis)

1. **`PLAYER_HANDLER.gradient_client` (singleton access)**: follows existing
   project pattern where all action/run-cue modules import `PLAYER_HANDLER` directly.
   FR-006 wording resolved accordingly (no `ch.player_handler` indirection).

2. **`set_gradient_client(port, node_uuid)` (naming + signature parity with
   `set_video_client(port)`)**: dedicated `NodeEngine.set_gradient_client()` method
   called from the same setup orchestrator as `set_video_players` / `set_dmx_players`.
   `node_uuid` is passed at construction (analogous to `VideoClient(player_port=port)`)
   and injected as `node_name` on every `send_fade`. Re-calling `set_gradient_client`
   replaces the prior client (reconnection safe-guard).

3. **`OscMessageBuilder` for `send_fade`**: required because `start_mtc_ms` must be
   sent as `h` (int64); `PyOscClient.send_message` only produces `i` (int32) for
   Python `int`. `PyOscClient` is still used for `cancel_all` and `cancel_motion`.

4. **No `GradientPlayer` stub**: daemon is a systemd service; no subprocess management.
   Single `GradientClient` class only.

5. **`cancel_all` owned by `NodeEngine`**: ControllerEngine MUST NOT send gradient OSC —
   cancel is a node-local concern. Fires on both STOP (FR-004) and project load
   (FR-005) before any other cleanup, to free any lingering motions in the daemon.

6. **Port-handler registration**: Handled automatically by the existing
   `get_config_ports(node_conf)` helper in `NodeEngine.py`, which collects
   every `*_port` key from `node_conf` — `gradient_osc_port` is picked up
   by that path without additional code. `set_gradient_client` MUST NOT
   call `add_config_ports` explicitly (would create a duplicate entry
   under a different label for the same UDP port).

7. **Flat `<gradient_osc_port>` settings key**: child of `<node>`, not nested.
   The UDP port is the only configurable parameter for gradient-motion-engine on
   the engine side; a nested block would be a one-element pseudo-namespace.

8. **FR-013 rename scope**: rename `fade_id`/`entry_fade_id` → `motion_id`/`entry_motion_id`
   in `ActionHandler`, `_build_fade_payload`, tests; cue-type-specific names
   (`FadeCue`, `fade_action`, `send_fade`) are NOT renamed.

9. **No `node_name` placeholder fallback in callers**: `GradientClient` holds
   `node_uuid` and injects it. If construction was skipped, `_handle_fade_action`
   returns `failed` with an ERROR log — no `'127.0.0.1'` placeholder. Required by
   Constitution V (no silent failures: a wrong `node_name` would be silently dropped
   by daemon `NodeMismatch` filtering).

## Post-Implementation Verification

- `poetry run pytest tests/test_gradient_client.py -v` — all 8+ tests pass (SC-004)
- `poetry run pytest -x` — full suite green (SC-005)
- Manual test: `fade-test` project on node-002, 5s linear fade to 0, human ear/eye (SC-001)
- Manual test: press STOP after fade; confirm no stale fade in daemon (SC-002)
- `ldd /usr/bin/gradient-motiond | grep -i nng` → no output (SC-003)
- Engine log: no `gradientengine` NNG routing errors or `controller.local` warnings (SC-006)
