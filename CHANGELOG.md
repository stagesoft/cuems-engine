# Changelog

## v0.1.0rc2 — 2026-05-19

Major feature release. Adds FadeCue integration with `gradient-motiond`, direct UDP OSC
gradient transport (replacing NNG), cluster liveness probing, multi-node GO gating,
async rsync deployment, display.conf canvas geometry, and per-cue custom video canvas
regions. Fixes a raft of deploy regressions, multi-node chain sequencing issues, and
MTC-related timing hazards from the rc1 baseline.

### Added

#### FadeCue — smooth OSC-parameter fades via gradient-motiond (Phase 6)

- New `fade_action` action type registered in `ActionHandler.SUPPORTED_CUE_ACTIONS`.
- `_handle_fade_action` arms the target cue if needed, reads the live start value from
  the target's Ossia cache, builds a fade payload via `_build_fade_payload`, and dispatches
  it to `gradient-motiond`. Sets `_start_mtc` / `_end_mtc` on the FadeCue so
  `loop_fadeCue` can hold the cue runner for the full duration.
- `_build_fade_payload` returns a `list[dict]`: one entry for `AudioCue`
  (`/volmaster` on the player's OSC port), N entries for `VideoCue` (one per
  `_layer_ids`, port 7000, `/videocomposer/layer/{layer_id}/opacity`).
- `loop_fadeCue` registered in `loop_cue.py`: 20 ms MTC poll until
  `cue._end_mtc` elapses, honours `_stop_requested`.
- `CueHandler` pre-arm rule extended to cover `action_type='fade_action'` alongside
  `'play'`, eliminating arm latency at FadeCue fire time.
- `FadeCue` inherits `run_actionCue` via singledispatch MRO (no dedicated `run` branch
  needed per spec FR-020).

#### GradientClient — direct UDP OSC transport to gradient-motiond

- New `src/cuemsengine/players/GradientClient.py`: fire-and-forget UDP OSC client
  wrapping `OscMessageBuilder` / `PyOscClient`. Exposes `send_fade()`,
  `send_cancel_motion()`, `send_cancel_all()`. Uses explicit `arg_type='h'` (int64)
  for `start_mtc_ms` to avoid silent `int32` truncation above 2³¹ ms (~25 days of MTC).
- `PlayerHandler` gains `get_gradient_client()` / `set_gradient_client(port, node_uuid)`.
- `NodeEngine.set_gradient_client()` reads `gradient_osc_port` from `node_conf` and wires
  it into `PlayerHandler` via `set_players()`.
- `NodeEngine.stop_playback()` and `_load_project_inner()` call `send_cancel_all()` before
  `stop_all_cues()`, clearing in-flight daemon motions before cue threads are torn down.

#### Cluster liveness probe and GO gating (Controller)

- `ControllerEngine` broadcasts a `COMMAND/UPDATE/target=ping` on every `load_project`
  and collects `STATUS/UPDATE/target=pong` replies with a 1.5 s `threading.Event` wait.
- At load time, three sets are intersected to compute `required_nodes`:
  `adopted_nodes` (network_map.xml) ∩ `alive_nodes` (ping respondents) ∩
  `project_nodes` (UUIDs referenced by cues in the current script). The controller's
  own UUID is always included.
- `armed=yes` only flips when `_armed_nodes >= _required_nodes` — the GO button is
  blocked until every required node reports `armed_ready`. Per-node arrivals are
  logged as "Node {uuid} armed (M/N)".
- Four-category load-time logging per adopted node:
  alive + in project (tracked silently), alive + not in project (`INFO`),
  offline + required (`ERROR`, GO blocked), offline + unused (`WARNING`).
- `NodeCommunications` recognises `target='ping'` in the COMMAND handler and
  replies immediately with a `STATUS/target='pong'` carrying the node's own UUID
  (fire-and-forget via `asyncio.create_task`).
- Stalled-load watchdog: a 120 s `threading.Timer` fires if `armed_ready` never
  accumulates to cover `required_nodes`, logging an ERROR listing the pending UUIDs.
  Cancelled on armed success or `_clear_playback_state`. Daemon timer so it cannot
  keep the engine alive on shutdown.

#### Display.conf canvas geometry

- New `cuemsengine.tools.display_conf` (moved from root): `read_display_conf` parses
  `/run/cuems/display.conf` (written by `cuems-videocomposer` ExecStartPre) with a
  preamble pre-pass so global keys (`canvas_layout`, `canvas_size`) are not silently
  dropped. Returns a per-connector pixel-region map and the implied virtual canvas size.
  Raises `DisplayConfNotFoundError` (missing file / no `[output:*]` sections) and
  `DisplayConfValueError` (malformed `canvas_size`, override smaller than bbox).
