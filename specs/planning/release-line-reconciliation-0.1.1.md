<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Release-line reconciliation for `cuems-engine 0.1.1-1` — merge before release

**Written 2026-10-17** on `feat/xml-refactor` at `e994a5e` (the `xml-refactor-merge-candidate` tag
commit). **Status: pre-spec, decided, not started.** It is the input for the next SDD feature,
**`009-release-line-reconciliation`**. Run `/speckit-specify` with Appendix A, then the rest of the
suite.

**Lifetime: temporary.** This file is a pre-spec. Once `specs/009-release-line-reconciliation/`
has absorbed it (spec, plan, research, evidence and upstream reports), it is **deleted as the final
task of 009** (§11, last step). `specs/planning/` holds only living cross-cutting documents.

**What it discharges.** It covers rule 4 ("merge before bump") of
[`cuems-utils/specs/planning/coordinated-release-version-bump.md`](../../../cuems-utils/specs/planning/coordinated-release-version-bump.md)
for this repository, and the **NOT YET RECONCILED** section of
`../.xml-refactor-tag-messages/cuems-engine.txt`. **cuems-engine is the first of the seven repositories
to reconcile.** So this feature also writes down what the siblings owe it (§8). Those obligations
are written here, but they are carried out in the siblings' own reconciliations.

## 0. Decisions already taken (maintainer, 2026-10-17)

| # | Decision |
|---|---|
| D1 | **`stop_project` lands in full**, on the condition that cuems-utils' own reconciliation puts rc17's `stop_project` into `0.1.1`. An upstream report goes to cuems-utils (§8.1). Until then, every test that needs the XSD value is a **strict xfail**. |
| D2 | This session writes a **pre-spec plus a `/speckit-specify` prompt**. It writes no code. |
| D3 | **Feature branch `009-release-line-reconciliation` off `feat/xml-refactor`**. The release line merges in there and gets adapted there. The branch then merges back into `feat/xml-refactor` with `--no-ff`, and the **maintainer** re-cuts the candidate tag. Agents never move tags. |
| D5 (2026-10-17) | **The CI change is part of 009.** The restructured workflow is the **pre-publication gate**: it is run **manually, in the cloud, as a GitHub Action** (`workflow_dispatch`) on the release candidate before anything is published. §14.5 covers it. |
| D4 (inherited) | The version **stays `0.1.1-1`**. Rule 4 means the merge goes *under* the bump that has already been made. The top changelog entry grows; it is not renumbered. |

## 1. Goal, scope, non-goals

**Goal.** `0.1.1-1` must carry every fix and feature that shipped from the engine's release line
since the refactor branched, so that nothing released in `0.1.0rc3-1 … 0.1.0rc6-5` is lost. The
xml-refactor contract (feature 008: typed node map, `Uuid` identity rules, version-2 scripts, no
`fade_in`/`fade_out`) must hold for the absorbed code too.

**In scope.** All source, tests, docs, packaging and changelog content reachable from
`origin/debian/bookworm` and `origin/rc_1` but not from `feat/xml-refactor`. The adaptation of that
code to the 008 contract. Re-verifying this repository's package relations. The tag-message
rewrite, which only produces a text file.

**Not in scope.**
- Publishing anything.
- Relocking `poetry.lock`. FR-022 still waits for `cuemsutils 0.1.1` on an index;
  `tests/test_lock_is_current.py` stays strict-xfail.
- ~~Engine CI turning green~~ **moved into scope by D5** (§14.5). CI resolves `cuemsutils` from a
  cuems-utils git ref, which is option A of `coordinated-release-inputs-pyossia-and-engine-ci.md`
  §4.3. What stays out of scope is *publishing* after the gate passes.
- Any sibling's reconciliation.
- New behaviour.

**Moving target.** The release line keeps releasing (for example a future `0.1.0rc6-6`). The
snapshot below is what this spec measures. The implementation **re-measures at its start and again
before hand-off**, and merges anything newer the same way (§11, step 1 and step 9). Measuring
against `master` is wrong: it is `92f03c6`, from 2025-02.

## 2. The three lines, measured 2026-10-17 (after `git fetch --all --tags`)

| Ref | Commit | What it is |
|---|---|---|
| `feat/xml-refactor` = `xml-refactor-merge-candidate^{commit}` | `e994a5e` | 0.1.1-1, UNRELEASED |
| `origin/debian/bookworm` | `b8431a3` | **the release line**, `0.1.0rc6-5` (tag `v0.1.0rc6-5`) |
| `origin/rc_1` | `698e777` | the development line feeding it |
| merge-base (all three) | `956a0f3` | 2026-09-28, the `rc_1` point merged into the refactor at `27b27f5` |

- `feat/xml-refactor` is **119 behind / 27 ahead** of `debian/bookworm`, and **84 behind / 27 ahead**
  of `rc_1`.
