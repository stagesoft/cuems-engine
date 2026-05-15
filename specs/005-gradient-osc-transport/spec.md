<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Feature Specification: Gradient OSC Transport

**Feature Branch**: `005-gradient-osc-transport`
**Created**: 2026-05-14
**Status**: Draft

## Context

This feature implements Phase H of the cuems-engine ↔ gradient-motiond integration
plan (see `specs/planning/phase-h-osc-refactor-plan.md`). The `gradient-motiond`
daemon (v0.3.0) already listens on a local UDP OSC port — its NNG input path has
been removed. This spec covers the **cuems-engine side** changes only: replacing
the NNG-over-bus0 dispatch path with direct localhost OSC.

The daemon binary at `/usr/bin/gradient-motiond` is the source of truth for the
OSC wire format. NodeEngine is the sole caller; ControllerEngine's
`_send_gradient_cancel_all` is removed.

## User Scenarios & Testing

### User Story 1 — FadeCue dispatches reach gradient-motiond correctly (Priority: P1)

An operator loads a project containing FadeCue cues (audio fade-out, video opacity
fade). When they press GO, NodeEngine sends a start-fade command to the local
`gradient-motiond` daemon over localhost UDP OSC. The daemon begins the fade and
drives the target player's OSC output smoothly to the target value over the
specified duration.

**Why this priority**: This is the core correctness gate. Without it, all fade cues
are silent failures.

**Independent Test**: A Python test can bind a UDP OSC listener on the gradient
port and verify that pressing GO on a FadeCue causes NodeEngine to emit the correct
`/gradient/start_fade` message with the right arguments. No daemon process needed.

**Acceptance Scenarios**:

1. **Given** a FadeCue targeting an armed AudioCue with a 5s linear fade to 0,
   **When** NodeEngine dispatches the fade action,
   **Then** a `/gradient/start_fade` OSC message is sent to `127.0.0.1:<gradient_osc_port>` containing: the FadeCue uuid as `motion_id`, the node name, `127.0.0.1` as `osc_host`, the AudioCue's OSC port, `/volmaster` as `osc_path`, the current volume as `start_value`, `0.0` as `end_value`, the current MTC position as `start_mtc_ms`, `5000` as `duration_ms`, and `linear` as `curve_type`.

2. **Given** a FadeCue targeting an armed VideoCue with two active layers,
   **When** NodeEngine dispatches the fade action,
   **Then** two `/gradient/start_fade` OSC messages are sent — one per layer — each with the layer-specific `/videocomposer/layer/{id}/opacity` OSC path and a layer-suffixed `motion_id`.

3. **Given** `gradient-motiond` is not running (port unreachable),
   **When** NodeEngine attempts to dispatch a fade,
   **Then** the failure is logged at ERROR level and `_handle_fade_action` returns a `failed` result; no engine crash occurs.

---

### User Story 2 — Cancel-all reaches gradient-motiond on STOP and project load (Priority: P1)

When the operator presses STOP or loads a new project, all in-progress fades are
cancelled on the local daemon. This prevents stale OSC output (e.g. a fade stuck at
mid-volume) from persisting across cue runs.

**Why this priority**: Tied with P1 — a cancel failure leaves audio/video at an
unexpected level between runs.

**Independent Test**: A test can verify that NodeEngine's stop and load paths emit
`/gradient/cancel_all` on the gradient OSC port. ControllerEngine must not emit
cancel (it is not a node-local concern).

**Acceptance Scenarios**:

1. **Given** the engine is running with active fades,
   **When** STOP is received by NodeEngine,
   **Then** `/gradient/cancel_all` is sent to the local daemon before any other stop-cleanup actions.

2. **Given** a new project is being loaded,
   **When** NodeEngine initiates project load,
   **Then** `/gradient/cancel_all` is sent to the local daemon as part of the load-project cleanup sequence.

3. **Given** `ControllerEngine` processes a STOP command,
   **Then** it does NOT send any OSC or NNG message to gradient-motiond — that is NodeEngine's responsibility.

---

### User Story 3 — Daemon port is configurable via settings (Priority: P2)

The operator or system integrator can change the UDP port on which
`gradient-motiond` listens by editing `settings.xml`. The engine reads this value
at startup and uses it for all gradient OSC traffic.

**Why this priority**: Needed for multi-node deployments where port 7100 may
conflict. Also required so the daemon's `--osc-port` flag and the engine's target
port stay in sync via a single config source.

**Independent Test**: A test can set `gradient_osc_port` to a non-default value in
the settings fixture and verify NodeEngine sends gradient OSC to that port.

**Acceptance Scenarios**:

1. **Given** `settings.xml` contains `<gradient_osc_port>7200</gradient_osc_port>` under `<node>`,
   **When** NodeEngine initialises `GradientClient`,
   **Then** all `/gradient/*` messages are sent to port 7200, not 7100.