- `canvas_size=WIDTHxHEIGHT` override propagated end-to-end: `read_display_conf` →
  `NodeEngine.set_video_outputs` → `PlayerHandler.start_video_outputs` via
  `canvas_override`. `PlayerHandler` logs `Canvas: WxH (bbox=...)` at INFO.

#### Per-cue custom video canvas regions

- `VideoCueOutput` can now carry a `<uuid>_custom_<n>` output name with an inline
  `canvas_region` (normalised floats in [0, 1]).
- `PlayerHandler` gains `make_custom_video_output()` (converts normalised coords
  to pixels using the cached alias canvas totals), `resolve_video_output_for_cue()`,
  and a `node_uuid` property. `add_node_uuid()` is now wired from
  `NodeEngine.set_video_players()`.
- `arm_videoCue` and `run_videoCue` delegate to `resolve_video_output_for_cue` instead
  of branching inline; catch-all except split into expected (KeyError / RuntimeError /
  ValueError → WARNING) and unexpected (Logger.exception, ERROR with traceback).

#### Audio mixer improvements

- `AudioMixer.player_connections_correct()`: verifies the player's outports are wired
  exactly as `connect_player_to_outputs` would wire them; returns False for missing
  ports, missing edges, or wrong destinations. Used to skip redundant reconnects.
- `ControllerEngine` broadcasts mixer volume state on `/realtime`:
  `/engine/status/audio/mixer/{node_uuid}/{output_index}/{channel}/volume` on every
  UI mixer write; newly connected `/realtime` clients receive a full state dump.
- `ControllerEngine` registers a UI OSC handler for every adopted node.

#### Async CuemsDeploy — non-blocking rsync (US1–US4)

- `CuemsDeploy.sync_files()` public API is unchanged (synchronous, blocking) but the
  rsync subprocess now runs under `asyncio.create_subprocess_exec` with two
  `_pump(stream, tag, queue)` coroutines on the injected event loop, keeping the NNG
  heartbeat loop free throughout multi-GB transfers.
- `_deploy_all_async()` owns the precheck → log-creation → sync flow. Returns False
  without touching the log file when precheck fails.
- Watchdog state machine: `asyncio.wait(pending, timeout=…)` with the queue drained
  before evaluating `not done`, and `pending` threaded through return values so
  completed pump tasks are never re-awaited.
- `_kill` and `_check_mandatory_sources` converted to `async def`.
- `sync_files()` gains a `self.loop is None` fast-fail guard (logs error, returns False).
- `--delete` and `--delete-delay` added to `_sync` rsync command so destination nodes
  remove files absent from the new project after each successful transfer.
- `_media_files(bare_names)` helper: expands bare filenames to `media/<name>` entries
  plus `media/indexes/<name>.idx` sidecars for video extensions (`.mp4 .mov .avi .mkv
  .mpg`). `sync_files(tag='media')` auto-expands bare names via this helper.
- `_RSYNC_PASSWORD` extracted as `ClassVar[str]`; the literal appears exactly once.
- `NodeEngine.deploy_media()` passes bare names directly to `sync_files`; path
  expansion is now centralised in `CuemsDeploy`.

---

### Changed

- **OSC gradient transport**: replaced NNG-over-bus0 gradient dispatch with direct
  localhost UDP OSC via `GradientClient`. Eliminated the `gradientengine` NNG routing
  errors on multi-node clusters after the bus0 topology change in v0.3.0. Wire
  contract: `/gradient/start_fade` with type-tag `,sssisffhiss`.
- **NNG gradient guards removed**: `gradient-motiond` (v0.3.0+) is a pure sink — it
  never sends messages back to the engine. Removed `_handle_status_operation`,
  `OperationType.STATUS` receive-callback, the `target="gradientengine"` COMMAND
  guard from `NodeCommunications`, and the `sender.startswith("gradientengine_")`
  guard from `ControllerEngine.status_operation_callback`. Deleted the corresponding
  test files (`test_node_communications_gradient_filter.py`,
  `test_controller_engine_gradient.py`).
- **`_handle_fade_action` signature**: all handler signatures now take
  `(ch, action_cue, target, mtc, frozen_mtc_ms=None)` so the FadeCue and the
  resolved target are always available as separate arguments.
- **`display_conf.py` relocated** from `src/cuemsengine/` to
  `src/cuemsengine/tools/` alongside other operational utilities.
