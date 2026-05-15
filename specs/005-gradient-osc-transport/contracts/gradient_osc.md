<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# OSC Wire Contract: gradient-motiond v0.3.0

**Source of truth**: `/usr/bin/gradient-motiond` (installed binary, Phase H)  
**Verified**: 2026-05-14 via `strings /usr/bin/gradient-motiond`  
**Transport**: UDP, localhost only (`127.0.0.1`)  
**Default port**: 7100 (configurable via `<gradient_osc_port>` in settings.xml)

---

## `/gradient/start_fade`

Instructs the daemon to begin a smooth fade motion on a remote OSC endpoint.

**Type-tag string**: `sssisffhiss`

| Position | Tag | Field             | Python type     | Example                              |
|----------|-----|-------------------|-----------------|--------------------------------------|
| 0        | `s` | motion_id         | `str`           | `"3fa85f64-5717-4562-b3fc-2c963f66afa6"` |
| 1        | `s` | node_name         | `str`           | `"node-002"`                         |
| 2        | `s` | osc_host          | `str`           | `"127.0.0.1"`                        |
| 3        | `i` | osc_port          | `int` (int32)   | `12300`                              |
| 4        | `s` | osc_path          | `str`           | `"/volmaster"`                       |
| 5        | `f` | start_value       | `float`         | `0.85`                               |
| 6        | `f` | end_value         | `float`         | `0.0`                                |
| 7        | `h` | start_mtc_ms      | `int` (int64)   | `30000`                              |
| 8        | `i` | duration_ms       | `int` (int32)   | `5000`                               |
| 9        | `s` | curve_type        | `str`           | `"linear"`                           |
| 10       | `s` | curve_params_json | `str`           | `"{}"`                               |

**CRITICAL**: `start_mtc_ms` uses OSC type tag `h` (int64 / 64-bit signed
integer). python-osc's automatic type inference maps Python `int` → `i`
(int32). Senders MUST use `OscMessageBuilder` with explicit `arg_type='h'`
for this field; passing an `int` through `SimpleUDPClient.send_message`
will send `i` (int32), which liblo discards silently on type-tag mismatch.

**Supported `curve_type` values** (from binary):
- `"linear"` — constant rate
- `"scurve"` — S-curve (ease in + ease out)
- `"ease_in"` — accelerating
- `"ease_out"` — decelerating
- `"sigmoid"` — logistic curve
- `"bezier"` — cubic Bézier (params in `curve_params_json`)

**`curve_params_json`**: JSON object string. Use `"{}"` for curves that
take no parameters. For `"bezier"`, specify control points (daemon-defined
schema). The Python sender always defaults to `"{}"` unless the caller
provides curve-specific params.

**Daemon response**: None. Fire-and-forget UDP. The daemon logs its own
`START_FADE` / `CANCEL_MOTION` events internally. There is no OSC reply.

**Duplicate `motion_id`**: The daemon's `MotionRegistry` cancels any
existing motion with the same `motion_id` before starting the new one
(implicit idempotency).

---

## `/gradient/cancel_motion`

Cancels a single in-flight motion by its `motion_id`.

**Type-tag string**: `s`

| Position | Tag | Field     | Python type | Example                              |
|----------|-----|-----------|-------------|--------------------------------------|
| 0        | `s` | motion_id | `str`       | `"3fa85f64-5717-4562-b3fc-2c963f66afa6_2"` |

This message is motion-generic: it works for any motion type (fade today;
crossfade, vector in future phases). `cancel_motion` is NOT removed when
future motion types are added.

---

## `/gradient/cancel_all`

Cancels all in-flight motions on the daemon. No arguments.

**Type-tag string**: `` (empty)

Sent by `NodeEngine` on STOP and project load (FR-003, FR-004, FR-005).
This is the primary cleanup mechanism; individual `cancel_motion` calls
are not required before `cancel_all`.

---

## Python Sender Implementation Notes

`GradientClient` holds `node_uuid` at construction (set by
`PlayerHandler.set_gradient_client(port, node_uuid)`); `node_name` is injected
by `send_fade` itself, not passed by callers. This prevents placeholder
values from causing silent daemon-side `NodeMismatch` drops.

```python
# GradientClient.send_fade (the only place this builder runs):
from pythonosc.osc_message_builder import OscMessageBuilder

builder = OscMessageBuilder(address='/gradient/start_fade')
builder.add_arg(motion_id,         arg_type='s')
builder.add_arg(self._node_uuid,   arg_type='s')   # node_name — self-injected
builder.add_arg(osc_host,          arg_type='s')
builder.add_arg(osc_port,          arg_type='i')
builder.add_arg(osc_path,          arg_type='s')
builder.add_arg(float(start_value),arg_type='f')
builder.add_arg(float(end_value),  arg_type='f')
builder.add_arg(int(start_mtc_ms), arg_type='h')   # h = int64 — REQUIRED
builder.add_arg(int(duration_ms),  arg_type='i')
builder.add_arg(curve_type,        arg_type='s')
builder.add_arg(curve_params_json, arg_type='s')
msg = builder.build()
self._osc.client.send(msg)   # SimpleUDPClient.send(OscMessage)

# cancel_motion — one string arg; PyOscClient.send_message is fine
self._osc.send_message('/gradient/cancel_motion', motion_id)

# cancel_all — no args; pass empty list
self._osc.send_message('/gradient/cancel_all', [])
```

`self._osc.client` is the underlying `SimpleUDPClient`. For `cancel_motion`
and `cancel_all`, `PyOscClient.send_message` is used directly (no explicit
type tags needed — `s` is inferred correctly for `str`).
