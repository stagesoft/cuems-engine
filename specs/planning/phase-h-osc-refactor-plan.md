<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
SPDX-FileContributor: Ion Reguera <ion@stagelab.coop>
-->

# Phase H — Replace NNG transport with OSC

> Status: **plan, not yet implemented**. Drafted 2026-05-07 by Ion Reguera during the cuems-engine ↔ gradient-motion-engine integration work tracked under ClickUp [869d6vuux](https://app.clickup.com/t/869d6vuux). Awaiting review.

## Background — what's already done (Phases A–G)

This branch (`feat/phase5-systemd-packaging`) carries the Debian packaging skeleton for `gradient-motiond` v0.2.0. On the cuems-engine side, the staging branch `merge/fade-cue-staging` carries:

- **Phase A** — wire-format fixes for PR #12 (Adrià): `target_value`→`end_value` with /100 unit conversion, `start_time`→`start_mtc_ms`, `node_name` injection in `send_fade_command` and `send_cancel_all`. `_handle_fade_action` dispatch signature fix.
- **Phase B** — merge with rc_1 (frozen_mtc_ms threading, 24h MTC rollover, CTimecode rc6 migration, audio-skip-redundant-go).
- **Phase D** — Debian packaging (this branch): control, rules, changelog, copyright, source/format. Builds clean.

Phase E (functional smoke test) **uncovered an architectural break** that Phase H addresses.

## H.0 Context — what Phase E uncovered

`gradient-motiond` never receives `start_fade` messages from NodeEngine, even with the wire format correct and `controller.local` resolving to the right host.

**Empirically verified 2026-05-07** (3-peer NNG bus0 topology test):

| Direction | bus0 in star topology |
|---|---|
| Listener → all dialers | ✓ broadcasts |
| Dialer A → Listener | ✓ direct |
| Dialer A → Dialer B (via Listener) | **✗ does NOT auto-relay** |

The original NNG design ([specs/005-nng-bus-client/research.md Decision 1](../specs/005-nng-bus-client/research.md)) assumed bus0 broadcasts end-to-end ("every node sees every message"). It does not in star topology.

The deeper issue is that gradient-motiond was placed in the wrong CUEMS message plane:

| Plane | Carrier | Members | Direction |
|---|---|---|---|
| **Plane 1: inter-node bus** | NNG bus0 :9093 | Controller, NodeEngine | Cross-machine |
| **Plane 2: local player control** | UDP OSC localhost | AudioPlayer, VideoComposer, DmxPlayer | Same-machine |

`gradient-motiond` is functionally a **Plane-2 player** — runs on each node, receives commands from the local NodeEngine, drives an OSC sink. The other Plane-2 players (audio/video/dmx) all use pure OSC and **do not emit status back**: cue lifecycle (start/end/progress) is emitted by **NodeEngine's `loop_*` functions**, not by the players themselves. See `loop_audioCue` in `cuems-engine/src/cuemsengine/cues/loop_cue.py` lines 95–104 for the dormant progress-emission pattern that anticipates this.

This is why the daemon's `motion_complete`/`motion_error` broadcasts have no consumer: they duplicate what NodeEngine's `loop_fadeCue` already does. Verified by grep — `NodeCommunications._handle_status_operation` (line 106) explicitly discards them with comment "the Python engine no longer mutates state in response to them (general cue lifecycle handles all disarm)". `ControllerEngine.status_operation_callback` (line 423) has a silent guard for `gradientengine_*` senders. The frontend has zero references to fade status/progress.

**Outcome of Phase H**: gradient-motiond becomes a pure OSC-controlled player consistent with the other CUEMS players. NodeEngine's `loop_fadeCue` owns fade lifecycle status (matching `loop_audioCue`/`loop_videoCue`/`loop_dmxCue`). When the planned fade-progress UI feature is built, it gets emission added to `loop_fadeCue` the same way audio/video progress would.

Removes ~600 lines of NNG infrastructure from the daemon, removes `controller.local`/Avahi dependency for the daemon, eliminates the relay/topology problem.

## H.1 Why NNG was chosen, why we're removing it

### Why NNG?

Quoted from [specs/005-nng-bus-client/research.md](../specs/005-nng-bus-client/research.md) Decision 1:

> BUS0 is what every other CUEMS peer on the hub speaks (confirmed by the Python `HubServices.py:217` reference call in the implementation plan). Non-blocking dial is the only way to keep daemon startup independent of hub availability — required by FR-001.
>
> Alternatives considered: REQ/REP or PUB/SUB instead of BUS — rejected, topology mismatch with the rest of the CUEMS ecosystem (NodeEngine, Controller, and NodesHub all speak BUS0).

The "match the ecosystem" reasoning was correct in intent but applied to the wrong plane. NodeEngine and Controller speak bus0 because they are inter-node command-plane peers. Players (audio/video/dmx) speak OSC because they are local-control-plane targets. gradient-motiond is the latter, not the former.

### Why remove now?

1. **Wrong plane.** Daemon belongs in Plane 2 with the other players, not Plane 1.
2. **Topology assumption fails.** bus0 broadcast doesn't reach all dialers in star topology. To make NNG work we'd need to add a relay in the controller, making the controller a message broker and adding ~1–2ms latency.
3. **Vestigial features.** Status broadcasts (`motion_complete`, `motion_error`) are emitted but no Python receiver consumes them (verified). Cue lifecycle is already tracked by `loop_fadeCue`. The status path is dead code.
4. **Avahi dependency.** Daemon dials `controller.local`; that hostname was broken on node-002 (Avahi resolved to a remote IP). Removing the dial removes the dependency entirely — local OSC needs no name resolution.
5. **Code surface.** ~600 lines of `NngBusClient` + `LockFreeQueue` (for thread handoff) + `StatusEmitRequest` infrastructure becomes deletable. Daemon shrinks; oscpack listener pattern is much smaller.

## H.2 Future animation implications

All planned motion types share the same output primitive: **emit N OSC floats to a path at MTC tick rate**. The OSC refactor only changes the **input** transport (how the daemon is told to start a motion). It does **not** change the output side.

| Motion | OSC output | Affected by OSC input refactor? |
|---|---|---|
| FadeMotion (Phase 4, today) | `/volmaster <float>` | No — still works |
| Opacity fade | `/videocomposer/layer/{id}/opacity <float>` | No — same shape |
| `VectorMotion<2>` (planned) — 2D position | `/position <float> <float>` | No — single path, multi-arg OSC |
| `VectorMotion<3>` — RGB color, 3D rotation | `/color <r> <g> <b>` | No — same |
| `VectorMotion<4>` — RGBA, quaternion | `/tint <r> <g> <b> <a>` | No — same |
| Crossfade (Phase 7) | two FadeMotions paired in registry, lockstep OSC sends | No — pairing is internal to daemon registry; one input command triggers two outputs |

**Critical finding**: oscpack supports OSC bundles, which can carry multiple paths atomically — useful for Phase-7 crossfade lockstep updates. NNG had no equivalent semantic.

The motion **input** wire shape is also fine over OSC:

```
/gradient/start_fade <motion_id> <node_name> <osc_host> <osc_port> <osc_path>
                     <start_value> <end_value> <start_mtc_ms> <duration_ms>
                     <curve_type> [<curve_params_json>]
/gradient/start_crossfade <motion_id> <partner_motion_id> ... (Phase 7)
/gradient/start_vector <motion_id> <N> <osc_path> <start_v0> ... <start_vN-1>
                       <end_v0> ... <end_vN-1> ...                    (Phase 8?)
/gradient/cancel_motion <motion_id>
/gradient/cancel_all
```

The argument count grows with vector dimension but stays a single OSC message per command. No semantic loss vs the JSON envelope.

## H.3 Consequences

**Gains**
- Daemon becomes consistent with AudioPlayer/VideoComposer/DmxPlayer pattern (oscpack listener, localhost UDP, one-way commands).
- Removes Plane-1 dependency: no `controller.local`, no NNG dial, no bus topology concerns.
- Lower latency (~1–2 ms saved by skipping bus relay; sub-ms localhost UDP).
- Multi-node correctness improves: each node's daemon only sees its own fades (today's broadcast-and-filter design has every daemon parse every fade just to drop it).
- Deletes ~600 lines of NngBusClient + status emit infrastructure.

