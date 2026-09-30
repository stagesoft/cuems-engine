# Changelog

## v0.1.0rc7 — UNRELEASED

Moves the engine onto `cuems-utils` 0.1.0rc16's public API. Nodes are identified by
`node_role` (not `node_type`), shows load through `CuemsScript.load` — so version-1 `script.xml`
files load again, converted in memory — and node and cue ids are handled as the library delivers
them, which removes a `cluster_status` crash on any node map the current library loads. Ships
together with `cuems-utils` 012–014; **read the upgrade notes before deploying.**

### Added

- The controller's node map lookup reads `node_role=controller` through the library's
  `NodeIndex`. A map with more than one controller is logged (one error listing each
  `uuid=… ip=…`) and the first controller in map order is used.
- A node whose `settings.xml` still carries the NOT PROVISIONED sentinel uuid logs one error
  naming `cuems-init-node` and exits before loading its configuration, instead of failing later
  with a generic "node not found".
- An empty `<duration/>` on an audio or video cue is treated as zero with one warning naming the
  cue (it used to be zero silently).
- `cuemsengine.tools.ids` (`as_id` / `id_str`): the engine's one place for converting ids. `as_id` is
  `cuemsutils.tools.coerce_identity`, the library's published rule (cuems-utils 012); the engine
  keeps no copy of it.

### Changed

- **Show loading**: `read_script` uses `CuemsScript.load`. A version-1 `script.xml` is converted
  in memory (the file on disk is left alone); a script newer than the installed library is
  refused with the library's error.
- **Adoption**: one read-only reader of `adopted` feeds OSC route registration, the liveness
  probe, the GO gate and `cluster_status`. Re-reading `network_map.xml` after a node-list change
  is no longer order-sensitive.
- **Identity**: ids are `Uuid` where the library delivers one (uuid4) and text otherwise; they
  enter engine code through `as_id` and leave it — sorts, JSON, OSC, logs — as text through
  `id_str`. `cluster_status` and `cluster_warning` keep their shape and stay lists of strings;
  pong/armed/finished senders and project nodes now match the map's ids one member per node.
- **`fade_out` is now a real stop — a behaviour change.** The library rewrites a version-1
  script's `fade_in`/`fade_out` actions to `play`/`stop` on read. `fade_in` → `play` behaves as
  before. A converted `fade_out` runs `stop`, which **disarms** its target (the old handler left
  player processes behind) and answers a repeat with `applied_no_change`.
- Dependencies: `cuemsutils >= 0.1.0rc16, < 0.1.1` (`pyproject.toml`); `debian/control`
  `cuems-utils (>= 0.1.0rc16)`, `cuems-utils (<< 0.1.1~)` and `cuems-common (>= 1.3.0-23~)`,
  the last inheriting `Breaks: cuems-nodeconf (<< 0.1.0-8)` because the engine reads
  `<node_role>`.
  The engine also needs cuems-utils feature 012's `cuemsutils.tools.coerce_identity`, which
  shipped inside the still-unreleased 0.1.0rc16 and so cannot be expressed as a version: build
  cuemsutils from a tree that contains it.
- `cuemsengine.__version__` is the single version source; `pyproject.toml` and this file's top
  entry are kept equal to it by a test.

### Removed

- `BaseEngine.find_hosts` (no caller; it could not run against the current library) and the
  `CONTROLLER_NETWORK_FLAG` constant.
- The engine's uses of the library's deprecated and internal surface: `XmlReaderWriter`,
  `NetworkMap.get_nodes_by_adoption` (which mutated the map it read) and the string-parsing
  workaround around it.
- The `fade_in` / `fade_out` action handlers; an in-memory ActionCue that still carries one is
  rejected as unsupported.
- `BaseEngine.node_host` (assigned, never read).

### Upgrade notes

1. **Upgrade every node host before the controller.**
2. Why: at show load the controller's library converts the show's `script.xml` to version 2 and
   deploys it to the nodes. A node on an older library cannot read it, and no package manager
   stands between the controller's deploy and the node's read. Nodes upgraded first read
   version-1 documents fine.
3. What the deploy ships and at which schema version: `script.xml` **2**, the project's
   `mappings.xml` 1, the project's `settings.xml` 1.
4. `cuems-utils` 012 and its node re-mint (every node converging on a uuid4 identity) go out in
   the **same upgrade** as rc7 engines, and the re-mint never runs under an older engine. rc7
   requires 012 — it takes `coerce_identity` from it — and no pre-rc7 engine has been run against
   012 or a re-minted map.

## v0.1.0rc6 — 2026-09-28

<!-- source: git log --no-merges fc8d2bb..956a0f3 (31 commits); debian/bookworm 0.1.0rc6-1 (7f6e475) -->

Auto continue chains are dispatched at their trigger, the controller ships the GO instant so
every node anchors its chain on the same MTC value, and the arm-ahead lookahead moves off the
command lock. Raises the `cuemsutils` floor to rc13.

### Added

#### Chain dispatch at the trigger (869ej4x38)

