<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Data Model: Gradient OSC Transport

**Phase**: 1 — design  
**Date**: 2026-05-14  
**Feature**: [spec.md](spec.md)

---

## Entities

### GradientClient

New class in `src/cuemsengine/players/GradientClient.py`.

| Attribute / Method    | Type / Signature                                                                                                  | Notes                                               |
|-----------------------|-------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------|
| `_osc`                | `PyOscClient`                                                                                                     | Fire-and-forget UDP transport                       |
| `_host`               | `str`                                                                                                             | Always `'127.0.0.1'`                                |
| `_port`               | `int`                                                                                                             | From `gradient_osc_port` in settings (default 7100) |
| `_node_uuid`          | `str`                                                                                                             | Held at construction; injected as `node_name` on every `send_fade` |
| `send_fade(...)`      | `(motion_id, osc_host, osc_port, osc_path, start_value, end_value, start_mtc_ms, duration_ms, curve_type, curve_params_json='{}') → None` | Builds OSC msg via `OscMessageBuilder`; type tag `sssisffhiss`. `node_name` is `self._node_uuid` — not a caller argument. |
| `send_cancel_motion(motion_id)` | `(str) → None`                                                                                      | Sends `/gradient/cancel_motion <motion_id>` (type `s`) |
| `send_cancel_all()`   | `() → None`                                                                                                       | Sends `/gradient/cancel_all` (no args)              |

**Constraints**:
- All three public methods MUST catch OSC send errors, log at ERROR level,
  and re-raise so callers can return a `failed` action result (FR-011).
- `send_fade` uses `OscMessageBuilder` directly for type-tag `h` (int64)
  on `start_mtc_ms`; it does NOT use `PyOscClient.send_message` which only
  infers int32.
- `node_name` is NOT a caller argument: `GradientClient` is constructed with
  `node_uuid` (analogous to `VideoClient(player_port=port)`) and self-injects
  it on every `send_fade`. This prevents the daemon from silently dropping
  messages on `NodeMismatch` due to caller-side placeholder values
  (Constitution V — no silent failures).

---

### gradient_osc_port (configuration value)

| Property        | Value                                       |
|-----------------|---------------------------------------------|
| Config path     | `settings.xml → <node> → <gradient_osc_port>` (flat child) |
| Type            | `int` — XSD `cms:NonPrivilegedPort` (1024–65535) |
| Required        | Yes — `cuemsutils >= 0.1.0rc8` declares the element with implicit `minOccurs="1"`. Absence is a settings-load validation error raised by cuemsutils before the engine starts. |
| Fixture value   | `7100` in `dev/test_xml_files/settings.xml` |
| Read by         | `NodeEngine.set_gradient_client()` at node setup — direct dict access (`node_conf['gradient_osc_port']`), no `.get()` fallback |
| Consumed by     | `PlayerHandler.set_gradient_client(port, node_uuid)` |
| Registered with | `PORT_HANDLER` automatically via `get_config_ports(node_conf)` in `NodeEngine.py` (helper collects every `*_port` key) — `set_gradient_client` does NOT call `add_config_ports` |

Flat-child schema rationale: UDP port is the only configurable parameter for
gradient-motion-engine on the engine side; no `path`/`args`/multi-port
distinctions warrant a nested block.

---

### motion_id (correlation key)

| Property        | Value                                                         |
|-----------------|---------------------------------------------------------------|
| Type            | `str`                                                         |
| Format (fade)   | `str(FadeCue.uuid)` for single-endpoint, `str(FadeCue.uuid) + "_{layer_id}"` for video layers |
| Canonical name  | `motion_id` everywhere in Python code (renamed from `fade_id` per FR-013) |
| Daemon usage    | Primary key in `MotionRegistry` on gradient-motiond side     |
| Scope           | Per-motion (fade, future: crossfade, vector)                  |

---

### FadePayload (internal dict, not a class)

Intermediate dict built by `_build_fade_payload`, passed directly to
`GradientClient.send_fade` after unpacking. Keys post-rename:

| Key              | Type    | Wire field     |
|------------------|---------|----------------|
| `motion_id`      | `str`   | `motion_id`    |
| `osc_port`       | `int`   | `osc_port`     |
| `osc_path`       | `str`   | `osc_path`     |
| `start_value`    | `float` | `start_value`  |
| `end_value`      | `float` | `end_value`    |
| `start_mtc_ms`   | `int`   | `start_mtc_ms` |
| `duration_ms`    | `int`   | `duration_ms`  |
| `curve_type`     | `str`   | `curve_type`   |

`node_name` (= `GradientClient._node_uuid`) is injected by `send_fade` itself;
callers do not supply it. `osc_host` (`'127.0.0.1'`) and `curve_params_json`
(`'{}'`) are supplied by `_handle_fade_action` at the call site (defaults).

---

## State Transitions

`GradientClient` has no internal state machine. It is a stateless UDP sender.
All motion lifecycle state lives in `gradient-motiond`'s `MotionRegistry`.

`PlayerHandler._gradient_client` transitions:
- `None` (initial, before NodeEngine setup).
- `GradientClient(host, port, node_uuid)` (after `set_gradient_client` called).
- `GradientClient(host, port', node_uuid)` (after `set_gradient_client` called
  again — prior instance is replaced; this is the reconnection safe-guard).
- Remains set for the lifetime of the node process; no teardown needed —
  `PyOscClient` is fire-and-forget UDP with no held resources.

`gradient-motiond` cleanup transitions (via `GradientClient.send_cancel_all`):
- On STOP (`NodeEngine.stop_playback`): first cleanup action — clears all
  in-flight motions before DMX/video/audio reset.
- On project load (`NodeEngine._load_project_inner`): same — clears motions
  from the previous project before disarm/rearm cycle so no stale fade
  lingers in the daemon's `MotionRegistry`.

---

## Validation Rules

- `osc_port` (gradient port): must be a valid `cms:NonPrivilegedPort`
  (1024–65535). XSD validation in the cuemsutils settings loader enforces
  this — out-of-range and missing values are rejected at load time, not at
  the engine layer.
- `start_value`, `end_value`: must be `float` in `[0.0, 1.0]` (caller
  responsibility; `_build_fade_payload` ensures `end_value` is normalised).
- `motion_id`: non-empty string (caller ensures via `str(cue.id)`).
- `curve_params_json`: defaults to `"{}"` if not supplied; no JSON schema
  validation at the Python layer.