**Losses**
- **Daemon's NNG status broadcasts are removed.** Acceptable because:
  - **The pattern is wrong.** Players in CUEMS don't emit status — NodeEngine's `loop_*` functions do, because they're the ones that know the cue lifecycle. AudioPlayer/VideoComposer/DmxPlayer emit no NNG status; only their wrapping `loop_audioCue`/`loop_videoCue`/`loop_dmxCue` does.
  - **The planned fade-progress UI feature lands in NodeEngine, not the daemon.** When implemented, the progress emission goes in `loop_fadeCue` (same place `loop_audioCue` lines 95–104 has commented-out progress code). NodeEngine already knows `_start_mtc` and `_end_mtc` for the fade and can compute progress without the daemon broadcasting anything.
  - No Python receiver consumes daemon status today (verified — `_handle_status_operation` discards at debug level; ControllerEngine `status_operation_callback` has a silent guard for `gradientengine_*`).
  - OSC errors and parse failures get logged in daemon stderr (visible via `journalctl -u cuems-gradient-motiond`).
- **Cross-machine fade dispatch becomes impossible.** Acceptable because:
  - Today's `_build_fade_payload` reads `target_cue._osc.remote_port` from the local target cue. The fade is **already** assumed local (NodeEngine on node-X knows port for player-on-node-X only).
  - Phase 7 crossfade is also single-node (paired motions in one daemon's registry).
  - Synchronized fade across two machines (e.g. left + right video walls) is **not** in scope for any current/planned phase. If needed later, would require a "sync group" coordination layer regardless of NNG vs OSC.
- **Existing daemon code (NngBusClient, ~600 lines) becomes dead.** Sunk cost. We delete it cleanly.

## H.4 Limitations

- The OSC port on the daemon must be known to NodeEngine. Two options:
  - **Hardcoded constant** in `/etc/cuems/settings.xml` under `<gradient_osc_port>` (default 7100, away from videocomposer's 7000 and dmxplayer's per-config). Same pattern as `<oscquery_osc_port>` already in settings.xml.
  - **Per-node discovery** via existing CUEMS Avahi `_cuems_*._tcp` services. Heavier; defer unless we find a reason to need it.
- Per-fade timing precision depends on OSC delivery latency. UDP localhost is sub-millisecond — fine for human-perceptible fades. If sub-frame-accurate audio fades are ever needed (~0.1ms), OSC-then-MTC-aligned execution still works (daemon waits for MTC tick before applying), so this is no worse than today.
- Loss of strict ordering between fade dispatch and other CUEMS messages (NNG bus0 had FIFO over the bus). Mitigated: each fade is independent and MTC-locked, so order across fades doesn't matter as long as each `start_fade` reaches the daemon before its `start_mtc_ms` elapses. UDP packets at <1ms latency easily meet this.

## H.5 Implementation phases

Two repos, two new branches off the current state:
- `cuems-engine`: `feat/gradient-osc-transport` off `merge/fade-cue-staging` (Phase A–B already landed).
- `gradient-motion-engine`: `feat/osc-input-transport` off `feat/phase5-systemd-packaging` (Phase D packaging already landed).

The .deb produced in Phase D will need rebuilding after H.2 — the new daemon binary is the deliverable. Phase G's non-destructive validation procedure still applies.

### H.1a — OSC command schema (write contract first)

File: `cuems-engine/specs/004-gradient-engine-phase6/contracts/` — add `gradient_osc.md` defining:

```
/gradient/start_fade s s s i s f f i f s s
  motion_id, node_name, osc_host, osc_port, osc_path,
  start_value, end_value, start_mtc_ms, duration_ms,
  curve_type, curve_params_json
```

`node_name` filter still applies (daemon drops non-matching). `motion_id` deduplicates and supports cancel.

```
/gradient/cancel_motion s            ; motion_id
/gradient/cancel_all                 ; no args
```

Update `fade_command.json` header to note "JSON envelope retired in Phase H; OSC schema is canonical".

### H.2 — Daemon: replace NngBusClient with OscServer

Files in this repo (`gradient-motion-engine`):

- **DELETE** `daemon/comms/NngBusClient.cpp`, `daemon/comms/NngBusClient.h`
- **DELETE** `src/signal/StatusEmitRequest.h` (status emit no longer needed; daemon-internal logs remain)
- **KEEP** `src/signal/LockFreeQueue.h` — still useful for OSC-thread → tick-thread handoff (oscpack callback runs on a network thread; we want the tick thread to apply)
- **KEEP** `src/signal/FadeCommand.h` `FadeCommand` struct — still the in-memory representation; just parsed from OSC instead of JSON
- **ADD** `daemon/comms/OscServer.cpp/.h` — wraps `oscpack`'s `OscPacketListener` + `UdpListeningReceiveSocket`. Reuse pattern from `cuems-audioplayer/src/oscreceiver/oscreceiver.cpp`.
- **ADD** `src/signal/parseFadeOscCommand.cpp/.h` — parses oscpack `ReceivedMessage` → `FadeCommand` struct. Mirrors the existing JSON parser in `src/signal/FadeCommand.cpp`. Same target/node_name filter, same field validation, same `ParseResult` return type.
- **MODIFY** `src/engine/GradientEngine.cpp`: replace `nngClient_` member with `oscServer_`. `onTick(mtc_ms)` keeps the same shape — drains the lock-free queue, applies, then ticks.
- **MODIFY** `daemon/main.cpp`: drop `--nng-url` flag, add `--osc-port` (default 7100, override via env or settings.xml).
- **MODIFY** `CMakeLists.txt`: link `oscpack` instead of `nng`. Keep `nlohmann/json` for `curve_params_json` (still embedded JSON for curve params).

Build dependency change: `debian/control` Build-Depends drops `libnng-dev`, adds `liboscpack-dev`.

### H.3 — Engine: NodeEngine sends OSC instead of NNG

Files in `cuems-engine`:

- **MODIFY** `src/cuemsengine/comms/NodeCommunications.py`: **DELETE** `send_fade_command` (lines 131–162) and `send_cancel_all` (lines 164–179). The NNG fade path is gone. Keep general NodeOperation send for cue lifecycle (still uses NNG for that).
- **ADD** `src/cuemsengine/players/GradientPlayer.py` — thin OSC client wrapper following `VideoPlayer.py` and `DmxPlayer.py` patterns. Methods:
  - `send_fade(motion_id, node_name, osc_host, osc_port, osc_path, start, end, start_mtc, duration_ms, curve_type, curve_params)`
  - `send_cancel_motion(motion_id)`
  - `send_cancel_all()`
- **MODIFY** `src/cuemsengine/players/PlayerHandler.py`: instantiate `GradientPlayer` alongside other players. Connect to `127.0.0.1:<gradient_osc_port>` from settings.xml.
- **MODIFY** `src/cuemsengine/cues/ActionHandler.py` `_handle_fade_action`: replace `ch.communications_thread.send_fade_command(...)` (line 546) with `ch.player_handler.gradient_player.send_fade(...)`.
- **MODIFY** `src/cuemsengine/ControllerEngine.py`: **DELETE** `_send_gradient_cancel_all` (line 868) and its two call sites (line 773 in `load_project`, line 906 in `stop_script`). Cancel becomes a node-engine concern.
- **MODIFY** `src/cuemsengine/NodeEngine.py`: on STOP and on LOAD, call `self.player_handler.gradient_player.send_cancel_all()`. Local concern, no bus involvement.
- **MODIFY** `etc/cuems/settings.xml` schema (in cuems-utils settings.xsd): add `<gradient_osc_port>` element under `<node>`, default 7100.

### H.4 — systemd unit and Avahi rollback

Files in `cuems-common`:

- **MODIFY** `etc/systemd/system/cuems-gradient-motiond.service`:
  - Drop `--nng-url tcp://controller.local:9093`
  - Add `--osc-port 7100` (or read env `CUEMS_GRADIENT_OSC_PORT`)
  - Drop `Wants=avahi-daemon.service`, `After=...avahi-daemon.service` (no longer needed)
- **REMOVE** the `/etc/systemd/system/cuems-gradient-motiond.service.d/node-uuid.conf` drop-in created during Phase E debugging — the new unit needs neither `--node-name` nor `--nng-url` overrides on this dev box.

The Avahi misconfiguration on node-002 (controller.local resolves to remote 169.254.9.194) becomes irrelevant for the daemon. The broader Avahi issue is documented as a separate follow-up — engine and editor still depend on Avahi for inter-node discovery, but that's out of scope for the gradient daemon refactor.

### H.5 — Tests

- **C++ unit tests** in `gradient-motion-engine/tests/`:
  - `test_osc_parse.cpp` (NEW) — covers OSC `start_fade` / `cancel_motion` / `cancel_all` parsing, malformed messages, missing args, type mismatches. Mirrors existing `test_nng_parse.cpp` for OSC.
  - `test_motion_registry.cpp` — unchanged
  - `test_lockfree_queue.cpp` — unchanged
  - `test_fade_motion.cpp` — unchanged
  - **DELETE** `test_nng_integration.cpp` — no NNG anymore
- **Python unit tests** in `cuems-engine/tests/`:
  - **REWRITE** `test_node_communications_gradient.py` → `test_gradient_player.py`: assert OSC packet emitted on the configured port with correct address+args (use a local OSC listener fixture).
  - **DELETE** OSC contract checks from `test_fade_action_handler.py` that asserted NodeOperation envelope shape — replace with GradientPlayer call assertions.
  - **MODIFY** `test_controller_engine_gradient.py`: drop `_send_gradient_cancel_all` test (function deleted).

### H.6 — Smoke test on node-002

Same project as Phase E — `/opt/cuems_library/projects/fade-test/` (AudioCue + FadeCue, target_value=0, 5s, linear).

1. Restart all services after editable install picks up Python changes:
   ```bash
   sudo systemctl restart cuems-controller-engine cuems-node-engine cuems-gradient-motiond
   ```
2. Confirm daemon listening:
   ```bash
   ss -ulnp | grep 7100   # gradient-motiond OSC listener
   ```
3. Load fade-test in the UI. GO twice. **Listen** — audio should fade smoothly to silence over 5 seconds. No bounce.
4. Capture daemon journal during fade — should see ~100 OSC packets received and forwarded to /volmaster (debug log). No NNG warnings, no `controller.local` references.
5. STOP — daemon receives `/gradient/cancel_all` from local NodeEngine and clears registry.

## H.6 Verification (success criteria for Phase H)

1. **All tests green**:
   - `cd gradient-motion-engine/build && ctest --output-on-failure` — green; new test_osc_parse.cpp passes
   - `cd cuems-engine && poetry run pytest -x` — green; new test_gradient_player.py passes
2. **Wire smoke (Python OSC listener)** — Python test sends `/gradient/start_fade` to daemon's port and confirms ticking by capturing emitted /volmaster packets on a separate listener port. No engine, no controller required.
3. **End-to-end on node-002** — H.6 above: audible 5s fade with no bounce-back. The user's exact failing scenario from Phase E now works.
4. **No NNG dependency** — `ldd gradient-motion-engine/build/gradient-motiond | grep -i nng` returns nothing. `dpkg-deb -I cuems-gradient-motiond_*.deb` Depends list does not contain libnng.
5. **No regressions** — existing audio/video cue playback unchanged. Phases A–G still apply for everything except the NNG transport.
6. **Architectural review** — daemon code follows the same OSC listener pattern as cuems-audioplayer/cuems-videocomposer/cuems-dmxplayer.

## Critical files modified or deleted in Phase H

cuems-engine (`feat/gradient-osc-transport`):
- DELETE: `src/cuemsengine/comms/NodeCommunications.py` `send_fade_command`, `send_cancel_all`
- DELETE: `src/cuemsengine/ControllerEngine.py` `_send_gradient_cancel_all` and call sites
- ADD: `src/cuemsengine/players/GradientPlayer.py`
- MODIFY: `src/cuemsengine/cues/ActionHandler.py` (use GradientPlayer)
- MODIFY: `src/cuemsengine/players/PlayerHandler.py` (instantiate GradientPlayer)
- MODIFY: `src/cuemsengine/NodeEngine.py` (cancel on stop/load)
- MODIFY: `tests/test_node_communications_gradient.py` → `tests/test_gradient_player.py`

gradient-motion-engine (`feat/osc-input-transport`):
- DELETE: `daemon/comms/NngBusClient.{cpp,h}`, `src/signal/StatusEmitRequest.h`, `tests/test_nng_integration.cpp`
- ADD: `daemon/comms/OscServer.{cpp,h}`, `src/signal/parseFadeOscCommand.{cpp,h}`, `tests/test_osc_parse.cpp`
- MODIFY: `src/engine/GradientEngine.cpp` (replace nngClient with oscServer)
- MODIFY: `daemon/main.cpp` (CLI flags)
- MODIFY: `CMakeLists.txt`, `debian/control` (oscpack instead of nng)

cuems-common:
- MODIFY: `etc/systemd/system/cuems-gradient-motiond.service` (CLI args, drop avahi deps)

cuems-utils (settings.xsd):
- MODIFY: add `<gradient_osc_port>` element to node config schema

## H.7 Out of scope for Phase H (deferred)

- **Cross-machine fade dispatch** — not supported today (target cue and fade cue assumed same node). If needed: separate phase introducing a sync-group concept across multiple daemons.
- **Status-back to controller** — removed. If a future UI feature needs fade progress %, it lands in NodeEngine's `loop_fadeCue` (matching the audio/video progress pattern), not in the daemon.
- **Phase 7 crossfade** — same as before; data shape ready, command emit deferred. Phase H makes the emit easier (single OSC `/gradient/start_crossfade`).
- **Avahi misconfiguration on node-002** — fixed for the daemon by removing the dependency. Engine and editor still rely on Avahi; that's a separate task ("fix Avahi on node-002" outside this plan).

## What stays unchanged from Adrià's Phase 0–4 work

The OSC refactor only changes the **input transport**. All of the following stays exactly as designed:

- `IMotion` interface and `FadeMotion` implementation
- `MotionRegistry` (apply, tick, addMotion, cancelMotion, cancelAll, supersede semantics)
- `MotionFactory` (constructs `FadeMotion` from `FadeCommand`)
- `LockFreeQueue<T, N>` (now used for OSC-thread → tick-thread handoff)
- `MtcTickSource` + bundled `mtcreceiver` submodule
- All curve types (`BezierCurve`, `CurveFactory`, JSON params parsing)
- All existing tests for motion logic (test_fade_motion, test_motion_registry, test_lockfree_queue, test_curve_factory)
- The `FadeCommand` struct itself (just constructed from OSC parse instead of JSON parse)
- Phase 7 crossfade preparation (`partner_fade_id` field, paired-evaluation hooks)
- `VectorMotion<N>` design (multi-arg OSC fits perfectly)

The boundary of the change is the recv path in `daemon/comms/`. Everything inside `src/motion/`, `src/signal/`, `src/time/`, `src/gradient/`, `src/osc/` (the OSC sender side) is untouched.