- **CTimecode hardening** (`cuemsutils` pinned to `0.1.0rc8`): every `.milliseconds`
  call-site migrated to `.milliseconds_rounded` (int, used for sleep durations,
  polling comparisons, OSC bundle args) or `.milliseconds_exact` (float, used for
  `BaseEngine.go_offset`). Affected files: `NodeEngine`, `BaseEngine`, `CueHandler`,
  `loop_cue`, `run_cue`, `helpers`, `MtcListener`.

---

### Fixed

#### Multi-node sequencing

- **Pre-arm walks chain to first LOCAL cue** (`BaseEngine.initial_cuelist_process`):
  `initial_cuelist_process` now walks the `post_go='go'` chain to find the first cue
  local to this node before pre-arming, instead of skipping pre-arm entirely when the
  first cue belongs to a peer node.
- **Walk post_go chain past non-local cues at GO** (`NodeEngine.go_script`): GO now
  walks `_target_object` forward until a local cue is found or the chain ends
  (`post_go != 'go'`), so the node fires its own first local cue in parallel with the
  controller's intro cue from the same GO press.
- **Skip non-local cues in `CueHandler.go()`** to keep the post_go chain alive for
  multi-node setups.

#### Deploy

- **Controller IP from `network_map`** instead of hardcoded `localhost` / avahi.
  `CuemsDeploy` is now constructed with the controller IP resolved at `BaseEngine.set_cm()`
  time. Marks `self.enabled = False` when no IP is available.
- **`deploy_project` runs before teardown**: `_load_project_inner` now deploys
  `script.xml` / `mappings.xml` / `settings.xml` as the *first* action, before stopping
  cues or resetting players. On failure the node returns False with no state torn down.
  `deploy_media` remains best-effort.
- **rsync log moved to `/run/cuems/rsync.log`** from `/tmp/` to avoid cross-uid
  ownership conflicts when multiple processes create the file.
- **Tolerate missing optional project files** via `--ignore-missing-args`; only
  `script.xml` is mandatory. Non-fatal missing files no longer abort the deploy.
- **Normalise newlines in rsync files-from** and prefix media paths correctly.
- **Preserve mtime with `-rt`**: without `-t`, rsync stamps receiver mtime to "now"
  on every transfer. This invalidates the `.idx` video index cache (forcing a
  3-pass reindex, ~5 s for a 4 GB clip) and causes unnecessary delta-checksums on
  subsequent loads. Fixed with `-rt`; all three outputs on a displayconf-test load
  in < 1 s as cache hits.
- **Streaming rsync supervision** (pre-async): replaced `subprocess.run(timeout=15)`
  with `subprocess.Popen` + `selectors`-driven stream consumption; dual watchdog:
  10 s startup deadline + 15 s inactivity threshold. Removed the total 15 s wall-clock
  cap that silently killed legitimate multi-GB media syncs.
- **rsync timeouts and disabled-state guard**: `--contimeout=2`, `--timeout=5`, and a
  Python-level `subprocess.run(timeout=15)` backstop. `sync_files()` short-circuits to
  False when `CuemsDeploy.enabled` is False.

#### MTC

- **24h MTC rollover false-positive fix** (`MtcListener`): the rollover detector now
  requires *both* a backward delta > 1 h *and* `prev_frames > frames_per_24h - frames_per_hour`
  to count as a true wrap. A manual reset from > 1 h back to 00:00:00:00 no longer
  accumulates a phantom +2,160,000-frame offset that caused video layers to seek to
  negative frame positions.

#### Audio

- **JACK self-heal** (`JackConnectionManager`): on `jack.JackError`, closes the stale
  client, re-initialises on next access, and retries the connect/disconnect once.
  The manager is now self-healing across jackd graph resets — no engine restart required.
- **Skip redundant mixer connect at GO**: `run_audioCue` now skips
  `connect_player_to_outputs` when `player_connections_correct()` returns True (the
  common path after arm). Eliminates 21–28 ms latency at GO that clipped the first
  samples. Degraded graph case still repairs via `connect_player_to_outputs`.
- **Kill orphaned audio player before re-arm** and fix port release ordering to prevent
  stale port registrations.
- **Fix double volume conversion** in real-time cue routing.

#### Video

- **Restore per-output canvas layout**: aliases without an explicit `canvas_region` in
  `default_mappings.xml` now receive a 1920×1080 side-by-side default in XML order
  instead of all mapping to the same region. `PLAYER_HANDLER.add_node_uuid()` is now
  called from `NodeEngine.set_video_players()` (was never invoked previously), fixing
  silent custom-cue fallback.