- **`rc_1` ⊂ `debian/bookworm` in content.** `git diff origin/rc_1 origin/debian/bookworm -- src tests
  docs CLAUDE.md` differs only in `src/cuemsengine/__init__.py` (the version string). The one
  `rc_1` commit not in bookworm is the merge commit `698e777` (PR #35), whose content reached bookworm
  through `feat/stop-project-actioncue` (`9d52e15`).
- Of the 119, about 35 are **bookworm-only** packaging and release commits. The rest are `rc_1`
  feature and fix commits.
- Changelog entries on the release line that the refactor does not have: **`0.1.0rc3-1`, `rc3-2`,
  `rc4-1`, `rc5-1`, `rc6-1`, `rc6-2`, `rc6-3`, `rc6-4`, `rc6-5`**.
- ⚠ **Five more released builds are on neither line: `0.1.0rc5-2 … rc5-6`.** They come from the
  `hotfix/rc5-*` branches, with tags `v0.1.0rc5-2` (`9a02a19`), `v0.1.0rc5-3` (`d7e9832`) and
  `v0.1.0rc5-6` (`69e91e4`). The release line itself never absorbed them, and the 016 tag message's
  "Absent released entries" list omits them. See §4.1.
- The **code** of `rc3-1 … rc6-1` is already on `feat/xml-refactor`, through the `956a0f3` merge. For
  those entries only the changelog text is absorbed. **New code arrives only from `rc6-2 … rc6-5`**.

## 3. Strategy: one real merge, then adaptation commits

**Measured, and contrary to the expectation that a direct merge is impossible:**
`git merge --no-ff origin/debian/bookworm` into `e994a5e` stops with **7 conflicting files**:

| File | Hunks |
|---|---|
| `debian/changelog` | 1 |
| `debian/control` | 2 |
| `pyproject.toml` | 2 |
| `src/cuemsengine/__init__.py` | 1 |
| `src/cuemsengine/ControllerEngine.py` | 2 |
| `tests/test_controller_commands.py` | 2 |
| `tests/test_nodelist_modify.py` | 1 |

The other source files merge cleanly. **The hard part is semantic, not textual.** With the conflicts
resolved mechanically, the merged tree fails **10 tests that pass on `e994a5e`** (§6.1).

**Methods, chosen per item.** The table in §4 assigns one to every item.

| Method | Used for | Why |
|---|---|---|
| **M — merge** (`git merge --no-ff origin/debian/bookworm`, then `git merge --no-ff origin/rc_1`) | everything, as the vehicle | It is the only method that makes `git rev-list --count HEAD..origin/debian/bookworm` (and `..origin/rc_1`) reach **0**. That count is rule 4's measurable form, and §8 of the planning document measures every sibling by it. It keeps ancestry, so the *next* release-line commit merges without re-conflicting. It brings the released changelog entries verbatim. The second merge only adds `698e777`'s ancestry; its only conflicts are version sites, resolved to ours. |
| **R — conflict resolution** | the 7 files above | Rules in §5 |
| **A — adaptation** (direct implementation, TDD, separate commits *after* the merge commit) | code that merged cleanly but breaks the 008 contract, or tests that encode a pre-008 or pre-rc6 assumption | The fix lives in the absorbed code's shape, not in either parent. The same rule as the planning document's §10.4: "merging brings the changelog entry but not a working fix". |
| **C — cherry-pick** | **nothing** | It would lose ancestry, so the behind-count never reaches 0, and the next merge from the line re-conflicts with the duplicates. With bookworm ⊇ rc_1 and only 7 textual conflicts it saves nothing. Keep it as a fallback only for an item a maintainer explicitly excludes from 0.1.1. None is excluded today. |

**Commit shape** (all GPG-signed; on a gpg failure, retry and never use `--no-gpg-sign`):

1. The merge commit of `origin/debian/bookworm`, containing the §5 resolutions **and nothing else**.
2. The `origin/rc_1` merge.
3. One commit per adaptation (§6). Under the constitution's TDD rule, each fixes a test that is red
   on the merge commit, or adds the missing red test first.
4. The packaging and changelog commit (§7).
5. The docs commit (§9).
6. A suite and relations re-verification record.

Do **not** use `git merge -X ours/theirs`. It silently drops whole hunks of absorbed fixes.

## 4. Inventory: what the merge brings, and the method for each item

ClickUp ids in parentheses. "Released in" is the bookworm changelog entry that shipped it.

| # | Item (PR) | Commits on `rc_1` | Released in | Method | Seam on the refactor |
|---|---|---|---|---|---|
| 1 | Video scale readback with float32 tolerance; placement failures at ERROR, recorded per cue; disarm skips layers removed by `/reset`, and every disarm is logged with a reason (869f8hfra, #20) | `6f8c356`…`2313c90` | rc6-2 (shipped, not listed in the entry) | M | **A-1**: `disarm()` now takes `reason=`, which breaks 008's `test_action_cue` (§6.1) |
| 2 | Delete the dead `VideoPlayer` (869f8v8yv, #21) | `e890954` | rc6-2 | M | none |
| 3 | Pre-arm of the node's next segment; one arm in flight per cue; publish-or-abandon arm epochs; the JACK wait ends on a dead player; a GO that cannot arm skips and advances (869f9wqpn, #22) | `b1d3063`…`ecafa23` | rc6-2 | M | none measured |
| 4 | Pre-arm measurement log lines (#22) | `1897104`…`9eaeae5` | rc6-2 | M | none |
| 5 | Video pixel size taken from the project, not ffprobe; nodes report their own media files that differ from the project (869fat84r, #22) | `98a69c3`…`52c7d06` | rc6-2 | M | **A-2**: 008's `test_media_duration` mocks the old probe path; **R-1**: `media.get("pixel_width")` against `Unset` defaults (§6.2) |
| 6 | Video wraparound only for repeating cues (869fa89uh, #23) | `9ac6b39` | rc6-3 | M | **A-3**: its test builds `media.duration` as a plain `str`, which 008's `media_duration()` helper does not read |
| 7 | Cross-node Auto follow relay, `run_seq`, `FollowRelay.py` (869fc8ytz, #25) | `6dad8cc`…`2c358f4` | rc6-3 | M | **A-5**: id conformance (`str(...)` on ids in `FollowRelay`) |
| 8 | Audio ready gate: wire on RUNNING, edge-by-edge repair at GO, arm-wait messages (869fbyjzx/869fcvz85, #27, #30) | `a90adf9`…`173301e` | rc6-3 | M | none measured |
| 9 | Cue names on the `:9190` channel (869fedahu, #28) | `df3e796`, `5ffb1b8` | rc6-3 | M | **A-5**: names are keyed by `item.id`; check that the OSC address uses `id_str` |
| 10 | Orphan-kill sweeps never abort a load, match only own-user players by argv[0], log the callback traceback (869evtdf7, #29) | `ce41208`…`0d197f3` | rc6-3 | M | none |
| 11 | `project_status`: three states, `running` / `loaded` / `none`, and a failed load clears `load` (869dr2kzh/869dr2k2h, #32) | `cdf8fcf`, `ff39eed` | rc6-4 | M + **R** (`test_controller_commands.py`) | **A-5**: `"project_uuid": str(self.script.id)` → `id_str` |
| 12 | Unrouted video outputs stay dark; `display.conf` `enabled=` (869fgq3xv, #33) | `5b5ed86`, `73e52a4` | rc6-4 | M | **A-5**: `{"cue_id": cue.id}` in `check_unrouted_video_outputs`' return value |
| 13 | **`stop_project` ActionCue**; cue ADD/UPDATE ignored while not running; the arm watchdog restarts after STOP; the dead `script_finished` aggregator removed (869fhjdq5/869fhjdp8, #35/#36) | `4121749`, `c401e5f` | rc6-5 | M + **R** (`ControllerEngine.py` hunk 1) | **A-4**: 008's `test_cluster_identity` tests the removed aggregator; **A-6**: 008's `test_identity_sweep` ADD test needs `running=yes`; **X-1**: needs cuems-utils (§8.1, D1) |
| 14 | Build venv isolated from the build host; the build fails if `python-rtmidi` is not vendored (869f79ecc) | `83f3ff0` (bookworm-only) | rc6-1 | M (`debian/rules`, merges cleanly) | none |
| 15 | Stop shipping `cffi-gen-src` | `dd723a0` (bookworm-only) | rc6-2 | M | pairs with the cuems-utils `Replaces:` (§8.1) |
| 16 | Mock player wrappers renamed `cuems-audioplayer` / `cuems-dmxplayer`; `Conflicts: cuems-dmxplayer`; postinst path text | `0e0e284` etc. (bookworm-only) | rc3-2 / rc4-1 | M + **R** (`debian/control`) | none |
| 17 | SPDX headers on `debian/control` and `debian/rules` | bookworm-only | rc6-x | M + R | none |
| 18 | Released changelog entries `rc3-1`…`rc6-5` | bookworm-only | — | M + **R** (`debian/changelog`) | §7.1 |
| 19 | `docs/unattended-playback.md`, `docs/index.md`, and the CLAUDE.md additions | `c401e5f`, `2c358f4`, `bd8381b`, `73e52a4`, `0d197f3`… | — | M (clean) | **§9**: version claims say `rc17` / `rc6-x` |
| 20 | `cuemsutils = ">=0.1.0rc17"` (rc_1/bookworm pyproject) | `4121749` | rc6-5 | **R → ours** | Subsumed by `>=0.1.1,<0.1.2` **only if** utils 0.1.1 contains rc17 (X-1) |

**Checked and found to be no reconciliation item:**
- `66aeb1f` ("Fix infinite recursion in load_project": `deploy_project(…, context=)`) and `ea81c50`
  (UUID in error responses) are January bookworm-only commits. The release line's own current tree no
  longer carries `66aeb1f`'s `deploy_project` change (`rc_1` superseded both and overwrote them in
  later merges). The merged result equals the release line here, so nothing shipped is lost. For the
  record, the bug `66aeb1f` fixed (load recursion) is guarded on `rc_1` differently
  (`forward_to_nodes=False`).
- `2cf205b` (restart services on upgrade): `debian/postinst` is already identical on both sides.

### 4.1 Outside both lines: stray branch heads and tags (swept 2026-10-17)

Every `origin/*` branch and every tag was checked for commits reachable from neither
`feat/xml-refactor` nor `origin/debian/bookworm`
(`git rev-list --no-merges <ref> ^HEAD ^origin/debian/bookworm`, plus `git cherry` for patch
equivalence).

| # | Ref | What | Released? | Relevance | Method |
|---|---|---|---|---|---|
| 21 | `hotfix/rc5-2-prearm` → `rc5-4-video-loop-wrap` → `rc5-5-audio-ready-gate` → `rc5-6-orphan-kill` (stacked; tags `v0.1.0rc5-2`, `-3`, `-6`) | rc5 backports of 869f79ecc, #22, #23, #27, #29 | **yes**, 0.1.0rc5-2…rc5-6 (30 Sep – 8 Oct) | **Code: none needed.** Each code commit maps to an rc_1 commit already in scope: `951503d→7b35ccf`, `7bccee8→8803dfe`, `cf5421f→f391675`, `68b09a0→4fc6d08`, `5509d87→0f7fb17`, `6eb827f→2e96b1c`, `092d99f→ecafa23` (its message says so), `2d8facc→58869e6`, `24e8054→ee3b060`, `929fdc0→674aefb`, `47b06b5→32dae0d`; the rest are patch-equivalent. **Changelog: 5 released entries are missing.** | **D — direct copy** of the five entries, verbatim from `git show v0.1.0rc5-6:debian/changelog`, into §7.1's position. Optionally also record ancestry with `git merge -s ours v0.1.0rc5-6`, citing this equivalence table, so future sweeps stop flagging the line (§12 Q6). A content merge is **not** an option: backports onto an rc5 base would re-conflict across all of #22–#29. |
| 22 | `fix/node-output-maps-ignore-inputs` `35cbe78` (Ion, 2026-10-15, base `93d5a2c` on rc_1) | **Production bug.** NodeEngine built the output→JACK-port and output→display lookups from inputs too, and input 0 overwrote output 0. An audio cue on `<node>_0` resolved to `system:capture_1` and played **SILENT** on any node whose mappings list inputs (seen on dev.stagelab.coop) | no; not on rc_1 | **must be included**. Without it, 0.1.1-1 ships a silent-audio bug that has a fix | **M** (merge the branch head after step 3). Its only conflicts are the same 2 test files as the main merge. **A-7**: check it against 008's typed `project_mappings` read path, and add a red test (mappings with `inputs` → the output lookup ignores them) if the branch has none. |
| 23 | `fix/mock-players-jack-ready` `d50ee4b` (2026-10-15, base `93d5a2c`) | The mock audioplayer and jack-volume register JACK ports and print `[OK] RUNNING!`. Without this, every mock-box arm waits the full 14.5 s ready-gate timeout introduced by #27 (item 8) | no | **should be included**: item 8 makes `cuems-engine-mock 0.1.1-1` close to unusable without it | **M**. Clean apart from the shared test conflicts |
| 24 | `feat/mock-nodeconf` `5a1811c` (2026-10-15) + `debian/mock-nodeconf-dropin` `3c11c60` | `cuemsengine.scripts.mock_nodeconf`, which answers `nodelist_modify` on `/tmp/nodeconf.ipc` for mock boxes, plus a `cuems-nodeconf.service.d` drop-in shipped by `cuems-engine-mock` | no ("belongs to the release that merges rc_1 with the script") | **include, but it cannot merge as written; it breaks three 0.1.1 rules**: (a) it imports `cuemsutils.xml.XmlReaderWriter`, which is deprecated (removed in 0.1.2) and forbidden by `test_public_surface.py`; (b) it detects the controller with `node_type … endswith("master")`, the retired vocabulary that 0.1.1 refuses at load; (c) it writes `<adopted>True</adopted>`, which is not a valid `xs:boolean` after utils 014 (`true`/`false`) | **M + A-8**: merge for ancestry, then re-implement `set_adopted` on cuemsutils' public network-map API (`node_role`, typed `adopted: bool`, the published validate/write path). TDD covers: refuse unadopting the `controller` role; an offline node cannot be adopted; the written map validates against 0.1.1's `network_map.xsd`. The drop-in is a **cross-package edge**: the mock overrides a unit that cuems-nodeconf owns, so tell cuems-nodeconf (§8.2) |
| — | `integ/rc6-3-node-adoption` `363b92a` | `0.1.0rc6-3+nodeadopt2`, a "test-rig integration build" changelog entry | rig only | Not a release. Its content shipped in rc6-4 | **Excluded**, and the exclusion is recorded in evidence (§12 Q7) |
| — | `gh-pages` | MkDocs deploy output | — | not source | excluded |
| — | `archive/*` tags (`feat-async_go`, `feat/action_cue`, `coms_thread`, …), `docker`, `nodeconf`, `server`, `engine-server`, `2ppo`, `osc_no_bool` (2020–2025) | archived or abandoned work | no | superseded; archiving was deliberate | excluded |

Branches 22–24 are unreviewed PR heads by their author, and they may land on `rc_1` before 009 starts.
**Merge them by their branch-head SHA, never cherry-pick.** Then a later `rc_1` merge of the same
commits is a no-op, and §11 step 1's re-measure picks up whichever route they took. The `gh` CLI is
not installed on this host, so their PR state was not checked. Check it at step 1.

## 5. Conflict resolutions (method R)

| File / hunk | Resolution | Reason |
|---|---|---|
| `ControllerEngine.py` hunk 1 (`status_operation_callback`): HEAD has `script_finished` with 008's `as_id(operation.sender)`; theirs has `stop_project` | **Take theirs.** Delete the `script_finished` branch. | 869fhjdp8 removed the aggregator on purpose ("dead since dec95e9"). 008's `as_id` care for senders moves to the `stop_project` and follow-relay adopted-sender checks; verified under A-4. |
| `ControllerEngine.py` hunk 2 (arm watchdog message) | **Combine:** theirs' `f"{what} stalled…"` with ours' `_sorted_ids(pending)` | `sorted()` over `Uuid` raises (CLAUDE.md id rule) |
| `tests/test_controller_commands.py` ×2 (`project_status`) | **Take theirs** (`_loaded_script()`, `project_unix_name`, `set_status("load", …)`) and keep 008's uuid4 literal (`UUID_A` is one; confirm) | the three-state contract of item 11 |
| `tests/test_nodelist_modify.py` ×1 | **Take ours** (`adopted_network_map(...)` typed fixture) | `_adopted_uuids_from_network_map` no longer exists on the refactor; it became `_adopted_node_uuids` |
| `pyproject.toml` ×2 | **Take ours:** `version = "0.1.1"`, `cuemsutils = ">=0.1.1,<0.1.2"` with its comment, and the pyossia dev wheel | relation-matrix row 10; theirs' rc17 floor is subsumed per X-1. Add one comment line saying that `0.1.1` must contain rc17's `stop_project` |
| `src/cuemsengine/__init__.py` | **Ours** `__version__ = "0.1.1"`, **plus theirs'** added `SPDX-FileContributor: Ion Reguera` line | `test_version_single_source` |
| `debian/control` ×2 | **Ours** for every versioned `Depends` (rows 6–9, 25) and the explanatory comment; **theirs** for the SPDX header, the mock `Conflicts: cuems-audioplayer, cuems-dmxplayer` and the mock description's renamed binaries | Rule 4 plus relation rows. Theirs' `cuems-utils (>= 0.1.0rc17)` / `cuems-common (>= 1.0.0)` / `cuems-engine (>= 0.1.0rc2)` are the values the relation matrix replaced. |
| `debian/changelog` | §7.1 | — |
| The `origin/rc_1` merge (step 2) | **Ours** for its `0.1.0rc2` version sites and its `debian/` | Ancestry only; the content is already in |

## 6. Semantic seams (method A)

### 6.1 Measured: the merged tree versus `e994a5e`

**Environment.** pyenv 3.11.9 `.venv-016`, with `cuemsutils 0.1.1` installed **editable from the local
`../cuems-utils` checkout**. That checkout is 4 commits ahead of the tag (`923b7ff`), so the result
is indicative, not validation evidence. Real pyossia. `libmtcmaster.so.0` is absent on the host, so
`core/libmtc.py`'s raise was replaced by a `MagicMock` **in both arms**. CI's two passes ran.

| Arm | Unit (`-m "not integration" -n auto`) | Integration fast |
|---|---|---|
| `e994a5e` | 877 passed, **8 failed**, 1 xfail | 32 passed |
| merged tree (mechanical §5 resolution) | 1380 passed, **16 failed**, 1 xfail | 32 passed |

**The 8 failures common to both arms are environmental** (`test_comms_nodehub` ×6, a NNG/socket
sandbox issue; `test_port_handler::test_concurrent_draws_are_distinct`;
`test_pyossia_osc::test_osc_multiple_parameters`). They are not a reconciliation item. They must be
re-checked on a real host, where the 016 record shows 885 + 32 green.

**The 10 failures on the merged tree only**, each with its adaptation:

| Id | Failing test (owner) | Cause | Adaptation |
|---|---|---|---|
| A-1 | `test_action_cue.py::TestFadeActionsFromAVersion1Script::test_former_fade_out_is_stop_and_disarms_its_target` (008) | 869f8hfra made `disarm()` log a reason: the call is now `disarm(..., reason="stop_action")`; the test expects no kwargs | Update the 008 test's expected call to `reason="stop_action"`. This keeps 008's assertion that a version-1 `fade_out` becomes `stop`. |
| A-2 | `test_media_duration.py::test_run_sets_end_to_start_plus_converted_duration[video-…]` ×4 and `test_run_with_no_duration_is_zero_and_warned[video]` (008) | `run_videoCue` now calls `PLAYER_HANDLER.cue_media_dimensions(cue)` (869fat84r); the 008 test's player-handler mock returns no 2-tuple → `ValueError: not enough values to unpack` at `run_cue.py:509` | Give the 008 fixture a `cue_media_dimensions` return value of `(w, h)`, keeping 008's duration assertions intact. Add one test that a v2-loaded VideoCue with **absent** `pixel_*` falls back to the probe (R-1). |
| A-3 | `test_loop_video_wraparound.py::test_counted_loop_wraps_then_clamps_on_its_last_pass`, `::test_infinite_loop_keeps_wrapping` (rc_1, 869fa89uh) | The fixture's `media=SimpleNamespace(duration="00:00:10.000")` is a `str`; 008's `media_duration()` (explicit empty durations, CTimecode-typed) does not yield a usable duration from it, so `loop_videoCue` exits before any `/loop` send | Convert the fixture to the 008 shape (`CTimecode` duration, as `test_media_duration` builds it). **Do not** make `media_duration()` accept strings: 008 FR made the type explicit. |
| A-4 | `test_cluster_identity.py::test_script_finished_from_str_senders_closes_the_run` (008) | It tests the `script_finished` aggregator, which 869fhjdp8 deleted (`_finished_nodes` is gone) | **Retire the test** and record it in `specs/009-…/evidence/test-retirements.md`. **Replace it** with the same identity property on the surviving paths: a `stop_project` and a `follow` status op whose `sender` is a **`str`** uuid is accepted from an adopted node whose map id is a `Uuid`, and refused from a non-adopted one. |
| A-6 | `test_identity_sweep.py::test_an_editor_cue_id_as_str_matches_the_scripts_uuid_cue_id` (008) | 869fhjdq5 ignores cue ADD/UPDATE while not running; the 008 test never sets `running=yes` | Set `running="yes"` in the test's arrangement. Add the negative twin: with `running="no"` the ADD is ignored, with a `str` id. |

### 6.2 Found by reading, not by a failing test: conformance and risk

| Id | Where (merged tree) | Rule | Required |
|---|---|---|---|
| A-5 | `FollowRelay.py` (`"source": str(cue.id)`, `str(data.get("source"/"target"))`); `ControllerEngine._handle_stop_project` (`str(data.get("cue",""))`); `get_project_status` (`str(self.script.id)`); `NodeEngine.check_unrouted_video_outputs` (`"cue_id": cue.id`, raw); `NodeEngine` stop-project notify (`str(cue_id)`); `PlayerHandler` (`str(cue.id)` ×5, `"".join(str(cue.id).split("-"))`); `run_cue.py:235` (same slug) | CLAUDE.md "Ids": enter through `as_id`, leave through `id_str`; never `.split()` a raw id; no `src/` module imports `Uuid` | Mechanical: `str(x)` on an outgoing id → `id_str(x)`; incoming payload ids → `as_id(...)` before comparing with project ids; the slug → `"".join(id_str(cue.id).split("-"))`. `test_identity_sweep.py` gains one case per **wire-leaving** site: FollowRelay announce/cancel payloads, `stop_project` op, `project_status`, cue-name OSC address, unrouted-video report. Then the 008 audit (`specs/008-cuems-utils-migration/evidence/identity-audit.md`) is re-run over the merged `src/`. |
| R-1 | `PlayerHandler.cue_media_dimensions` / own-media check: `media.get("pixel_width")`, `media.get("file_size")` | utils 014 declares these `Unset` in `Media.DECLARED_DEFAULTS` | **Verify** what `.get()` returns on a v2-loaded `Media` with the element absent under `cuemsutils 0.1.1`. If it returns `Unset` rather than `None`, the "missing → probe" branch must treat `Unset` as missing (via cuemsutils' public helper, if any; otherwise an `is None or is Unset` check on the published symbol). Test with a **real** v2 script loaded through `CuemsScript.load`, not a dict. |
| R-2 | Cue-name walk `_collect_cue_names` (`hasattr(cuelist, "contents")`, `item.get("name")`) | 008 US2: v2 scripts and explicit empties | Test against a real v2 script that includes a CueList child and a cue with an empty `<name/>`. Expected: `""`. |
| R-3 | `ActionHandler` `stop_project` path versus 008's `ActionType` handling | 008 removed `fade_in`/`fade_out`; utils converts a v1 `fade_out` to `stop` | Confirm that `stop_project` is not caught by any "unknown action → reject" guard written by 008. The rc_1 test "other project actions still rejected" must stay green. |
| R-4 | `ControllerEngine._resolve_cluster_state` / `_collect_project_nodes` / the cluster warning | 008 typed-map read path (`_adopted_node_uuids`) versus rc_1's copies | The merge resolved cleanly to the refactor's helpers. Prove with one test that the stop_project and follow relays use **the same** adopted set as the GO gate. |

## 7. Packaging, versions, changelogs

### 7.1 `debian/changelog`

This follows the planning document's §10.1 shape. Order is by **dpkg version**, highest first:

```
cuems-engine (0.1.1-1) UNRELEASED       ← kept, body extended (below)
cuems-engine (0.1.0rc6-5) bookworm      ← verbatim from origin/debian/bookworm
… rc6-4, rc6-3, rc6-2, rc6-1            (verbatim, bookworm)
cuems-engine (0.1.0rc5-6) … rc5-2       ← verbatim from tag v0.1.0rc5-6 (§4.1 row 21)
cuems-engine (0.1.0rc5-1) … rc4-1, rc3-2, rc3-1   (verbatim, bookworm)
cuems-engine (0.1.0rc2-3) bookworm      ← kept (came from the rc_1 line, 2026-06-17)
cuems-engine (0.1.0rc2-2) … rc2-1 … rc1-1
```

- **Absorbed verbatim.** Entries are never rewritten or renumbered. Lintian may flag that `rc2-3`
  (dated Jun 17) sits below `rc3-1` (dated Apr 16). That is history and stays. `rc4-1`'s own text
  already explains it.
- The `0.1.1-1` body changes in three ways. **Replace** the "NOT YET RECONCILED" bullet with a
  "Reconciled with debian/bookworm at `<sha>` (0.1.0rc6-5): absorbs rc6-2..rc6-5" bullet that lists
  items 1–13 in a line each. **Add** the cuems-utils condition (X-1). **Keep** the poetry.lock bullet.
- `dpkg-parsechangelog -l debian/changelog -S Version` must still print `0.1.1-1`.

### 7.2 `CHANGELOG.md`: every released build present in the stable 0.1.1 changelog

**Rule.** The stable `0.1.1` changelog must list **every release that shipped before it**. Two
documents carry that history, and both must be complete:

- `debian/changelog` (§7.1): one entry per Debian build, verbatim.
- `CHANGELOG.md`: the upstream-facing history. HEAD's backfill (`56dbf9b`) is incomplete.

**Existing convention, measured on `e994a5e`.** There is one `## v<upstream>` header per upstream
version, dated by its first build. A `<!-- source: … -->` comment names the Debian revisions folded
under it:

| `CHANGELOG.md` section | Debian builds it must cover | State at `e994a5e` |
|---|---|---|
| `## v0.1.0rc6 — 2026-09-28` | `rc6-1`, **`rc6-2`, `rc6-3`, `rc6-4`, `rc6-5`** | ⛔ covers only `rc6-1` (source comment `7f6e475`) |
| `## v0.1.0rc5 — 2026-08-14` | `rc5-1`, **`rc5-2`, `rc5-3`, `rc5-4`, `rc5-5`, `rc5-6`** (hotfix line, §4.1) | ⛔ covers only `rc5-1` |
| `## v0.1.0rc4 — 2026-08-03` | `rc4-1` | ✅ |
| `## v0.1.0rc3 — 2026-04-16` | `rc3-1`, `rc3-2` | ✅ |
| `## v0.1.0rc2 — 2026-05-19` | `rc2-1`, `rc2-2`, `rc2-3` | to verify: `rc2-3` (the mock rsync shim, rc_1 line) is the one most likely missing |
| `## v0.1.0 — Initial release` | `rc1-1` | to verify |

**Required:**
1. **Extend `## v0.1.0rc6`** to cover `rc6-2…rc6-5`, following the convention. Use one
   `<!-- source: debian/bookworm 0.1.0rc6-N (<sha>) -->` comment per build, and put each build's
   content under the existing `Added` / `Changed` / `Fixed` sub-headers, with its build revision and
   date inline (for example "(0.1.0rc6-3, 2026-10-08)"). The content is items 1–13 of §4 and is
   taken from the Debian entries. A `-N` revision gets no top-level header of its own:
   `test_version_single_source.py` reads the top header, and the convention has none.
2. **Audit every older section** against the release line's `debian/changelog`, one build at a time.
   Fill any gap the same way. `rc2-3` and `rc1-1` are the two unverified rows.
3. **Rewrite the `## v0.1.1 — UNRELEASED` lead paragraph.** Its line 9 still says the release line
   "(0.1.0rc3-1 … 0.1.0rc6-5, including the `stop_project` ActionCue)" is *not* reconciled. It
   becomes: "Contains every change released in 0.1.0rc3-1 … 0.1.0rc6-5, absorbed from
   debian/bookworm at `<sha>`", followed by the X-1 condition.
4. `## v0.1.1` stays the top header, because `test_version_single_source.py` requires it to equal
   `__version__`.

### 7.3 `debian/control`, `debian/rules`, mock package

- Relations: rows 6–10 and 25 at their 016 values (§5).
- After the merge, re-run cuems-utils' `specs/016-coordinated-minor-bump/tools/verdicts.sh` for the
  engine rows. It must report **27/27** as in `relation-verdicts-progress-6.txt`. New evidence goes in
  `specs/009-…/evidence/`; never overwrite 016's.
- `debian/rules` must carry **all of these** after the merge:
  - `PIP_IGNORE_INSTALLED=1`, `PYTHONNOUSERSITE=1` and the rtmidi vendoring check (item 14)
  - the `cffi-gen-src` strip (item 15)
  - the renamed mock wrappers (item 16)
  - 016's changes (venv `home = /usr/bin`)
- **CACHEDIR.TAG (open, verify).** The planning document §10.2 says engine `rc4`/`rc5` debs shipped
  `/usr/lib/cuems/CACHEDIR.TAG`. cuems-utils (`rc16+1`) and power-bridge (`0.3.0-8`) strip theirs;
  bookworm's engine `rules` strips nothing. Build `0.1.1-1` and run `dpkg -c … | grep CACHEDIR`. If it
  is present, strip it the way the siblings do, so that every package agrees nobody ships it. Record
  the result either way.
- Build both debs in a bookworm chroot. This feature does not publish them. The evidence must show
  `Version: 0.1.1-1` and that mock `Depends: cuems-engine (>= 0.1.1)` and `Conflicts:` name both
  players.

### 7.4 Things that do not move

- `python3-pyossia (>= 2.0.0-rc6+124+cuems3)` and the dev wheel.
- `poetry.lock`: no relock; `test_lock_is_current` stays strict-xfail.
- `.venv/pyvenv.cfg` being tracked is out of scope, as 016 noted.

## 8. Sibling relations, from the `xml-refactor-merge-candidate` perspective

The engine reconciles first, so each line below is either **satisfied here** or **owed by a sibling**
and written to it as an upstream report under `specs/009-…/upstream-reports/`.

### 8.1 cuems-utils (hard prerequisites for publication, not for this feature's merge)

| Id | Obligation | Measured |
|---|---|---|
| **X-1** | `0.1.1` must carry rc17's **`stop_project`** in the **version-2** `script.xsd` `ActionType` enumeration and in the `ActionCue` docs. Otherwise a project with a stop_project cue is **refused at load** by every 0.1.1 cluster, and the editor cannot save one. | `origin/feat/xml-refactor` (cuems-utils) contains `stop_project` **only in docs and specs, not in `src/`**; `origin/debian/bookworm` has it at `script.xsd:279`, `ActionCue.py:20` |
| X-2 | Keep **`Replaces: cuems-engine (<< 0.1.0rc6-2~)`**. It licenses `cffi-gen-src` moving out of the engine for upgrades from engine `≤ rc6-1`. | present on utils' bookworm `debian/control:18`; **absent** on utils' `feat/xml-refactor`. It is not in 016's relation matrix, so add it as a new row there. |
| X-3 | `CACHEDIR.TAG` (utils `rc16+1`): utils stops shipping it. The engine's half is §7.3. | utils-side known; engine-side to verify |
| X-4 | `Media.pixel_width/pixel_height/file_size` semantics on a v2 load (`Unset` versus `None`), so that R-1 relies on a published contract | to confirm with the utils maintainers if R-1 finds `Unset` |

**Engine-side handling of X-1 (D1).** The rc_1 `stop_project` tests that build an `ActionCue` in code
pass on `0.1.1` today. Every test that goes through **XSD validation** (loading or saving a script
with `<action_type>stop_project</action_type>`) is written now and marked `xfail(strict=True,
reason="cuems-utils 0.1.1 lacks rc17 stop_project — upstream-reports/…")`. It turns XPASS, then red,
on the day utils absorbs rc17, so the obligation cannot be forgotten (the same pattern as
`test_lock_is_current`). The release notes and the tag message state the condition.

### 8.2 The other siblings: wire contracts this merge adds (all additive or cluster-wide)

| Contract (item) | Producer here | Consumer and where its half lives | Note |
|---|---|---|---|
| GO value is a **dict with `run_seq`**; `follow` status ops (7) | controller and node engines | **every engine in the cluster** | Not wire-compatible with a pre-rc6-3 engine. A cluster must not mix engine versions; that already holds, since every host upgrades to `0.1.1-1` together. State it in the release notes. |
| `project_status` = `running`/`loaded`/`none` + `project_unix_name` (11) | controller | cuems-power-bridge (`0.3.1-2`, on its `main`), cuems-editor | Additive. Power-bridge's 0.4.0-1 reconciliation absorbs its half. |
| `/engine/status/cue_name/<uuid>` (9) | controller `:9190` | cuems-frontend (`dev`) | Additive; older UIs ignore it |
| `stop_project` authored in UI (13) | — | cuems-frontend `dev` (STOP chips, PR #15), editor save path (via utils XSD, X-1), power-bridge `0.3.1-2` | Frontend `0.2.0` and power-bridge `0.4.0-1` reconciliations absorb their halves |
| `/engine/status/cluster_warning`, `nodelist_modify` | — | already paired before the merge-base (editor `0.1.0rc1-7`) | No change |
| `cuems-common (>= 1.3.1~)` | — | — | Nothing in rc6-2…rc6-5 touches units or `/etc/cuems`; unchanged |

**This feature changes no sibling's files.** It produces three things for them:
1. the upstream report to cuems-utils (X-1…X-4)
2. one note each for cuems-frontend, cuems-power-bridge and cuems-editor, naming the engine
   contracts above, so that their reconciliations can confirm their halves exist at their re-cut tags
3. the rewritten `../.xml-refactor-tag-messages/cuems-engine.txt` (§10)

## 9. Docs touched by the merge

- **CLAUDE.md.** It merges cleanly, but it now says `stop_project` "needs cuems-utils ≥ rc17". Rewrite
  that as "≥ 0.1.1, which must absorb rc17's value (cuems-utils reconciliation)". Check the merged file
  for leftover `script_finished` wording and for duplicated sections between 008's rc7 notes and
  rc_1's notes.
- **`docs/unattended-playback.md`**: `:77` ("cuems-utils ≥ 0.1.0rc17") and `:95` ("engine 0.1.0rc6-3 or
  later") → `0.1.1` / `0.1.1-1`. `docs/` is end-user only, so keep it free of dev-planning prose.
- `specs/008-…` is frozen history. Do not rewrite it. Record A-4's retirement in 009's evidence.

## 10. Acceptance criteria (for spec.md's success criteria)

1. `git rev-list --count HEAD..origin/debian/bookworm` = **0** and `git rev-list --count HEAD..origin/rc_1`
   = **0**, measured at hand-off against freshly fetched refs (re-merge if the line moved).
   The §4.1 sweep is re-run at hand-off and every row has a verdict. `35cbe78`, `d50ee4b`,
   `5a1811c` and `3c11c60` (or their rc_1 merges) are ancestors of HEAD. If the `-s ours` option of
   §12 Q6 is chosen, `v0.1.0rc5-6` is an ancestor too.
2. Every item in §4 is present. One test per item, named in an evidence table, passes on the merged
   branch. For items 1–13 these are the rc_1 tests that came with them.
3. The CI-equivalent suite (unit plus integration-fast) has **no failure that `e994a5e` does not also
   have**, on the same host. The 10 failures of §6.1 are fixed, not skipped. Run CI's two passes three
   times, interleaved, as 016 did.
4. Strict xfails are exactly: `test_lock_is_current` plus the X-1 XSD-dependent `stop_project` tests,
   each with the upstream-report path in its reason.
5. The identity audit re-run over the merged `src/` finds no raw `str()`/`sorted()`/`.split()` on an
   id leaving the process (A-5).
6. `black --check`, `isort --check` and `flake8 src/` are clean (CI lint).
7. Engine relation verdicts: **27/27**. Both debs build in bookworm with `Version 0.1.1-1`. The
   CACHEDIR.TAG check is recorded.
8. **Every released build is in the stable changelog**, checked mechanically:
   - `dpkg-parsechangelog` top = `0.1.1-1`.
   - The set of `cuems-engine (<version>)` headers in the merged `debian/changelog` ⊇ the set in
     `origin/debian/bookworm` ∪ `origin/rc_1` ∪ every `v0.1.0*` release tag (today `v0.1.0rc5-6`
     adds `rc5-2…rc5-6`). That is the §10.1 `comm -13` recipe returning **empty**, and it includes
     `rc2-3`.
   - Entries `rc3-1…rc6-5` are byte-identical to bookworm's, and `rc5-2…rc5-6` to `v0.1.0rc5-6`'s.
   - Every one of those Debian versions is named by a `<!-- source: … -->` comment (or an inline
     revision) in `CHANGELOG.md`.
   - `CHANGELOG.md`'s top is `v0.1.1`, the single-source version test passes, and the `v0.1.1` lead
     paragraph no longer says "not reconciled".
   - A small test or script performing these checks is part of the evidence (recommended: a test
     under `tests/`, so that a future release-line merge cannot drop a build silently).
9. `../.xml-refactor-tag-messages/cuems-engine.txt` is rewritten:
   - `Tag:` points at the new `feat/xml-refactor` head after the 009 `--no-ff` merge
   - the "NOT YET RECONCILED" section is replaced by "Reconciled with origin/debian/bookworm at
     `<sha>` (0.1.0rc6-5)" and the X-1 condition
   - the "Carries" list gains items 1–13
   - the "Pairs with" list is unchanged
   - the maintainer re-cuts the tag; this feature does not
10. The upstream reports (§8) exist, and the cuems-utils report is linked from the cuems-utils
    planning document's "still owed" list. That link is an edit in cuems-utils, so it goes to its
    maintainer.
11. The cleanup-phase acceptance of §14.6 holds.

## 11. Execution order (seed for tasks.md)

1. Fetch. Re-measure §2 (counts, new release-line entries via the §10.1 `comm` recipe). Update this
   table if the line moved.
2. Create `009-release-line-reconciliation` off `feat/xml-refactor`. Run the baseline suite on it
   (arm A).
3. Merge `origin/debian/bookworm` with the §5 resolutions. Commit. Run the suite and record the red
   set; expect §6.1's 10.
4. Merge `origin/rc_1` (ancestry). Commit. Then merge, by SHA, any §4.1 branch head (22–24) that
   rc_1 has not taken yet. Copy the rc5-2…rc5-6 changelog entries (row 21).
5. Adaptations A-1…A-6 and R-1…R-4, TDD, one commit each.
6. Write the X-1 strict xfails and the upstream report.
7. Packaging: changelogs (§7.1–7.2), the rules audit, the CACHEDIR check, the bookworm build,
   verdicts.
8. Docs (§9).
9. Re-fetch. If the line moved, merge again (loop to 3 for the delta). Run the full suite (arms A/B
   ×3) and the lint.
10. **Cleanup phase** (§14), one commit per sub-section (14.1 `dev/`, 14.2 `scripts/`, 14.3
    `tests/` + CI, 14.4 strays). Pure moves and deletes; run the suite after each commit and confirm
    the pass set is unchanged.
11. Rewrite the tag message. Hand off: the `--no-ff` merge into `feat/xml-refactor` and the tag
    re-cut are maintainer acts.
12. **Final task: delete this planning file** (`git rm specs/planning/release-line-reconciliation-0.1.1.md`).
    First verify that every section is traceable from `specs/009-release-line-reconciliation/`: FRs or
    SCs for §4–§10 and §14, research for the open items, evidence for §6.1 and §13. Then
    `git grep -n release-line-reconciliation-0.1.1 -- . ':!specs/009-*'` must return nothing; re-point
    any hit to the 009 spec first. 009 links to the file's last commit, so the history stays reachable.

## 12. Open questions for `/speckit-clarify`

1. `CHANGELOG.md` (§7.2): confirm the recommended layout, which folds `rc6-2…rc6-5` into
   `## v0.1.0rc6` following the existing source-comment convention. Should the §10 criterion-8
   completeness check be a permanent test (recommended) or a one-off evidence script?
2. If the CACHEDIR check finds the engine shipping `/usr/lib/cuems/CACHEDIR.TAG`: strip it in this
   feature (recommended; it is a cross-package overwrite class) or record it and defer?
3. A-5's scope. Convert **every** `str(id)` in absorbed code (recommended, since the audit is
   mechanical), or only the wire-leaving sites?
4. If utils' reconciliation lands rc17 before this feature finishes: drop the X-1 xfails inside 009,
   or leave that to a follow-up?
5. Is a mixed-version cluster during a rolling upgrade ever expected? The `run_seq` GO dict (item 7)
   says no; confirm so the release note can say "upgrade every host together".
6. The hotfix line (§4.1 row 21): copy the five changelog entries only, or also record ancestry
   with `git merge -s ours v0.1.0rc5-6`? Ancestry is recommended: the code equivalence is
   evidenced, and future sweeps stop reporting 62 "unmerged" commits.
7. Confirm that `0.1.0rc6-3+nodeadopt2` (a rig build) stays out of the changelog.
8. Branches 22–24: include them even if their PRs are still unreviewed on rc_1 when 009 starts
   (recommended for `35cbe78`, the silent-audio bug, and for `d50ee4b`), or wait for rc_1?
9. Cleanup (§14): which developer tools have rig users? `osc_send.py` and one of the two
   `kill_cuems` implementations are kept by default, moved to `scripts/dev/`; anything nobody uses is
   deleted. (The CI change is in scope: answered by D5.)
10. Cleanup (§14.3): split `test_port_handler.py`, so that only the concurrent-draws case is
    integration, or move the whole file?

## 13. How this was measured (reproducible)

```bash
git fetch --all --tags
git rev-list --count HEAD..origin/debian/bookworm    # 119
git rev-list --count HEAD..origin/rc_1               # 84
git diff --stat origin/rc_1 origin/debian/bookworm -- src tests docs CLAUDE.md   # __init__.py only
git merge-tree --write-tree HEAD origin/debian/bookworm   # 7 conflicted files
# trial: scratch worktree, mechanical §5 resolution, libmtc stub in both arms,
# .venv-016 → CI's two pytest passes (results in §6.1)
```

## 14. Final phase: repository cleanup for the first stable release

0.1.1-1 is the first real stable release, so 009 ends with a cleanup phase. It deletes, relocates or
rewrites anything that has lost its meaning, is unused, or is half-built. It also gives `tests/` the
same unit/integration layout cuems-utils already uses. **It runs last, after the final re-fetch and
re-merge (§11 step 9),** for two reasons: moving files before the release-line merge would turn
clean merges into rename conflicts, and the merge brings about 25 new test files (plus
`mock_jack.py` and `mock_nodeconf.py`) that the cleanup has to cover. **No behaviour change:** each
commit is a pure move, delete or rewire, and the suite stays at the same pass set.

All findings were swept 2026-10-17 on `e994a5e` plus the merge-tree of `origin/debian/bookworm`. A
"live reference" is a path-qualified hit in `src/`, `tests/`, `debian/`, `.github/`, `pyproject.toml`
or the docs. `specs/` is frozen history and does not count.

### 14.1 `dev/`: delete almost all of it

| Path | What it is | Live references | Verdict |
|---|---|---|---|
| `dev/CuemsEngine.py`, `dev/CuemsEngine_old.py` | The pre-split monolithic engine, superseded by `ControllerEngine` / `NodeEngine` | none (specs only) | **delete** |
| `dev/AudioPlayerRemote.py`, `VideoPlayerRemote.py`, `NodeAudioPlayers.py`, `NodeVideoPlayers.py` | 2025-02 prototypes of the player layer, superseded by `players/` | none | **delete** |
| `dev/NodeControl.score` (4418 lines) | An ossia score document from 2025-02 | none | **delete** (keep it outside the repo if anyone still opens it in score) |
| `dev/cuems-engine.service` | A unit for `cuems-engine.service`, which **CLAUDE.md says does not exist**. The real units are owned by cuems-common | none | **delete**: it is actively misleading |
| `dev/network_map.xsd` | A 2025 copy of a schema that cuems-utils owns (0.1.1 ships the versioned one) | none path-qualified | **delete**: a stale schema copy is a second source of truth |
| `dev/display.py` | An Xlib randr probe snippet (18 lines) | none | **delete** (`tools/display_conf.py` is the real path) |
| `dev/editor-engine-commands.txt` | Informal notes on the editor↔engine protocol, 2025 | none | **delete**. If any of it is still true, it belongs in `controller-integration-contracts.md` |
| `dev/diagnose_env_output.txt` | Captured output from one machine (2025-05) | none | **delete** |
| `dev/test_cleanup_demo.py` | A demo of the cleanup fixtures; says "Run this with: pytest tests/test_cleanup_demo.py" | none | **delete**, together with `tests/pytest_cuems_plugin.py` (§14.4) |
| `dev/test_pyossia_gmq.py`, `test_pyossia_midi.py`, `test_pyossia_without_daemon.py` | 2024 investigation scripts with hard-coded `/home/stagelab/src/...` paths | none | **delete**: their findings are already recorded in `specs/planning/PYOSSIA_EVALUATION_RESULTS.md`, and that document is the record. Add one line there naming the deleted scripts and their last commit. The `test_*` names are a trap: they look like tests and are not collected (`testpaths = ["tests"]`) |
| `dev/scripts/change_to_{firstrun,master,slave}.sh` | Copy `cuems.service.{firstrun,master,slave}` into avahi | none | **delete**: retired `master`/`slave` vocabulary, and those service files are retired in cuems-common 1.3.1 |
| `dev/scripts/kill_cuems.sh` + `kill_cuems_processes.py` | Two implementations of the same escalating process killer (≈257 lines each) | none | **keep one** as `dev/scripts/kill_cuems.sh` (the shell one needs no venv). Re-check it against the binary names fixed by 869evtdf7 (`cuems-audioplayer`, own-user only), or delete both if nobody uses them (§12 Q9) |
| `dev/scripts/diagnose_env.py` | Prints poetry/venv/site info | none | **delete** (`poetry env info` does this) |
| `dev/scripts/run_cpu_tests.py` | Wrapper around `test_cpu_usage.py` | `specs/planning/README_CPU_TESTS.md` | **delete**, and replace it with one documented `pytest tests/integration/test_cpu_usage.py -m slow` line |
| `dev/scripts/link-dev.sh` | Symlinks the source tree over `/usr/lib/cuems` (the `cuemsengine.pth` dev overlay) | README:243, CONTRIBUTORS:69 and the constitution :122/:139 all call it **`scripts/link-dev.sh`**, a path that does not exist | **keep, and move it to `scripts/dev/link-dev.sh`** (§14.2). Fix all four references. The constitution edit is a PATCH amendment through `/speckit-constitution` |
| `dev/test_json_files/test1.json` | A 2025 JSON fixture | none (the `/test1` hit in `test_ossia.py` is an OSC path) | **delete** |
| `dev/test_xml_files/test_jsons.txt` | 2020 JSON scratch notes with pasted code | none | **delete** |
| `dev/test_xml_files/{settings,network_map,default_mappings,project_mappings,project_settings}.xml`, `projects/*/script.xml` | **Live test fixtures** (008 and 014 converted them) | `tests/fixtures.py` (×3), `tests/network_map_helpers.py`, `tests/test_action_cue.py`, and by name in about 15 tests | **move** to `tests/data/` (§14.3) |
| `.gitignore` `dev/test_xml_files/media/`, `dev/local/` | Ignore rules for the fixture media and local scratch | — | re-point to `tests/data/media/`. `dev/local/` goes, since `dev/` goes |

**After the cleanup, `dev/` no longer exists.** Everything that survives moves to `scripts/dev/`
(tools) or `tests/data/` (fixtures). A directory named `dev/` that is half fixtures and half archive
is exactly what makes "is this used?" unanswerable.

### 14.2 `scripts/`: one home for developer tools that are not shipped

| Path | Verdict |
|---|---|
| `scripts/osc_send.py` | A 35-line pythonosc one-shot sender (`osc_send.py <path> <value> [--ip --port]`). No test or fixture uses it; the `osc_send` hit in `test_fade_action_handler.py` is a test *name*. It is a useful manual tool for poking `:9000`-style endpoints on a rig. **Move it to `scripts/dev/osc_send.py`.** Not a fixture: tests that need to send OSC already have `SimpleUDPClient` inline or through `fixtures.py`, and a CLI with `argparse` is the wrong shape for a fixture. Retire it instead if nobody uses it on rigs (§12 Q9). |
| `scripts/dev/` (new) | Holds `link-dev.sh`, `osc_send.py`, and (if kept) `kill_cuems.sh`. It gets a 10-line `README.md` saying what each tool is for and that **nothing here is packaged or run by CI**. This mirrors the shipped/unshipped split: `src/cuemsengine/scripts/` holds packaged entry points, top-level `scripts/` holds developer tools. |

### 14.3 `tests/`: a cuems-utils-style layout, marked by directory

**Problem, measured.** 79 test modules sit flat in `tests/` (post-merge). Only 7 carry
`@pytest.mark.integration`. CI's unit pass is `-m "not integration" -n auto`, so anything unmarked
runs as a parallel unit test. **The 8 sandbox failures of §6.1 are exactly such files:**
`test_comms_nodehub` (real NNG sockets), `test_port_handler::test_concurrent_draws_are_distinct`
(real binds) and `test_pyossia_osc` (real pyossia devices). They are integration tests that are
labelled unit by omission. Three `testdev_*.py` files are never collected, because `python_files`
does not match them. Measured on `e994a5e`: 3 passed, 6 failed, 2 errors, 35 s, so nobody has been
running them.

**Target layout.** It is the convention cuems-utils' `feat/xml-refactor` already has (`tests/contract
data golden integration packaging support unit`), so a contributor sees one shape across the
ecosystem:

```
tests/
  conftest.py            # shared fixtures + auto-marking by directory (below)
  support/               # helpers.py, fixtures.py, network_map_helpers.py, reader.py,
                         #   paths.py (DATA_DIR — the ONE place the data path is written)
  data/                  # ← dev/test_xml_files/* (settings, network_map, mappings, projects/…)
  unit/                  # pure logic; mocks for every socket/JACK/subprocess; xdist-safe
  integration/           # opens a real socket, NNG pipe, pyossia device, UDP port, subprocess,
                         #   or waits on wall-clock time
  contract/              # repository/packaging invariants: test_public_surface, test_version,
                         #   test_version_single_source, test_lock_is_current,
                         #   test_default_mappings_valid, + §10 criterion-8 changelog test
```

**The classification rule** goes in `tests/README.md` and `CONTRIBUTORS.md`. A test is
**integration** if it binds or connects a real socket (NNG, UDP, TCP, an OSCQuery or pyossia device),
starts a real subprocess or player, touches JACK or ALSA, or relies on `sleep` ≥ 0.5 s for
correctness. Otherwise it is **unit**. A unit test that needs one of those things mocks it.

**Initial split, from the post-merge sweep** (signals: real `pynng`/`NodesHub`, pyossia factories,
`SimpleUDPClient`/sockets, free-port helpers, unpatched `subprocess`, long sleeps). Verify each file at
move time:

| Destination | Files |
|---|---|
| `integration/` | `test_comms_nodehub`, `test_ossia`, `test_ossia_bundle_support`, `test_pyossia_osc`, `test_pythonosc`, `test_port_handler` (or split: only the concurrent-draws case binds), `test_project_load`, `test_project_go` (slow), `test_cpu_usage` (slow), `test_core_baseengine`, `test_cuems_deploy_integration`, `test_gradient_client` (check whether its UDP is real) |
| `contract/` | `test_public_surface`, `test_version`, `test_version_single_source`, `test_lock_is_current`, `test_default_mappings_valid` |
| `unit/` | everything else (about 60 modules, including all rc_1 additions: `test_arm_*`, `test_cross_node_follow_*`, `test_controller_stop_project`, `test_video_unrouted_output`, …). Note: `test_cuems_deploy`, `test_players_audiomixer` and `test_node_engine_load_orphan_eperm` / `test_player_handler_orphan_kill` showed `sleep`/`subprocess` signals. Confirm they are patched; if not, either mock them or move them |
| **retire** | `testdev_engines_communication.py`, `testdev_ossia_oscquery.py`, `testdev_ossia_queue.py`. Move any of their 3 passing cases into `integration/` only if no existing test covers the same behaviour. Delete the rest and record it in `evidence/test-retirements.md` |

**Wiring:**
- **Markers from directories, not by hand.** A `pytest_collection_modifyitems` hook in the root
  `conftest.py` adds `unit` / `integration` / `contract` from the path, so a test cannot be
  mislabelled by forgetting a decorator. Keep `slow` as an explicit mark. Drop the unused `cuems`
  marker, together with the plugin. `--strict-markers` stays.
- **CI runs three parallel jobs instead of two sequential steps:**
  - `unit + contract`: `pytest tests/unit tests/contract -n auto`, with coverage
  - `integration`: `pytest tests/integration -m "not slow"`, serial or `--dist loadgroup`, with
    free-port helpers
  - a `coverage` job that combines the artifacts and keeps `--cov-fail-under=45` on the **combined**
    number, so splitting cannot move the gate
- **Imports.** A single `tests/support/paths.py:DATA_DIR` replaces the five hand-built
  `Path(__file__).parent / ".." / "dev" / "test_xml_files"` expressions (`fixtures.py` ×3,
  `network_map_helpers.py:22`, `test_action_cue.py:430`). Delete the two commented-out copies in
  `fixtures.py` (:430, :458). Fix `from .conftest import engine_cleanup` in `test_project_go.py`:
  importing from `conftest` is a pytest anti-pattern, because fixtures resolve by name. Keep
  `tests/__init__.py` packages, adding one per subdirectory, so the existing relative imports keep
  working.
- **Bookkeeping.** `pyproject.toml` `[tool.pytest.ini_options]`: `testpaths = ["tests"]` stays;
  `python_files` is unchanged once `testdev_*` is gone.

### 14.4 Other stale items found in the sweep

| Path | Finding | Verdict |
|---|---|---|
| `src/cuems/ComunicatorServices.py` | A whole stray top-level package. Not packaged (`packages = [{include="cuemsengine"}]`), imported by nothing; cuemsutils ships `tools.CommunicatorServices`, which the code uses | **delete** |
| `src/cuemsengine/scripts/system_ports.py` | A near-copy of `tools/system_ports.py` (50 vs 64 lines). Nothing imports it and no entry point names it; `PortHandler` imports the `tools/` one | **delete** |
| `src/cuemsengine/players/VideoPlayer.py` | Dead | already deleted by the merge (869f8v8yv, item 2); check that no doc still names it |
| `tests/pytest_cuems_plugin.py` (190 lines) | A cleanup plugin that is never registered (no `pytest_plugins`, no entry point). `conftest.py` has its own `engine_cleanup` | **delete**. Fold whatever is still true of `specs/planning/README_CLEANUP.md` (46 references to the plugin and demo) into `CONTRIBUTORS.md`'s testing section, then delete that README |
| `specs/planning/README_CPU_TESTS.md` | Documents `run_cpu_tests.py` | Rewrite it to the plain pytest line, or fold it into `CONTRIBUTORS.md` |
| `.venv/pyvenv.cfg` (tracked) | `.gitignore` both un-ignores it (`!.venv/pyvenv.cfg`) **and** ignores it again (last line), yet it is tracked; 016 flagged it out of scope | **untrack it** (`git rm --cached`) and keep only the ignore rule. A venv config pins one machine's interpreter path |
| `.gitignore` | Missing `.venv-*/`, `.ruff_cache/`, `.016-native/`, `/__pycache__` at the root; `.coverage*` is present | add them |
| Mock entry points `src/cuemsengine/scripts/mock_*.py` (+ `mock_jack.py`, `mock_nodeconf.py` after §4.1) | They ship inside the production `cuems-engine` venv, although only `cuems-engine-mock` uses them | **leave in place for 0.1.1** (YAGNI): moving them changes the `python -m` paths in `debian/mock-scripts/*` and the drop-ins, for no runtime gain. Record it as a known wart for 0.1.2 |

### 14.5 CI: the pre-publication gate, run manually in the cloud (D5)

**Measured constraints:**
- **`workflow_dispatch` only works for workflow files that exist on the default branch.** The default
  branch is **`main`**, not `master`: `git remote show origin` → `HEAD branch: main`. The local
  `origin/HEAD → origin/master` is stale; repair it with `git remote set-head origin -a`. `main`'s
  `.github/workflows/ci.yml` already declares `workflow_dispatch`, so
  `gh workflow run ci.yml --ref <009 or feat/xml-refactor>` runs **the ref's version** of the file.
  ⇒ **Keep the file name `ci.yml` and restructure the jobs inside it.** A new workflow file (for
  example `release-gate.yml`) could not be dispatched until it reached `main`, and 009 never touches
  `main`.
- **Triggers.** `push` / `pull_request` cover only `[main, rc_1]`. Add **`feat/xml-refactor`** to
  both, so PRs into the integration branch (009 included) run the same jobs. Dispatch stays the
  release gate.
- **`cuemsutils` cannot come from PyPI** (0.1.1 is unpublished; rule 5). Install it from a cuems-utils
  git ref given as a dispatch input: `cuemsutils_ref`, defaulting to the cuems-utils
  `xml-refactor-merge-candidate` tag. Command: `pip install "cuemsutils @
  git+https://github.com/stagesoft/cuems-utils@${ref}"`. Use the same value for push/PR runs. The
  job logs the resolved commit (`git ls-remote`) and `cuemsutils.__version__`, so every run states
  which library it validated against.
- **The stale lock (FR-022).** `poetry.lock` still resolves `cuemsutils 0.1.0rc16` while
  `pyproject.toml` says `>=0.1.1,<0.1.2`. **Research for /speckit-plan:** does Poetry 2.4.1 refuse
  `poetry install` on that mismatch? If it does, the job installs the locked dev group without the
  root package's resolution of `cuemsutils` (or re-locks inside the job only, never committed), then
  installs `cuemsutils` from the ref. Choose the variant that keeps every *other* dependency at its
  locked version. `test_lock_is_current` stays strict-xfail, so the committed lock is still flagged.
- **The X-1 interaction.** Until utils' reconciliation re-cuts its tag with rc17's `stop_project`, the
  gate runs against a utils that lacks it. The X-1 strict xfails are what make that run green and
  honest. Re-dispatching after utils' re-cut turns them XPASS-strict, i.e. red, which is the signal to
  drop them.
- **Native libraries are already handled:** libmtcmaster `v0.0.2-0`, librtpmidid and librtmidi6 come
  from the existing steps, and pyossia from the pinned wheel.

**Job layout** (inside `ci.yml`):

| Job | Needs | Runs | Notes |
|---|---|---|---|
| `lint` | — | `black --check`, `isort --check`, `flake8 src/` | unchanged |
| `unit` | lint | `pytest tests/unit tests/contract -n auto --cov` | no network; uploads `.coverage.unit` |
| `integration` | lint | `pytest tests/integration -m "not slow" --cov` | runs in parallel with `unit`; uploads `.coverage.integration`. The real sockets, NNG and pyossia here work on a hosted runner, unlike in the agent sandbox |
| `coverage` | unit, integration | `coverage combine` + `report --fail-under=45` + badge | the 45 % gate applies to the **combined** number |
| `gate-summary` | all | writes the job summary: engine SHA, `cuemsutils` ref and commit, pass/xfail counts, the list of strict xfails | this is the record evidence links to |

`slow` tests (`test_cpu_usage`, `test_project_go`) stay out of the hosted run, as today: they are
unreliable on a runner. They are run by hand on a rig, and the evidence says so.

**Badge / gh-pages.** `gh-pages.yml` triggers on `workflow_run` of CI for `[master, rc_1]`. A dispatch
on 009 must **not** push the coverage badge: gate the badge step on
`github.ref == 'refs/heads/main' || github.ref == 'refs/heads/rc_1'`.

**The gate itself.**
- **Before 009 hands off:** one dispatched run on the 009 head SHA must be green, with
  `cuemsutils_ref` set to the current utils candidate tag. Record the run URL, SHA and summary in
  `specs/009-…/evidence/ci-gate.md`.
- **Before publication:** another dispatched run on the post-merge `feat/xml-refactor` head, with
  `cuemsutils_ref` set to utils' **reconciled** re-cut tag. This is a maintainer act, after 009, and
  it gates `pypi-publish.yml` (triggered on a GitHub release) and the `.deb` upload.
- Write the pre-publication checklist line into the tag message and into `CONTRIBUTORS.md`'s release
  section.

### 14.6 Acceptance for the cleanup phase

- `dev/` does not exist; `scripts/dev/README.md` lists every surviving tool.
- `git grep -nE "dev/test_xml_files|test_json_files|scripts/link-dev|pytest_cuems_plugin|CuemsEngine_old" -- . ':!specs'`
  returns **nothing**.
- No `tests/test_*.py` remains at the root of `tests/`. Every collected test lives in `unit/`,
  `integration/` or `contract/` and carries exactly one of those markers (assert this in a small
  contract test over the collection).
- `pytest tests/unit tests/contract -n auto` passes **without network**. The sandbox that produced
  §6.1's 8 environmental failures now produces 0 there, because all 8 moved to `integration/`.
- The pass set before and after the cleanup is identical, apart from retired tests, which are listed
  in evidence with their reason. Combined coverage is ≥ 45 %.
- `ci.yml` (same file name) has the §14.5 jobs and the `cuemsutils_ref` dispatch input. A
  **`workflow_dispatch` run on the 009 head SHA is green**, and its URL, the engine SHA, the
  `cuemsutils` ref and commit, and the xfail list are in `evidence/ci-gate.md`. A dispatch on a
  non-`main`/`rc_1` ref does not push the badge. `black` / `isort` / `flake8` are clean on the moved
  paths.
- README, CONTRIBUTORS, the constitution (PATCH amendment) and CLAUDE.md name the new paths.
- **Tell the rc_1 developers about the new layout.** The release line keeps adding tests at
  `tests/` root, and every future reconciliation merge has to re-file them. A short note in the
  `CONTRIBUTORS.md` testing section, plus a message to the rc_1 maintainer, is part of the hand-off.

---

## Appendix A — paste-ready `/speckit-specify` prompt

> Feature `009-release-line-reconciliation` for cuems-engine. Branch off `feat/xml-refactor`
> (`e994a5e`, the `xml-refactor-merge-candidate` commit, version 0.1.1-1 UNRELEASED). Absorb the
> engine's release line `origin/debian/bookworm` (`b8431a3`, 0.1.0rc6-5) and `origin/rc_1`
> (`698e777`) into the refactor before 0.1.1-1 is published ("merge before bump", rule 4 of
> cuems-utils `specs/planning/coordinated-release-version-bump.md`), so that nothing shipped in
> 0.1.0rc3-1…rc6-5 is lost, and so that the absorbed code obeys feature 008's contract (typed node
> map, `as_id`/`id_str` identity rules, version-2 scripts, no fade_in/fade_out handlers). The work
> order is `specs/planning/release-line-reconciliation-0.1.1.md`. Use its decisions D1–D4, its
> inventory (§4: 20 items, each with a method of merge / conflict-resolution / adaptation, cherry-pick
> for none), its stray-head sweep (§4.1: the released-but-unabsorbed 0.1.0rc5-2…rc5-6 hotfix
> changelog entries; the unmerged 2026-10-15 branches `35cbe78` silent-audio output-map fix,
> `d50ee4b` mock JACK readiness, and `5a1811c`/`3c11c60` mock nodeconf needing re-implementation on
> the 0.1.1 public API), its conflict rules (§5), its measured semantic seams (§6: 10 tests red on the merged tree,
> adaptations A-1…A-6, risks R-1…R-4), its packaging and changelog shape (§7), its sibling
> obligations (§8; X-1 = cuems-utils 0.1.1 must carry rc17's `stop_project` in the v2 script.xsd,
> engine-side tests that need it are strict xfails), its acceptance criteria (§10, including §14.6) and its execution
> order (§11). Its final phase is the first-stable-release cleanup (§14): delete `dev/` (superseded
> engines and prototypes, the misleading `cuems-engine.service`, the stale `network_map.xsd`, the
> pyossia investigation scripts whose findings live in PYOSSIA_EVALUATION_RESULTS.md, the retired
> master/slave scripts); move the live fixtures to `tests/data/` behind one `DATA_DIR`; move the kept
> developer tools (`link-dev.sh`, `osc_send.py`) to `scripts/dev/`, fixing the broken `scripts/link-dev.sh`
> references in README, CONTRIBUTORS and the constitution; delete the stray `src/cuems/` package,
> the duplicate `scripts/system_ports.py`, the unregistered `pytest_cuems_plugin.py` and the
> uncollected `testdev_*.py`; untrack `.venv/pyvenv.cfg`; and re-lay `tests/` as cuems-utils does
> (`unit/`, `integration/`, `contract/`, `support/`, `data/`), marked by directory, with CI split
> into parallel unit and integration jobs and coverage combined. Pure moves; the pass set is
> unchanged. The CI restructure is in scope (D5, §14.5). It is the pre-publication gate, run manually
> in the cloud with `workflow_dispatch`. Keep the file name `ci.yml`: dispatch needs the file on the
> default branch `main`. Add a `cuemsutils_ref` input that installs cuemsutils from the cuems-utils
> candidate tag instead of PyPI; resolve the stale-lock install path during planning; add
> `feat/xml-refactor` to the push/PR triggers; keep dispatches on other refs from pushing the badge;
> and record a green dispatched run on the 009 head SHA as evidence. The final task of tasks.md
> deletes this planning file once the 009 artefacts carry all of its content (§11 step 12). Treat
> §12 as the clarify list. Out of scope: publishing, the poetry.lock relock, CI
> green, sibling edits, tag moves, new behaviour. The version stays 0.1.1-1. Constitution: TDD
> (every adaptation starts from a red test), SOLID, YAGNI, no new runtime dependency, structured
> logging. Planning artefacts go under `specs/009-release-line-reconciliation/`, evidence under its
> `evidence/`, and upstream reports under its `upstream-reports/`.