2. **Given** `settings.xml` does not contain `<gradient_osc_port>`,
   **Then** `GradientClient` defaults to port 7100 and NodeEngine logs the default at INFO.

---

### Edge Cases

- What happens when `_build_fade_payload` raises `ValueError` (e.g. VideoCue with no `_layer_ids`)? The error must propagate as a `failed` `_action_result`; no OSC message is sent.
- What happens if `GradientClient` is not yet initialised when `_handle_fade_action` is called? An `AttributeError` must be caught and logged; the failure result must be returned.
- What happens on multi-layer fade where the first OSC send succeeds but the second fails? The plan specifies: abort remaining dispatches; the partial dispatch is cleared by the next `cancel_all` (on stop/load).
- What if `send_cancel_all` is called before `GradientClient` is initialised (e.g. very early load event)? The call must be a no-op with a DEBUG log; no exception.

## Requirements

### Functional Requirements

- **FR-001**: `GradientClient` MUST send `/gradient/start_fade` over UDP OSC to `127.0.0.1:<gradient_osc_port>` with all fields required by the `gradient-motiond` v0.3.0 OSC contract: `motion_id`, `node_name`, `osc_host`, `osc_port`, `osc_path`, `start_value`, `end_value`, `start_mtc_ms`, `duration_ms`, `curve_type`, `curve_params_json`.

- **FR-002**: `GradientClient` MUST send `/gradient/cancel_motion <motion_id>` to cancel a single in-flight motion by its `motion_id`. **Future-proofing**: No production caller is wired in Phase H — fade cancellation is bulk-only via `cancel_all` on STOP / project load. This method is implemented now to complete the daemon contract surface so that future motion types (vector, crossfade) can target individual motions without revisiting `GradientClient`. Cue-type-specific dispatch logic for per-motion cancel will be added by the feature that introduces that motion type.

- **FR-003**: `GradientClient` MUST send `/gradient/cancel_all` (no arguments) to cancel all in-flight fades on the daemon.

- **FR-004**: `NodeEngine` MUST call `gradient_client.send_cancel_all()` when processing a STOP command, before other stop-cleanup actions.

- **FR-005**: `NodeEngine` MUST call `gradient_client.send_cancel_all()` when initiating a project load, before clearing other player state.

- **FR-006**: `ActionHandler._handle_fade_action` MUST replace the `ch.communications_thread.send_fade_command(...)` call with `PLAYER_HANDLER.get_gradient_client().send_fade(...)`, accessing the singleton directly via the `get_gradient_client()` method (parity with `get_video_client()` / `get_dmx_player_client()`; `PLAYER_HANDLER` is imported at module level in every action / run-cue module). `node_name` is NOT a caller argument: `GradientClient` is constructed with `node_uuid` and injects it on every send.

- **FR-007**: `NodeCommunications.send_fade_command` and `NodeCommunications.send_cancel_all` MUST be deleted; gradient commands MUST NOT travel over the NNG bus.

- **FR-008**: `ControllerEngine._send_gradient_cancel_all` and its two call sites (in `load_project` and `stop_script`) MUST be deleted.

- **FR-009**: `PlayerHandler` MUST expose a `gradient_client` attribute (a `GradientClient` instance) initialised at node setup time, following the same pattern as `_dmx_player_client` and `_video_client`. Access via `PlayerHandler.get_gradient_client()` and construction via `PlayerHandler.set_gradient_client(port, node_uuid)` — naming parity with `set_video_client(port)` / `get_video_client()`. `NodeEngine` MUST expose a dedicated `set_gradient_client(self)` method called from the same setup orchestrator that invokes `set_video_players` / `set_dmx_players`, and MUST register the port via `PORT_HANDLER.add_config_ports({'gradient_motiond': port})` for parity with every other player subsystem. Re-calling `set_gradient_client` replaces the prior client (reconnection safe-guard).

- **FR-010**: The engine-side `settings.xml` **parser** MUST accept an optional `<gradient_osc_port>` integer element under `<node>`, defaulting to 7100 when absent. The XSD lives in the external `cuems-utils` repo; the test fixture `dev/test_xml_files/settings.xml` is updated as part of this feature. If validation against the published XSD fails because `cuems-utils` has not yet shipped the schema update, the affected test(s) MUST be marked as expected-to-fail (`pytest.mark.xfail` / `skip`) with a TODO referencing the external dependency, until the schema is published — engine-side acceptance is the deliverable here.

- **FR-011**: All dispatch failures (OSC send errors, uninitialised player) MUST be logged at ERROR level and returned as `failed` action results; they MUST NOT raise unhandled exceptions in the calling thread.

- **FR-012**: The existing `test_node_communications_gradient.py` MUST be replaced by `test_gradient_client.py` which asserts correct OSC packet emission on the configured port. `test_controller_engine_gradient.py` assertions for `_send_gradient_cancel_all` MUST be removed.