- A chain epoch orders concurrent chain dispatches and keeps a STOP in force against older
  cascades (`b85ce26`).
- The Auto continue chain is dispatched at its trigger, not cue by cue: each cue fires at
  trigger + its own prewait, so prewaits that run backwards fire on time instead of late
  (`0ffb166`).
- A stop takes its scheduled chain with it, and a cue enabled mid-chain rejoins at its own slot
  (`6e6d432`). A plain GO during an Auto follow tail still fires its target after the chain —
  documented, not changed (`c24db51`).

#### GO anchor shipped by the controller (869f79ecc)

- The controller captures the GO instant and ships it inside the GO command
  (`{"go_mtc_ms": ...}`); a node adopts it when its own lag is within [-200 ms, +10 s] and
  otherwise falls back to its local MTC with a warning. Mixed old/new controller and node
  versions keep working (`17482b1`, `7b35ccf`).
- `AudioMixer` logs how long each JACK port took to register on success, to size the 15 s
  ceiling from field data (`2942305`).

### Changed

#### Arm-ahead lookahead (869f79ecc)

- `setnextcue`'s lookahead runs on a `PreArm:<cue>` background thread, off the command lock, so
  the GO that follows a cue selection no longer waits for the next cues to load; only the
  selected cue is still armed synchronously (`423cccc`).
- `_arm_ahead` treats other nodes' cues as transparent (no arm, no budget, no depth), returns
  what it newly armed, and gains a cooperative abort and a per-type carve-out; the PreArm walk
  governs `arm()`'s own recursion, and audio cues are pre-armed like any other local cue
  (`77e4237`, `afef5da`, `ed18516`, `8f2710e`, `5fe9d6e`).
- Dependency: `cuemsutils >= 0.1.0rc13` (was rc4 in `debian/control`): `FadeActionHandler`
  divides `AudioCue.master_vol` by 100, and only rc13 moved its default to 100 — on older
  libraries a fade from an AudioCue with no deployed volume started at 1% (`956a0f3`).

### Fixed

- The controller ships the GO anchor only while its MTC input is live (any quarter frame or
  timecode sysex in the last 0.5 s); a dead input used to become every node's anchor at 0.0
  (`432c042`).
- The stop-cancel summary joined cue ids, which are `Uuid`s, and crashed inside the log line
  that reports what a stop cancelled (`6068dd8`, `0a9563f`).
- CI installs `librtmidi6` so the unit tests import `cuemsengine` again (`1b54369`); black/isort
  on the phase 2 files (`c006e40`, `361b391`).
- Packaging (debian/bookworm `0.1.0rc6-1`): the build venv is isolated from the build host and
  the build fails if `python-rtmidi` was not vendored — a host with `python3-rtmidi` installed
  produced a deb whose MTC read 0.0 forever.

## v0.1.0rc5 — 2026-08-14

<!-- source: git log --no-merges 2abf26d..fc8d2bb (5 commits); debian/bookworm 0.1.0rc5-1 (8b57710) -->

Auto continue triggers the whole chain at one common trigger.

### Changed

- **Auto continue (869ej3cc8)**: `CueHandler._chain_advance_ms` is now zero. It returned
  prewait + postwait, so every cue's prewait cascaded into every later cue: prewaits authored as
  absolute offsets from GO (5/35/65/95/380 s) played as 5/40/105/200/580. Every cue now shares the
  trigger as its arrival and plays at trigger + its own prewait; postwait keeps its meaning as a
  real tail under Auto follow / Auto pause and as the illumination hold. Not a DMX rule — DMX was
  the only cue type carrying a prewait in the reporting show (Castillo Medina del Campo)
  (`fc8d2bb`).
- A chain whose prewaits run backwards is still reached after its anchor and fires at dispatch;
  `go_threaded` now warns "firing LATE" instead of mistiming silently (closed in rc6).
- ActionHandler architecture analysis and controller-integration contracts documented
  (`be4e4f6`, `3645308`, `afff04a`); CI lint fixed and `poetry.lock` refreshed (`e210b26`).

## v0.1.0rc4 — 2026-08-03

<!-- source: git log --no-merges v0.1.0rc2..2abf26d (100 commits); debian/bookworm 0.1.0rc4-1 (15d50b6) -->

MTC-anchored cue timing (prewait, body and postwait as real MTC-timeline gaps with a held/reveal
mechanism), FadeCue fixes against `gradient-motiond`, the JACK port-wait fix for silent audio
cues, controller discovery via `controller.local`, and a restored test/CI pipeline.

### Added

#### MTC-anchored cue timing

- MTC-gated reveal: `run_cue` sets a cue up held (video invisible, audio not following, action
  not yet run) and `reveal_cue` shows it when live MTC reaches its start (`e1883a3`).
- prewait/body/postwait anchored as real MTC-timeline gaps, honoured identically on every node
  (`1855769`).
- Auto-follow / Auto-pause postwait is a real MTC-gated tail after the media body (`2ca443d`).

#### Controller and cluster

