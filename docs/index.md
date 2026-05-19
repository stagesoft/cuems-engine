# cuems-engine

**Timecode-driven audio, video, and DMX cueing engine with OSCQuery control.**

[![PyPI - Version](https://img.shields.io/pypi/v/cuemsengine.svg)](https://pypi.org/project/cuemsengine)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/cuemsengine.svg)](https://pypi.org/project/cuemsengine)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

!!! note "Project README"
    For installation instructions, release history, and licensing, see the
    [project README](https://github.com/stagesoft/cuems-engine#readme) on GitHub.

---

## What is cuems-engine?

`cuems-engine` is the Python runtime at the heart of the **CueMS** (Cue Management System).
It synchronises audio, video, and DMX playback across one or more nodes using
**MIDI Timecode (MTC)**, exposing a live control surface over **OSCQuery** and **WebSocket**.

The engine is split into two complementary processes that communicate over **NNG**:

| Process | Role |
|---|---|
| `controller-engine` | Master: owns the cue list, drives the MTC clock, coordinates the node fleet, exposes the editor WebSocket interface |
| `node-engine` | Worker: deploys project assets via rsync, arms and fires audio/video/DMX players as subprocesses, reports status back |

Both processes inherit from a common `BaseEngine` base that owns the asyncio event loop,
OSCQuery lifecycle, MTC listener integration, and the ongoing/next cue pointers.

---

## Signal flow

```
MTC Timecode ──► Controller Engine ──► Cue Dispatch ──► Node Engine ──► Player Lifecycle ──► Output
                       │                                      │                                  │
                 (WebSocket / OSC)                     (NNG transport)               ┌──────────┼──────────┐
                   Editor UI                                                       Audio      Video      DMX
                                                                                  (JACK)  (Gradient)
```

A single `GO` press:

1. **Controller** resolves the current cue pointer, verifies all required nodes are armed, and broadcasts a `COMMAND/GO`.
2. **Node Engine** receives the command, identifies the first local cue in the `post_go='go'` chain, and fires it with a frozen MTC timestamp.
3. **Player subprocesses** start their media aligned to that MTC snapshot; all nodes play in sync regardless of network latency.
4. **Status** flows back over NNG (`armed_ready`, `script_finished`, cue-level events) to update the controller's state machine and the editor UI.

---

## Architecture

### Core layer

[`core/`](core.md) — shared base used by both engines.

- **`BaseEngine`** — abstract engine; owns the asyncio event loop, `ConfigManager`,
  OSCQuery client/server lifecycle, MTC listener, and the ongoing/next cue pointers.
- **`EngineStatus`** — structured data model for engine state.
- **`libmtc`** — MIDI Timecode master helper.

### Communications layer

[`comms/`](comms.md) — NNG-based message transport between controller and nodes.

- **`ControllerCommunications`** — controller-side NNG publisher and WebSocket bridge.
- **`NodeCommunications`** — node-side NNG receiver; dispatches `COMMAND` operations
  and sends `STATUS` replies. Recognises `target='ping'` and replies with
  `target='pong'` for the liveness probe.
- **`AsyncCommsThread`** — asyncio/thread bridge for non-blocking NNG I/O.
- **`NodesHub`** — `NodeOperation` enum and shared data models for the NNG protocol.

### Cues layer

[`cues/`](cues.md) — the unit of show control.

- **`CueHandler`** — singleton managing the armed-cue registry and video player index.
- **`ActionHandler`** — action cue dispatch with a three-phase hook system
  (`before_dispatch`, `after_dispatch`, `wrap_dispatch`). Every failure path returns a
  structured `{status, action_type, target_id, reason}` dict.
- **`arm_cue`** — cue arming workflow: pre-load, readiness checks.
- **`run_cue`** — single-shot playback (audio, video, DMX, fade).
- **`loop_cue`** — loop/multiplay execution with MTC-boundary polling; includes
  `loop_fadeCue` for holding a cue alive for the duration of a gradient fade.
- **`helpers`** — timing utilities (`find_timing`, pre/post-wait calculation).

### Players layer

[`players/`](players.md) — player subprocess management and hardware I/O.

- **`PlayerHandler`** — singleton owning all active players; handles layer routing,
  canvas setup, and OSC communication.
- **`AudioMixer`** — JACK-based audio mixing, routing, and graph validation.
- **`JackConnectionManager`** — JACK port management with self-heal on stale clients.
- **`AudioPlayer`** / **`VideoPlayer`** / **`DmxPlayer`** — subprocess wrappers.
- **`GradientClient`** — fire-and-forget UDP OSC client for `gradient-motiond`;
  uses explicit `int64` for `start_mtc_ms` to avoid truncation above 2³¹ ms.

### OSC / OSCQuery layer

[`osc/`](osc.md) — protocol layer for live parameter control and editor communication.

- **`OssiaNodes`** — Ossia device tree node management.
- **`OssiaClient`** / **`OssiaServer`** — OSCQuery client/server lifecycle wrappers.
- **`WebSocketOscHandler`** — bidirectional WebSocket-to-OSC bridge between the
  show editor and the engine.
- **`PyOsc`** — pure-Python OSC fallback for environments without Ossia.

### Tools layer

[`tools/`](tools.md) — operational utilities used by both engines.

- **`CuemsDeploy`** — async rsync-based project asset deployment; mandatory-file
  precheck, progress streaming, startup (10 s) and inactivity (15 s) watchdog
  timeouts, stale-file cleanup via `--delete`. Non-blocking: rsync runs under
  `asyncio.create_subprocess_exec` on the injected event loop so NNG heartbeats
  continue throughout multi-GB transfers.
- **`MtcListener`** — MIDI Timecode decoder; 24 h rollover detection with a
  two-condition guard that ignores manual seeks back to `00:00:00:00`.
- **`PortHandler`** — dynamic OSC port allocation.
- **`display_conf`** — parses `/run/cuems/display.conf` for per-connector pixel
  regions and optional `canvas_size` override.
- **`system_ports`** — system MIDI port enumeration.

---

## Key design decisions

### Deterministic playback across nodes

All playback boundaries derive from a single MTC reference owned by the
controller. The frozen `mtc_ms` value is captured once at `GO` and threaded
through `ActionHandler` dispatch, player subprocess launch, and the
`loop_fadeCue`/`loop_audioCue`/`loop_dmxCue` MTC-polling loops. Identical
inputs produce identical outputs regardless of transport jitter.

### Cluster liveness and GO gating

At `load_project` time the controller runs a ping/pong liveness probe (1.5 s
window). It intersects three sets — adopted nodes, alive nodes, and nodes
referenced by the current script — to compute `required_nodes`. `armed=yes`
only flips when every required node has sent `armed_ready`. A 120 s stalled-load
watchdog fires an error if any node goes silent mid-rsync.

### Async deployment

`CuemsDeploy.sync_files()` is synchronous at its public boundary but internally
submits an asyncio coroutine to the engine's shared event loop via
`run_coroutine_threadsafe`. The caller blocks on `.result()`; the loop stays
free for NNG heartbeats throughout. An SC-001 integration test verifies ≤ ±20 %
heartbeat jitter during a concurrent multi-GB transfer.

### FadeCue and gradient-motiond integration

`FadeCue` dispatches a `/gradient/start_fade` UDP OSC datagram to
`gradient-motiond` via `GradientClient` (direct localhost UDP, not NNG).
The engine does not poll for fade completion — it seeds `_end_mtc` on the
FadeCue at dispatch time and `loop_fadeCue` holds the cue runner alive by
MTC-polling until the fade duration elapses. The daemon is a pure sink; no
status messages flow back.

---

## API reference

Each module's public API is generated directly from docstrings:

- [Core](core.md) — `BaseEngine`, `EngineStatus`
- [Communications](comms.md) — `AsyncCommsThread`, `ControllerCommunications`, `NodeCommunications`, `NodesHub`
- [Cues](cues.md) — `ActionHandler`, `CueHandler`, `arm_cue`, `run_cue`, `loop_cue`
- [Players](players.md) — `PlayerHandler`, `AudioMixer`, `JackConnectionManager`, player wrappers, `GradientClient`
- [OSC / OSCQuery](osc.md) — `OssiaNodes`, `OssiaClient`, `OssiaServer`, `WebSocketOscHandler`, `PyOsc`
- [Tools](tools.md) — `CuemsDeploy`, `MtcListener`, `PortHandler`, `display_conf`, `system_ports`