#### Actions

- **Structured error returns for all bare `ch.arm/go/disarm` calls**: introduces
  `_ready_action_target(action, target, ch)` as a module-level helper centralising
  the enabled → arm (try/except) → loaded-after-arm pre-flight for `_handle_play`,
  `_handle_fade_in`, `_handle_go_to`, and `_handle_fade_action`. `ch.go()` in
  `_handle_fade_in` and `ch.disarm()` in `_handle_stop` are now wrapped with
  try/except. All failure paths return a clean `{status: "failed", action_type,
  target_id, reason}` dict instead of propagating bare exceptions.
- **`ensure_video_indexes` subprocess failures surfaced** (`NodeEngine`): captures
  stdout/stderr, logs the file list at INFO, logs returncode + stderr at WARNING on
  non-zero exit. Previously silent on any non-zero exit.
- **`revert(controller)`: drop XML persistence of `<online>`** — that field belongs
  to nodeconf, not the in-memory probe result.

---

### Tests

- `T007–T015, T023a, T027–T032, T034a` — async CuemsDeploy: coroutine shape, loop-None
  fast-fail, watchdog paths, mandatory-sources sad path, early-fail/success via real
  event loop, `--delete` flag contract, `_RSYNC_PASSWORD` ClassVar, `_media_files`
  shape, `sync_files(tag='media')` auto-expansion.
- `T043` (`test_cuems_deploy_integration.py`, `@pytest.mark.integration`) — real event
  loop + fake slow process; heartbeat coroutines at 100 ms intervals show ≤ ±20 % jitter
  during concurrent `sync_files()`, verifying SC-001 NNG coexistence.
- `test_gradient_client.py` (15 tests) — OSC address, type-tag string, motion_id at [0],
  node_uuid at [1], int64 h-tag, cancel addresses, OSC error propagation. Uses a real
  ephemeral UDP socket.
- `test_player_handler_gradient.py` (5 tests) — `GradientClient` lifecycle on
  `PlayerHandler` singleton.
- `test_node_engine_gradient.py` (8 tests) — `set_gradient_client()` from `set_players()`,
  node_uuid pass-through, `cancel_all` ordering before `stop_all_cues` on STOP and load.
- `test_fade_action_handler.py` — happy path (audio + video, single & multi-layer),
  arm-on-demand, per-layer motion_id, hard-fail on OSC dispatch error, `_end_mtc` seeding,
  unsupported target type.
- `test_loop_fade_cue.py` — block-until-`_end_mtc`, immediate exit when `_end_mtc is None`,
  cancellation via `_stop_requested`.
- `test_display_conf.py` — override-larger-than-bbox, exact-bbox, smaller-than-bbox
  (raises), zero/negative (raises), malformed (raises), absent (falls back to bbox),
  multi-output, T-shape canvas bbox, unknown forward-compat keys.
- `test_video_routing.py` (10 tests) — pixel conversion regression, canvas-dim resolver
  error case, alias path regression, custom synthesis, multi-node matching by full
  output_name, missing-cue-output KeyError.
- `test_players_audiomixer.py` — stereo, mono with 2 and 4 outputs, missing edge, wrong
  destination, crashed subprocess, linear query-count guard.
- `test_cuems_deploy.py` — 22 cases: supervision paths (startup deadline, inactivity,
  error exit), `on_progress` wiring, progress-line parsing. Updated for async internals.
- `test_action_cue.py` — 15 failure-path tests covering every newly guarded branch in all
  five action handlers.
- `TestMtcListenerRollover` — clean 24h boundary crossing, offset persisting across decode
  calls, manual seek NOT treated as rollover, forward jumps past boundary.
- Two `TestLoopDmxCue` mock fixtures updated to set `.milliseconds_rounded` instead of
  `.milliseconds` on the MTC mock.

---

### Notes

- `gradient-motiond` is assumed to be running on the node at all times; `cuems-engine`
  is not responsible for its process lifecycle.
- DMX cues retain their existing player-side fade mechanism (out of scope for this
  release).
- `CuemsDeploy.deploy_manager` captures the controller IP at init time; an IP change
  at runtime requires a node-engine restart.
- The surgical 1-frame fix at `loop_cue.py:107,224` from the sister task (869cy1yjb)
  remains untouched — it is now redundant with the `__add__`/`__sub__` fix in cuemsutils,
  but removal is deferred to a focused follow-up alongside a regression test.

---

## v0.1.0 — Initial release
