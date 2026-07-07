# cuems-engine

Part of the **CUEMS** ecosystem — see the [`cuems-RELATIONS`](https://github.com/stagesoft/cuems-RELATIONS) repo for the system index, architecture diagram, and protocol/port map.

## Role

Controller/node orchestrator: loads projects, broadcasts MTC timecode, manages the cue lifecycle, and communicates with the UI (`cuems-editor`) and cluster nodes. Python 3.11 (pyenv + Poetry).

**One source repo, TWO systemd services.** The engine builds `cuems-controller-engine.service` (controller role) AND `cuems-node-engine.service` (node role — runs on every host, including controllers). There is **no** `cuems-engine.service`.

- A **controller HOST runs BOTH** services concurrently: the controller box also acts as a node, driving its own videocomposer/audioplayer/dmxplayer with its own `MtcListener` and OSC clients in each process.
- A **pure node host** runs only `cuems-node-engine.service`.
- The two processes **do NOT share memory**: each has its own `MtcListener`, `_24h_offset_frames` accumulator, OSC sender, and cue-handler thread.
- **When patching engine source on a controller, restart BOTH services.** Restarting only one leaves the other running stale code (caught us hard 2026-05-13: a 6h-old node-engine kept sending corrupted MTC offsets long after controller-engine had been restarted with the fix).

Role is decided **only** by `<node_type>` in `/etc/cuems/network_map.xml` (`NodeType.master` → controller, `NodeType.slave` → node); the engine reads its own `<uuid>` from `settings.xml`, looks itself up, and runs the matching role logic. Constant `CONTROLLER_NETWORK_FLAG = "NodeType.master"` in `BaseEngine.py`. See the cuems-common CLAUDE.md for the full roles & targets contract.

## Build & run

```bash
cd <this repo> && poetry install
```

Runs as the two systemd services above. On the dev/deploy boxes the engine often runs **editable from source** via a `cuemsengine.pth` overlay rather than the `.deb` — so a `.deb X.Y` version label can be misleading; patch = edit the working tree + restart both engines.

**Commits must be GPG-signed** (`commit.gpgsign=true`; the repo enforces it). On a "gpg failed to sign" error, retry the commit — never `--no-gpg-sign`.

## Constitution

The full project constitution lives at `.specify/memory/constitution.md` (v1.1.0). Key rules:

- **TDD is NON-NEGOTIABLE**: write failing test → confirm failure → implement → green → refactor.
- **SOLID** applies to every module, class, and function.
- **No new runtime dependency** without documented justification and team review.
- **YAGNI**: every design decision justified by a current, concrete requirement.
- **Observability**: structured logging for all engine events; silent failures forbidden.

### Documentation artifact layout (mandatory)

| Location | Purpose |
|---|---|
| `specs/NNN-feature/` | Per-feature spec, plan, tasks, design notes. Owned by the feature branch. |
| `specs/planning/` | Cross-cutting planning docs spanning multiple features. Dev-internal only. |
| `docs/` (top-level) | End-user docs and generated API reference ONLY. Hand-written dev planning artifacts MUST NOT go here. |

## MTC timecode lifecycle

MTC starts running as soon as a project is loaded and ready — **before** the first GO. On GO, the engine captures the current MTC position (`frozen_mtc_ms`) and computes a negative offset so playback starts from the beginning of the media (e.g. MTC at 3.88s / frame 96 → `offset_to_go = -96` so the videocomposer renders frame 0). **MTC is always non-zero at first GO — by design, not a bug.**

The engine's `MtcListener` reads MTC from ALSA `Midi Through Port-0` (delivered by rtpmidid on nodes); on the controller the MTC *source* is a `libmtcmaster` `MtcMaster` (ALSA client ~130). The controller stays at libmtcmaster's default `FR_25` — the engine never binds `MTCSender_setFrameRate`, so **CUEMS MTC is always 25 fps**; players translate that to media fps.

## Cue play modes & pre/post-wait semantics

A cue's `post_go` field decides what happens after it fires. Three values, mapped to UI labels in `cuems-frontend` (`sequence.component.ts:107-109`):

| `post_go` | UI label | Behaviour |
|-----------|----------|-----------|
| `pause` | **Auto pause** | prewait → cue plays → postwait → **standby** (waits for next GO). |
| `go` | **Auto continue** | prewait → cue plays; **postwait counts from play-start**. Next cue fires at `start + postwait` regardless of media length; current cue keeps playing "freely" (overlap allowed). postwait 0 → next cue fires simultaneously. |
| `go_at_end` | **Auto follow** | prewait → cue plays to end → postwait → next cue. **postwait counts from the cue's END.** Sequential, no overlap. |

**Load-bearing distinction — where the postwait clock starts:**

- **Auto continue (`go`)**: postwait measured from play-start ⇒ gap to next = `prewait + postwait` — the media **body (duration) is NOT counted**.
- **Auto follow (`go_at_end`) / Auto pause (`pause`)**: postwait measured from the cue's end ⇒ gap = `prewait + body + postwait`.

Terminology: **body / duration** = media playback length (`media.duration` for A/V, `fadein_time + fadeout_time` ms for DMX, `0` for Action/CueList). `prewait`/`postwait` are `CTimecode`, serialized nested: `<postwait><CTimecode>00:00:05.000</CTimecode></postwait>`.

**Illumination** (sequence-view highlight; driven by `add_cue`/`remove_cue` → editor → frontend): a cue illuminates when it **arrives** (start of its prewait) and stays lit for:

- Auto continue: `prewait + max(body, postwait)` (multiple auto-continue cues can be lit at once).
- Auto follow / pause: `prewait + body + postwait`.

**Engine implementation — MTC-anchored reveal** (`CueHandler.py`, `NodeEngine.py`):

- Each cue's timeline slot: `arrival_k = GO_mtc + Σ eff(preceding chain cues)`; `start_k = arrival_k + prewait_k`. The cue is set up **held** (video invisible / audio not-following / action not-yet-run / DMX self-schedules from absolute `mtc_time`) by `run_cue`, then **revealed** (`reveal_cue`: video `/visible 1`; audio `/offset`+`/mtcfollow 1`; action executes; DMX no-op) only when live MTC reaches `start_k` — gated by `CueHandler._reveal_wait`. Every node derives `start_k` from the same shared `GO_mtc` + identical durations → aligned cluster-wide.
- `post_go='go'` chains **fire in parallel across nodes**. Each node's `NodeEngine.go_script` walks the chain from the GO press, **skips cues owned by other nodes** (adding their slot offset to `Σ`), and fires its own first local cue at `GO_mtc + Σ`. Each cue's `go_threaded` walks on via `_next_local_fire`. Disabled cues are transparent (`Σ += 0`); a `post_go != 'go'` cue breaks the chain (hand-off).
- Auto-continue slot contribution = `CueHandler._chain_advance_ms` = `prewait + postwait` (body excluded). `_effective_duration_ms` (pre+body+post) survives only for arm-ahead lookahead.
- **Auto-follow / auto-pause postwait = an MTC-gated tail after the body**: when `loop_cue` returns, the engine blanks the video (`blank_cue`: `/visible 0`, cue stays armed → STOP-reachable), waits until `body_end + postwait` on the MTC timeline, then ends illumination (`remove_cue`) and — for follow — fires the target via `go_from`. A manual GO during the tail **preempts** the auto-fire. Follow fires at `body_end + postwait`, not at media end.
- `prewait` is applied at exactly one point (`start = arrival + prewait`), never as a wall-clock sleep. The postwait `sleep` in `go_threaded` is **auto-continue only**: dispatch pacing + holding the thread past the body when `post > body`.

Cross-cutting invariants: **never auto-stop a running project**; `_reveal_wait` exits on `_stop_requested` (STOP) or a changed `_go_generation` (newer GO/reload) and does **not** bail on a recoverable MTC stall (reveal fires late on resume); anchor comparisons use wrap-accumulated `milliseconds_exact` (24h-safe). See `Plans/postwait-postgo-chain-semantics.md` and `Plans/postwait-engine-only-implementation.md` in the cuems-RELATIONS index repo for the full design/diagnosis.

## Cue lifecycles (engine side)

Engine → VideoComposer and engine → DmxPlayer are inter-component protocols documented once in the cuems-RELATIONS CLAUDE.md ("Video/DMX Cue Lifecycle"). The engine side: arm → send load/`/frame` bundle → run (set offset/visible/mtcfollow, or scene bundle) → reveal on MTC. See the videocomposer and dmxplayer CLAUDE.md for the player halves.

## Field notes / gotchas

- **Editing `network_map.xml` or `default_mappings.xml` requires restarting BOTH `cuems-controller-engine` AND `cuems-editor`** (plus `cuems-node-engine` if active) — both daemons load topology **once at startup** via `ConfigManager(load_all=True)` and hold it in memory; there is no per-project-load reload. Edit → `xmllint --noout --schema /etc/cuems/<x>.xsd <file>` → confirm no project loaded → restart. Verify: editor logs `"number_of_nodes": N`; engine logs correct `Controller IP` + adopted set.
- **`cuems-node-engine` has two non-obvious hard startup blockers** (both hit on formitgo 10.16.1.111):
  1. `Requires=jack-alsa-bridges.service`, which runs `zita-j2a -d hw:PCH,0`. If that ALSA device doesn't exist (onboard codec is HDMI-only, or a USB DAC is the real card) zita fails → dependency failure → node-engine never starts. Fix: repoint `-d` to the real card (`/proc/asound/cards`; USB DAC often `hw:HID,0`), `daemon-reload` + `reset-failed` + restart.
  2. `set_video_outputs` reads `/run/cuems/display.conf` and dies with `DisplayConfNotFoundError` if there are no `[output:*]` sections with a valid `canvas_region`. A hand-authored override that only sets `resolution_policy=native` (no sections) is tolerated by videocomposer but **breaks node-engine** — keep the `[output:*]` sections too.
- **On a controller that MASKS `jack-alsa-bridges`, `systemctl restart cuems-node-engine` fails** ("Unit ... is masked") because the masked unit is in the `Requires=` closure; boot works (the target transaction tolerates it) but unit-level restart + `Restart=on-failure` auto-restart don't. A `Requires=`/`After=` drop-in reset does **not** clear the edge (only `Wants=` reset does). Fix: unmask + stub the audio units (`ExecStart=/bin/true`, `Type=oneshot`, `RemainAfterExit=yes`) so the Requires are satisfied by no-ops.
- **Single-box controller won't arm if `network_map.xml`'s controller `<ip>` isn't locally reachable.** node-engine dials `tcp://<controller-ip>:9093` for the NNG hub; a dead/absent `<ip>` leaves it in TCP SYN-SENT forever with no error log → never receives `load` → never arms (`409 not_armed`). Diagnose: `ss -tnp | grep :9093` (SYN-SENT from node-engine). Fix for single-box: set controller `<ip>` to `127.0.0.1` (hub listens on 0.0.0.0). Only valid with no real remote nodes; if nodeconf is enabled it re-owns `<ip>` and writes a real assigned local addr (also fine).
- **Isolated MTC-harness injection on a live host is polluted by the engine's own MtcMaster** (ALSA client 130 emits periodic resync full-frames at position 0 even with no project loaded → interleaves with harness frames → spurious +24h wraps). Stop the whole stack first: `systemctl stop cuems-controller-engine cuems-node-engine cuems-midiconnector rtpmidid cuems-videocomposer`. Run MTC tools as root (`/dev/snd/seq` is `root:audio`).
- Engine canvas (bbox of ALL `display.conf` `[output:*]` regions) vs videocomposer canvas (connected DRM connectors only) can diverge on partially-cabled rigs — a **known accepted limitation**, don't ad-hoc fix. See the videocomposer CLAUDE.md.