- Nodes resolve the controller as `controller.local` (mDNS), falling back to the
  `network_map.xml` `<ip>` (`92d006a`).
- The UI gets an authoritative, node-sourced read-back of mixer gain (`5ae765e`).
- `enable`/`disable` actions arm/disarm their target, so runtime-enabled cues are pre-armed
  (`334b553`).

#### Deploy and packaging

- `CuemsDeploy` sync/async branching with a blocking subprocess fallback (`18ef2c4`).
- `cuems-engine-mock` binary package for headless/UI-dev boxes (`22b54bb`).

### Changed

- Dependencies: `cuemsutils >= 0.1.0rc9`, then `>= 0.1.0rc10` (lxml 6.1.0 / CVE-2026-41066,
  media duration) (`165b48a`, `ef1f790`); lock at rc11 (`f490e34`); pyossia floor
  `2.0.0-rc6+124+cuems3` — cuems2 has no `Node.remove_child` (`dd60f76`); Poetry 2.4.1
  (`546c8ee`).
- `NodeEngine`'s load and stop share extracted teardown/re-arm helpers (`b476984`); the
  ActionHandler → CueHandler circular import is resolved with a protocol (`4d53856`).
- Code formatted with black/isort/flake8 (PEP 8) across `src/` and `tests/`.

### Fixed

#### Cue timing

- Auto-continue pre/post-wait timing, illumination and the cross-node loop (`46acadf`).
- `next_cue_pointer` advances when a GO has no local cue (`fb8feb8`).
- `_effective_duration_ms`: DMX fade times are milliseconds, not seconds (`31bae8c`).
- Video wraparound is enabled early for infinite-loop cues, so the first loop does not freeze on
  its last frame (`41ab6bc`).
- CueList children that reach their trigger un-armed are re-armed (`c9b8aa5`).

#### Audio

- Wait for the player's JACK port before wiring it to the mixer — the cue played green but
  silent (`e0896f2`, `3b56c2f`); fail fast when there is no JACK server at all (`c20a4e4`).

#### FadeCue / gradient-motiond

- `node_name` sent to gradient-motiond is the node's `role_id`/hostname, not its uuid, and
  cancel messages carry it (`45bbe9b`).
- Fade `start_value` comes from the live client, and consecutive fades chain from the recorded
  `end_value` (`2608ea8`, `afebe48`, `d642f2c`).
- FadeCue illumination is held for the fade duration on every node (`89bbd9b`); a FadeCue
  duration <= 0 fails loudly at reveal (`9b8c837`).

#### Other

- `PORT_HANDLER`'s exclusion list actually excludes; ports are bind-probed before being handed
  out (869ed9wf7) (`2abf26d`).
- Video layers render at native size and no longer bleed into neighbouring outputs (`fe595db`).
- `MtcListener` aligned with the unified C++ receiver across 24 h (`608fed2`).
- The NNG comms thread is stopped and joined before interpreter exit (`a4e5e61`).
- Action handlers wrapped in try/except (`18ec2cd`).
- Packaging: engine services restart on package upgrade (`b698d64`); `cuems-engine-mock` carries
  forward the rsync shim and PATH drop-in and keeps the `cuems-<component>` wrapper names
  (debian/bookworm `0.1.0rc4-1`).

### Tests

- Testing workflow with coverage report (`9faa30c`); PR protections and a contributors' code of
  conduct (`0f38840`); the integration suite no longer hangs and slow tests are split
  (`cfcfb9f`); the suite runs in a single process again and no longer collides with a live CUEMS
  install (`f287f0e`, `4cad9ff`, 869ed41ey).

## v0.1.0rc3 — 2026-04-16

<!-- source: debian/bookworm 0.1.0rc3-1 / 0.1.0rc3-2 (git show 7f6e475:debian/changelog, lines 105-132);
     first-parent packaging commits 99460bb (merge rc_1, 45 non-merge commits), 30af517, 0e0e284 -->

Cut from the packaging line before the `v0.1.0rc2` tag (2026-05-19). Its changes reached the
engine source through `rc_1` and are part of the rc2 entry below; this records the packaging
release.

### Changed

- Player binaries renamed: `audioplayer-cuems` → `cuems-audioplayer`, `dmxplayer-cuems` →
  `cuems-dmxplayer` (kill scripts, PlayerHandler pgrep filter, mock wrappers) (`1202b06`).
- Stale `dev/cuems-node-engine.service` removed; the unit in `cuems-common` is the single source
  (`5f0be1a`).
- `cuems-engine-mock`: drop-in wrappers renamed to the `cuems-<component>` convention;
  `Conflicts:` covers `cuems-dmxplayer` too; postinst reports the right install path (`0e0e284`,
  `0.1.0rc3-2`).

### Added

- Cue enable/disable toggle via WebSocket OSC; disabled cues are skipped in nextcue, GO, arming
  and auto-chains (`2256c56`, `856173e`).

### Fixed

- Arm waits for an in-progress arm instead of failing on concurrent access (`fe9339f`).

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
