<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Research: Gradient OSC Transport

**Phase**: 0 — pre-implementation unknowns resolved  
**Date**: 2026-05-14  
**Feature**: [spec.md](spec.md)

---

## Decision 1: OSC type-tag string for `/gradient/start_fade`

**Decision**: `sssisffhiss` (11 arguments)

**Rationale**: Extracted directly from the installed daemon binary with
`strings /usr/bin/gradient-motiond | grep -E '(sss|iff|hiss)'`.
The spec assumption (`sssiffffss`, 10 chars) was wrong in both count and
field types. Daemon is authoritative per spec Assumption §Assumptions.

**Correct field mapping** (0-indexed, type-tag left to right):

| Index | Tag | Field         | Python type to send |
|-------|-----|---------------|---------------------|
| 0     | `s` | motion_id     | `str`               |
| 1     | `s` | node_name     | `str`               |
| 2     | `s` | osc_host      | `str`               |
| 3     | `i` | osc_port      | `int` (int32)       |
| 4     | `s` | osc_path      | `str`               |
| 5     | `f` | start_value   | `float`             |
| 6     | `f` | end_value     | `float`             |
| 7     | `h` | start_mtc_ms  | `int` (int64!)      |
| 8     | `i` | duration_ms   | `int` (int32)       |
| 9     | `s` | curve_type    | `str`               |
| 10    | `s` | curve_params_json | `str`           |

**Critical correction — `h` (int64) for `start_mtc_ms`**: python-osc's
`SimpleUDPClient.send_message` infers type tags from Python types; it maps
`int` → `i` (int32), never `h` (int64). Sending `i` where the daemon
expects `h` will cause liblo to silently discard the message (type-tag
mismatch).

**Implementation consequence**: `GradientClient.send_fade` MUST build the
OSC message using `OscMessageBuilder` with explicit `arg_type='h'` for
`start_mtc_ms`, rather than relying on `PyOscClient.send_message` type
inference. `PyOscClient` can still be used for `send_cancel_all` and
`send_cancel_motion` (no `h` fields in those messages).

**Alternatives considered**:
- Use `PyOscClient.send_message` with automatic type inference — rejected
  because it cannot produce `h` (int64) type tags.
- Extend `PyOscClient` with a typed send method — unnecessary complexity;
  `OscMessageBuilder` is already available from `pythonosc`.

---

## Decision 2: `GradientClient` access pattern in `ActionHandler`

**Decision**: Import `PLAYER_HANDLER` directly in `ActionHandler`; call
`PLAYER_HANDLER.gradient_client.send_fade(...)`.

**Rationale**: The entire codebase uses `PLAYER_HANDLER` (module-level
singleton imported from `players.PlayerHandler`) directly in all action and
run-cue modules — `CueHandler`, `run_cue.py`, `arm_cue.py`, `NodeEngine`.
`CueHandler` has no `player_handler` instance attribute. Introducing one
would break the established pattern without providing any benefit.

FR-006 originally said `ch.player_handler.gradient_client` but the resolved
pattern is `PLAYER_HANDLER.gradient_client` consistent with every other call
site. The test `_make_cue_handler` helper in the test file uses `MagicMock`
which auto-creates any attribute — tests must be updated to patch
`PLAYER_HANDLER` directly (matching how `arm_cue` tests patch it).

**Alternatives considered**:
- Thread `player_handler` through `CueHandler.__init__` — rejected; no
  other attribute is threaded this way; violates existing conventions.

---

## Decision 3: Test migration strategy

**Decision**:
1. `test_node_communications_gradient.py` → **DELETE** in full. All tests
   cover `send_fade_command` / `send_cancel_all` which are removed (FR-007).
   The gradient-engine COMMAND filter tests (`TestGradientEngineCommandFilter`,
   `TestGradientStatusDiscarded`) test `_handle_command_operation` /
   `_handle_status_operation` — these remain valid; move them to
   `test_node_communications.py` (or a new `test_node_communications_gradient_filter.py`)
   rather than deleting them outright.
2. `test_controller_engine_gradient.py` → **PARTIAL UPDATE**. Keep
   `TestGradientEngineSenderGuard` (STATUS sender guard is unchanged).
   Delete `TestSendGradientCancelAll`, `TestStopScriptCancelAllOrder`,
   `TestLoadProjectCancelAllOrder` (FR-008).
3. `test_fade_action_handler.py` → **UPDATE**. Replace all
   `ch.communications_thread.send_fade_command(...)` references with
   `PLAYER_HANDLER.gradient_client.send_fade(...)`. Rename `fade_id` →
   `motion_id` throughout. Update failure test names
   (`test_nng_send_failure_returns_failed` → `test_osc_send_failure_returns_failed`).
4. **NEW**: `tests/test_gradient_client.py` — covers SC-004: `send_fade`
   OSC emission (correct packet structure + type tags), `send_cancel_all`,
   `send_cancel_motion`, error handling, uninitialised-client no-op.

---

## Decision 4: `GradientClient` initialisation in `NodeEngine`

**Decision**: NodeEngine reads `gradient_osc_port` from settings at node
setup time (in the same block that calls `PLAYER_HANDLER.set_video_client()`
and `PLAYER_HANDLER.start_dmx_player()`), then calls
`PLAYER_HANDLER.init_gradient_client(port)`.

**Rationale**: `NodeEngine` already owns all player initialisation.
`PlayerHandler.init_gradient_client(port)` mirrors
`PlayerHandler.set_video_client(port)` and
`PlayerHandler.start_dmx_player(...)`. The port is read from settings XML
once; `GradientClient` is constructed with `host='127.0.0.1'` and the
resolved port.

---

## Cancelled Investigation: `fade_id` rename in ActionHandler tests

All `fade_id` / `entry_fade_id` references in `test_fade_action_handler.py`
and `ActionHandler.py` are in-scope for FR-013. The binary string `fade_id`
does not appear in daemon logs (daemon uses `motion_id` internally); the old
key was only in the NNG JSON envelope which is being removed. Rename is
unambiguously safe.
