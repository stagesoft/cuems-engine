# cuems-engine Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-05-14

## Active Technologies

- Python 3.11 (managed via pyenv + Poetry) (004-gradient-engine-phase6)

## Project Structure

```text
src/
tests/
```

## Commands

cd src [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] pytest [ONLY COMMANDS FOR ACTIVE TECHNOLOGIES][ONLY COMMANDS FOR ACTIVE TECHNOLOGIES] ruff check .

## Code Style

Python 3.11 (managed via pyenv + Poetry): Follow standard conventions

## Recent Changes
- 004-gradient-engine-phase6: Added Python 3.11 (managed via pyenv + Poetry)

- 004-gradient-engine-phase6: Added Python 3.11 (managed via pyenv + Poetry)

<!-- MANUAL ADDITIONS START -->
## Constitution

The full project constitution lives at `.specify/memory/constitution.md` (v1.1.0).
All agents MUST read and apply it. Key rules reproduced here for agent visibility:

- **TDD is NON-NEGOTIABLE**: write failing test → confirm failure → implement → green → refactor.
  No production code may be written before a failing test exists.
- **SOLID principles** apply to every module, class, and function.
- **No new runtime dependency** without documented justification and team review.
- **YAGNI**: every design decision must be justified by a current, concrete requirement.
- **Observability**: structured logging for all engine events; silent failures are forbidden.

### Documentation Artifact Layout (mandatory for all agents)

Artifacts MUST be placed in the correct location — misplaced files are a constitution violation:

| Location | Purpose |
|---|---|
| `specs/NNN-feature/` | Per-feature spec, plan, tasks, design notes. Owned by the feature branch. |
| `specs/planning/` | Cross-cutting planning docs spanning multiple features (roadmaps, migration strategies, phase handoff notes). Dev-internal only. |
| `docs/` (top-level) | End-user documentation and generated API reference (Doxygen/equivalent) ONLY. Hand-written dev planning artifacts MUST NOT go here. |

When creating or moving any documentation file, check this table first.

## Cue play modes & pre/post-wait semantics

A cue's `post_go` field decides what happens after it fires. Three values, mapped
to UI labels in `cuems-frontend` (`sequence.component.ts:107-109`):

| `post_go` | UI label | Behaviour |
|-----------|----------|-----------|
| `pause` | **Auto pause** | prewait → cue plays → postwait → **standby** (waits for the next GO). |
| `go` | **Auto continue** | prewait → cue plays; **postwait counts from the cue's play-start**. The next cue fires at `start + postwait`, regardless of media length. The current cue keeps playing "freely" — overlap with the next cue is allowed/expected. If postwait is 0 the next cue fires simultaneously. |
| `go_at_end` | **Auto follow** | prewait → cue plays to its end → postwait → next cue. **postwait counts from the cue's END.** Sequential, no overlap. |

**Load-bearing distinction — where the postwait clock starts:**

- **Auto continue (`go`)**: postwait measured from play-start ⇒ gap to next cue =
  `prewait + postwait` — the media **body (duration) is NOT counted**.
- **Auto follow (`go_at_end`) / Auto pause (`pause`)**: postwait measured from the
  cue's end ⇒ gap to next = `prewait + body + postwait`.

Terminology: **body / duration** = media playback length — `media.duration` for
A/V, `fadein_time + fadeout_time` (ms) for DMX, `0` for Action/CueList. `prewait`
and `postwait` are `CTimecode`, serialized nested:
`<postwait><CTimecode>00:00:05.000</CTimecode></postwait>`.

**Illumination** (sequence-view highlight; driven by `add_cue` / `remove_cue`
→ editor → frontend): a cue illuminates when it **arrives** (start of its prewait)
and stays lit for:

- Auto continue: `prewait + max(body, postwait)` — lit until it finishes playing
  *or* hands off, whichever is later. Multiple auto-continue cues can be lit at
  once (overlap).
- Auto follow / pause: `prewait + body + postwait`.

**Engine implementation — MTC-anchored reveal** (`CueHandler.py`, `NodeEngine.py`):

- Each cue's timeline slot: `arrival_k = GO_mtc + Σ eff(preceding chain cues)`;
  `start_k = arrival_k + prewait_k`. The cue is set up **held** (video invisible /
  audio not-following / action not-yet-run / DMX self-schedules from absolute
  `mtc_time`) by `run_cue`, then **revealed** (`reveal_cue`: video `/visible 1`;
  audio `/offset`+`/mtcfollow 1`; action executes; DMX no-op) only when live MTC
  reaches `start_k` — gated by `CueHandler._reveal_wait`. Because every node
  derives `start_k` from the same shared `GO_mtc` + identical durations, the gap
  and start frame are aligned cluster-wide.
- `post_go='go'` chains **fire in parallel across nodes**. On each GO, a node's
  `NodeEngine.go_script` walks the chain from the GO press, **skips cues owned by
  other nodes** (adding their slot offset to `Σ`, so its own first local cue lands
  at the correct slot), and fires that local cue at `GO_mtc + Σ`. Then each cue's
  `go_threaded` walks on via `_next_local_fire` to this node's next local+enabled
  cue. Disabled cues are transparent (`Σ += 0`); a `post_go != 'go'` cue breaks the
  chain (hand-off — wait for next GO).
- The per-cue slot contribution is `CueHandler._effective_duration_ms`. **Intended:**
  for auto-continue (`go`) it must be `prewait + postwait` (**body excluded** — the
  overlapping cue keeps playing on its own); auto-follow gets its body wait from
  `loop_cue` naturally (it fires the next cue *after* the media finishes).
- `prewait` is applied at exactly one point (`start = arrival + prewait`), never as
  a wall-clock `sleep`. The postwait `sleep` in `go_threaded` is **dispatch pacing
  only** (avoids arming the whole chain at once) — the real timing comes from the
  arrival/reveal math, not that sleep.

Cross-cutting invariants: never auto-stop a running project; `_reveal_wait` exits
on `_stop_requested` (STOP) or a changed `_go_generation` (newer GO/reload) and
does **not** bail on a recoverable MTC stall (reveal fires late on resume);
anchor comparisons use wrap-accumulated `milliseconds_exact` (24h-safe).
See `Plans/postwait-postgo-chain-semantics.md` and
`Plans/postwait-engine-only-implementation.md` (in the cuems-RELATIONS index repo)
for the full design/diagnosis.
<!-- MANUAL ADDITIONS END -->

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/007-cuemsdeploy-sync-fallback/plan.md`.
<!-- SPECKIT END -->