- **FR-013**: All Python identifiers named `fade_id` or `entry_fade_id` MUST be renamed to `motion_id` / `entry_motion_id` throughout the codebase — including function parameters, local variables, dict keys, log message format strings, and test fixtures. This applies to `ActionHandler._handle_fade_action`, `ActionHandler._build_fade_payload`, and any test code that references the field. Rationale: `motion_id` is the daemon's canonical identifier for any in-flight motion (fade today, vector/crossfade in future phases); using fade-specific naming locally creates drift between the wire contract and Python identifiers. Cue-type-specific names (`FadeCue`, `fade_action`, `_handle_fade_action`, `_build_fade_payload`, `send_fade`) are NOT in scope for this rename — they remain fade-specific because they handle fade-specific business logic.

### Key Entities

- **GradientClient**: A new OSC client class in `src/cuemsengine/players/GradientClient.py`. Wraps `PyOscClient` (`src/cuemsengine/osc/PyOsc.py`) for fire-and-forget UDP OSC sends — no pyossia device, no endpoint registration, no local port allocation, no subprocess management (`gradient-motiond` is a systemd service). Constructed with `(host, port, node_uuid)` analogous to `VideoClient(player_port=port)`; holds `node_uuid` and injects it as `node_name` on every `send_fade` (callers do not pass it). Exposes `send_fade(...)`, `send_cancel_motion(motion_id)`, `send_cancel_all()`.

- **gradient_osc_port**: An integer configuration value, a **flat child of `<node>`** in `settings.xml` (not nested under a `<gradient_motiond>` block — it is the only configurable parameter for gradient-motion-engine on the engine side). Default 7100, sourced from `GRADIENT_OSC_PORT_DEFAULT` defined in `NodeEngine.py`. Read by `NodeEngine.set_gradient_client()` at startup and passed to `PlayerHandler.set_gradient_client(port, node_uuid)`.

- **motion_id**: The daemon's canonical correlation key for an in-flight motion. For Phase H (fade only), the value is the `FadeCue.uuid` as a string, optionally with a `_{layer_id}` suffix for per-layer video fades. Future motion types (vector, crossfade) will populate the same field with their own cue's UUID, allowing `cancel_motion(motion_id)` and any future motion-generic OSC paths to operate uniformly. Replaces the previous `fade_id` identifier everywhere in the Python codebase (see FR-013).

- **OSC wire contract**: Defined in `specs/005-gradient-osc-transport/contracts/gradient_osc.md` (created as part of this feature). Documents the `/gradient/start_fade` type-tag string and field order that `gradient-motiond` v0.3.0 expects. Serves as the canonical reference for both the Python sender and any future tests.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A FadeCue GO on a live node results in a smooth, continuous fade of the target audio or video player over the specified duration, with no bounce-back at the end. Verified by human ear/eye on node-002 (`fade-test` project, 5s linear fade to 0).

- **SC-002**: After STOP, audio volume returns to its pre-fade level within one cue re-arm cycle. There are no stale fade commands active in the daemon between runs.

- **SC-003**: `ldd /usr/bin/gradient-motiond | grep -i nng` returns nothing; the daemon binary has no NNG linkage. (Already true for v0.3.0 — this criterion validates the engine side does not re-introduce NNG for gradient traffic.)

- **SC-004**: `poetry run pytest tests/test_gradient_client.py -v` passes with all 8 of: (1) `/gradient/start_fade` address; (2) `,sssisffhiss` type-tag string; (3) `motion_id` at position 0; (4) constructor-supplied `node_uuid` injected at position 1 (`node_name`); (5) `start_mtc_ms` `h` (int64) tag round-trips values exceeding int32 range; (6) `/gradient/cancel_all` emission with no args; (7) `/gradient/cancel_motion` emission with `motion_id`; (8) OSC send error logged at ERROR and re-raised.

- **SC-005**: `poetry run pytest -x` (full suite) passes with no regressions in audio/video/DMX cue tests.

- **SC-006**: The engine log contains no `gradientengine` NNG routing errors or `controller.local` resolution warnings during a fade-test run on node-002.

## Assumptions

- `gradient-motiond` v0.3.0 is already installed at `/usr/bin/gradient-motiond` and listens on the configured UDP OSC port (default 7100). The daemon side of Phase H is complete; this spec covers the engine side only.
- The OSC type-tag string for `/gradient/start_fade` is `sssisffhiss` (11 args), verified against `/usr/bin/gradient-motiond` (v0.3.0) on 2026-05-14. Field order: `motion_id`(s), `node_name`(s), `osc_host`(s), `osc_port`(i — int32), `osc_path`(s), `start_value`(f), `end_value`(f), `start_mtc_ms`(**h — int64**), `duration_ms`(i — int32), `curve_type`(s), `curve_params_json`(s). The `h` (int64) tag on `start_mtc_ms` requires `OscMessageBuilder` with explicit `arg_type='h'` — python-osc's `SimpleUDPClient.send_message` type inference maps `int` → `i` (int32) only and would cause silent daemon-side drops. See `contracts/gradient_osc.md` for the full wire contract.
- `GradientClient` wraps `PyOscClient` (`src/cuemsengine/osc/PyOsc.py`, `python-osc 1.9.3` already in `pyproject.toml`). It does NOT extend `PlayerClient` (pyossia): pyossia's `set_value()` pushes one typed value per registered endpoint, whereas `/gradient/start_fade` requires 11 individually typed arguments in a single OSC message — packing them as `ValueType.List` would lose the per-argument type tags the daemon's oscpack parser requires.
- Per-node correctness: each NodeEngine instance only drives its own local daemon. Cross-machine fade dispatch is out of scope.
- The settings XSD lives in the `cuems-utils` repo; changes to it are tracked there and referenced here as a dependency. The `dev/test_xml_files/settings.xml` in this repo is updated as a test fixture.
- `curve_params_json` defaults to `"{}"` (empty JSON object string) when no curve parameters are specified.

## Clarifications

### Session 2026-05-14

- Q: Should `GradientClient` use `PyOscClient` (python-osc `SimpleUDPClient`) or extend `PlayerClient` (pyossia) for OSC transport? → A: `PyOscClient` — pyossia's per-endpoint `set_value()` cannot send 11 individually typed OSC arguments without packing them as a list (which breaks the daemon's oscpack type-tag expectations); `python-osc 1.9.3` is already a declared dependency.
- Q: Should `send_cancel_motion(motion_id)` be P1 scope (implement and test now) or deferred to Phase 7? → A: Implement now — completes daemon contract coverage while the wire format is being established; thin implementation cost.
- Q: Should this feature introduce a single `GradientClient` class or a `GradientPlayer` + `GradientClient` split (as per DmxPlayer/DmxClient)? → A: Single `GradientClient` — `gradient-motiond` is a systemd service; no subprocess management is needed. A vestigial `GradientPlayer` wrapper would repeat the unused `VideoPlayer` pattern.
- Q: Should all existing `fade_id` references in the Python codebase be renamed to `motion_id` to align with the daemon's motion-generic identifier semantic? → A: Yes — `motion_id` is the canonical correlation key for any in-flight motion (fade now, vector/crossfade later); fade-specific names (`FadeCue`, `_handle_fade_action`, `send_fade`) stay fade-specific because they encode fade-specific business logic, but identifiers that name the in-flight motion are renamed. Captured as FR-013.

### Session 2026-05-15

Post-`/speckit-analyze` startup-pattern parity refinements (the engine-side gradient client must boot equivalently to `VideoClient`/`VideoPlayer`):

- Q: Should the `PlayerHandler` constructor method be `init_gradient_client` or `set_gradient_client`? → A: `set_gradient_client(port, node_uuid)` — naming and signature parity with the existing `set_video_client(port)`. Method-only access via `get_gradient_client()`, no `@property`.
- Q: Where should `GRADIENT_OSC_PORT_DEFAULT` live? → A: As a module-level constant in `NodeEngine.py`, alongside `VIDEOCOMPOSER_OSC_PORT_DEFAULT`.
- Q: Should `NodeEngine.set_gradient_client()` register its port with `PORT_HANDLER`? → A: Yes — `PORT_HANDLER.add_config_ports({'gradient_motiond': port})`, for parity with every other player subsystem.
- Q: Where does `node_name` come from in the wire payload? → A: `GradientClient` is constructed with `node_uuid` (analogous to `VideoClient(player_port=port)`) and self-injects it on every `send_fade`. Callers do not pass `node_name`. Prevents silent daemon-side `NodeMismatch` drops from caller-side placeholder values.
- Q: Settings schema — flat `<gradient_osc_port>` under `<node>`, or nested under `<gradient_motiond>`? → A: Flat — UDP port is the only configurable parameter for gradient-motion-engine on the engine side; a nested block would be a one-element pseudo-namespace.
- Q: Is `set_gradient_client` safe to call multiple times? → A: Yes — any new call replaces the prior client (reconnection safe-guard). No teardown needed; `PyOscClient` is fire-and-forget UDP with no held resources.
- Q: Does project unload (`_load_project_inner`) call `cancel_all`? → A: Yes — first cleanup action, before `CUE_HANDLER.stop_all_cues`, to free any lingering motions in the daemon before the new project loads (FR-005).
- Q: Should FR-006's `ch.player_handler.gradient_client` indirection be kept? → A: No — replace with direct `PLAYER_HANDLER.gradient_client` singleton access, matching every existing action / run-cue module.
