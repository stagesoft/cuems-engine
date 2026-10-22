<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Feature Specification: Release-line reconciliation before 0.1.1-1

**Feature Branch**: `009-release-line-reconciliation`, created off `feat/xml-refactor` at `945ccba`.
That commit is `e994a5e` (the `xml-refactor-merge-candidate` commit, `0.1.1-1` UNRELEASED) plus one
docs commit that adds the work order. Nothing else differs.
**Created**: 2026-10-17
**Status**: Clarified 2026-10-17; analysed 2026-10-18 (`/speckit-analyze`, remediated)
**Work order**: `specs/planning/release-line-reconciliation-0.1.1.md` (pre-spec, written 2026-10-17
at `e994a5e`). Work order last commit: `945ccba5aff30f09e5c937ff6fe73e26e8372c02`. This spec cites its sections as **WO §n**. The final task of 009 deletes that file
(FR-060), so every section it contains must be traceable from this directory first. See
[Traceability](#traceability-to-the-work-order).
**Input**: User description: "Feature `009-release-line-reconciliation` for cuems-engine. Branch off
`feat/xml-refactor` (`e994a5e`) … absorb `origin/debian/bookworm` (`b8431a3`, 0.1.0rc6-5) and
`origin/rc_1` (`698e777`) into the refactor before 0.1.1-1 is published ('merge before bump') …
followed by the first-stable-release cleanup (WO §14) and the pre-publication CI gate (D5)." (full
prompt: WO Appendix A)

## Context

`0.1.1-1` will be the engine's first stable release. It was cut on `feat/xml-refactor`, which branched
from the release line on 2026-09-28 at `956a0f3`. The release line kept shipping after that point:
`0.1.0rc6-2` through `0.1.0rc6-5` on `debian/bookworm` (code from `rc_1`), and the `0.1.0rc5-2` through
`rc5-6` hotfix builds, which neither line ever absorbed. If `0.1.1-1` is published as it stands, every
fix in those builds disappears from the fleet on upgrade. Among them are the `stop_project` ActionCue,
the cross-node Auto follow relay, the audio ready gate, the three-state `project_status`, and the
orphan-kill hardening.

Rule 4 of the coordinated release ("merge before bump",
`cuems-utils/specs/planning/coordinated-release-version-bump.md`) therefore requires the release line
to be merged **under** the `0.1.1-1` bump that already exists. cuems-engine is the first of the seven
repositories to reconcile, so this feature also writes down what the siblings owe it.

Merging is not enough. The absorbed code was written against the pre-008 library, so it must obey
the feature-008 contract:

- the typed node map (`NodeRole`, typed `adopted`)
- the identity rules (ids enter through `as_id` and leave through `id_str`)
- version-2 scripts
- no `fade_in`/`fade_out` handlers

### Decisions already taken (maintainer, 2026-10-17)

| # | Decision |
|---|---|
| **D1** | `stop_project` lands **in full**, on condition that cuems-utils' own reconciliation puts rc17's `stop_project` into `0.1.1` (X-1). Until it does, every engine test that needs the XSD value is a **strict xfail** that names the upstream report. |
| **D2** | The planning session wrote no code. This feature implements. |
| **D3** | This branch holds the merges and the adaptations. It merges back into `feat/xml-refactor` with `--no-ff`. The **maintainer** performs that merge and re-cuts the candidate tag. Agents never move tags. |
| **D4** | The version **stays `0.1.1-1`**. The top changelog entry grows; it is not renumbered. |
| **D5** | The CI restructure is part of 009. The restructured `ci.yml` is the **pre-publication gate**, dispatched manually in the cloud (`workflow_dispatch`). |

### Measured state at specification time (WO §2, §3, §6.1; re-checked 2026-10-17 on this branch)

| # | Finding | Consequence |
|---|---|---|
| **M1** | `HEAD..origin/debian/bookworm` = **119**, `HEAD..origin/rc_1` = **84**. Merge-base of all three lines: `956a0f3`. | The measurable form of rule 4 is "both counts reach 0" (SC-001). |
| **M2** | `rc_1` ⊂ `debian/bookworm` in content. They differ only in `src/cuemsengine/__init__.py`, the version string. | Bookworm is the vehicle. The rc_1 merge only adds ancestry. |
| **M3** | The code of `rc3-1 … rc6-1` is already here, through `956a0f3`. New code arrives only from `rc6-2 … rc6-5`. | For older builds only the changelog text is absorbed. |
| **M4** | A trial `git merge --no-ff origin/debian/bookworm` into `e994a5e` conflicts in **7 files**: `debian/changelog`, `debian/control` ×2, `pyproject.toml` ×2, `__init__.py`, `ControllerEngine.py` ×2, `tests/test_controller_commands.py` ×2, `tests/test_nodelist_modify.py`. | Resolution rules: FR-004. |
| **M5** | With a mechanical resolution, the merged tree fails **10 tests that pass on `e994a5e`**. Both arms share 8 further failures, which are environmental (NNG and socket sandbox, real binds, real pyossia). | Adaptations A-1…A-6 (FR-010…FR-015). The 8 are an argument for the test re-layout (FR-047). |
| **M6** | Five released builds, `0.1.0rc5-2 … rc5-6` (tag `v0.1.0rc5-6` = `69e91e4`), are on neither line. Every code commit in them maps to an `rc_1` commit that is already in scope (WO §4.1 row 21 equivalence table). | Only their changelog entries are missing (FR-008). |
| **M7** | Four unmerged heads from 2026-10-15: `35cbe78` (silent-audio output-map fix), `d50ee4b` (mock JACK readiness), `5a1811c` + `3c11c60` (mock nodeconf and its drop-in). All are present as `origin/*` branches. | FR-006, FR-007, FR-016, FR-016a. |
| **M8** | The cuems-utils `feat/xml-refactor` carries `stop_project` only in docs and specs, not in the version-2 `script.xsd`. | X-1 strict xfails (FR-020). |

## Clarifications

### Session 2026-10-17

- Q: Where do the kept developer tools live: `dev/scripts/`, `scripts/dev/` (WO §14.2) or `tools/dev/`? → A: **`dev/scripts/`**, with a `dev/README.md`. The top-level name `dev/` marks everything under it as not shipped. Top-level `scripts/` (today only `osc_send.py`) is removed, and `link-dev.sh` and `kill_cuems.sh` stay where they are. Shipped scripts remain in `src/cuemsengine/scripts/` and `debian/mock-scripts/`. This overrides WO §14.1's "`dev/` no longer exists" and WO §14.2's `scripts/dev/`.
- Q: Which unreviewed 2026-10-15 heads (#22 `35cbe78`, #23 `d50ee4b`, #24 `5a1811c` + `3c11c60`) does 009 include? → A: **#22 and #23 by SHA now. #24 is not built in 009. It lands in 0.1.1, after cuems-nodeconf's consolidation (its own reconciliation), on the structure 009 writes down (FR-016a).** #24 never shipped, so re-implementing it inside 009 would be new behaviour, and its drop-in overrides a unit that cuems-nodeconf owns, so nodeconf has to settle first. 009 writes a clear message to #24's author and the `rc_1` maintainer that sets out the agreed structure of the engine's mock nodeconf. (Amended in the same session: "0.1.2" became "0.1.1, after the cuems-nodeconf consolidation".)
- Q: For the hotfix line `0.1.0rc5-2…rc5-6`, copy the changelog entries only, or also record it as merged? → A: **Both.** Copy the five entries verbatim **and** run `git merge -s ours v0.1.0rc5-6`, citing the code-equivalence table, so future sweeps stop flagging about 62 already-absorbed commits.
- Q: Is the changelog-completeness check permanent, and what does it check against? → A: **A permanent test that reads the live git refs and tags** (`origin/debian/bookworm`, `origin/rc_1`, `v0.1.0*`) and **skips when they are absent**, rather than a committed manifest or a one-off script.
- Q: Does the A-5 id conversion cover every `str(id)` in absorbed code, or only the sites that send an id out of the process? → A: **Every** `str(id)` and raw id use in absorbed code goes through `id_str`/`as_id`. Tests are required only at the wire-leaving sites.

## User Scenarios & Testing *(mandatory)*

The actors are the **release maintainer**, who publishes `0.1.1-1` and re-cuts the tag; the **show
operator**, who runs shows on an upgraded cluster; the **sibling maintainers** (cuems-utils, -frontend,
-editor, -power-bridge, -nodeconf); and **contributors** working on the engine after 0.1.1.

### User Story 1 — Nothing shipped is lost on upgrade (Priority: P1)

An operator whose fleet runs `0.1.0rc6-5` upgrades to `0.1.1-1`. Every fix and feature they already
had is still there:

- the `stop_project` cue stops the project
- Auto follow crosses nodes
- audio cues wait for the player's JACK ports
- `project_status` reports `running` / `loaded` / `none`
- unrouted video outputs stay dark
- cue names reach the UI
- orphan sweeps never abort a load

The silent-audio output-map bug fixed on 2026-10-15 is not reintroduced either.

**Why this priority**: This is the reason the feature exists. Without it, publishing 0.1.1-1 is a
regression release for the whole fleet.

**Independent Test**: After the merges (FR-001…FR-008), both behind-counts are 0, and every inventory
item has a named test or recorded check that passes on the branch (SC-001, SC-002).

**Acceptance Scenarios**:

1. **Given** the branch at its hand-off head and freshly fetched refs, **When** the maintainer counts
   the commits reachable from `origin/debian/bookworm` or `origin/rc_1` but not from HEAD, **Then** both
   counts are 0.
2. **Given** a node whose project mappings list both inputs and outputs, **When** an audio cue targets
   output `<node>_0`, **Then** it resolves to the output port, never to `system:capture_1` (item 22).
3. **Given** a mock box, **When** an audio cue arms, **Then** it does not wait out the 14.5 s
   ready-gate timeout (item 23).
4. **Given** a version-2 project with a `stop_project` ActionCue built in code, **When** it fires,
   **Then** the project stops, as on `0.1.0rc6-5`.

---

### User Story 2 — Absorbed code obeys the 0.1.1 contract (Priority: P1)

The maintainer runs the suite on the reconciled branch. It shows no failure that `e994a5e` does not
also show. The code that came from the release line follows the same identity, typed-map and
version-2 rules as the rest of 0.1.1, so feature 008's guarantees hold for the whole engine, not only
for the part written on the refactor branch.

**Why this priority**: A merge that brings the code but breaks the 008 contract has two outcomes.
Either it fails loudly at the first unorderable `Uuid`, or it quietly answers wrongly, as when a `str`
sender is compared with a `Uuid` adopted set. Both cases are rig incidents waiting to happen (008 M18
was one).

**Independent Test**: Every adaptation is a red test first, then green, in its own commit. The identity
audit re-run over the merged `src/` finds no raw `str()`, `sorted()` or `.split()` on an id that leaves
the process (SC-004, SC-005).

**Acceptance Scenarios**:

1. **Given** the merge commit, **When** the suite runs, **Then** exactly the 10 tests of M5 are red,
   and each one turns green in a later commit that names its adaptation id.
2. **Given** a `stop_project` or `follow` status op whose sender is a `str` uuid, **When** it comes from
   an adopted node whose map id is a `Uuid`, **Then** it is accepted. **When** the same op comes from a
   non-adopted node, **Then** it is refused.
3. **Given** a real version-2 script loaded through the library, with a VideoCue whose media has no
   pixel size, **When** the cue runs, **Then** the engine falls back to probing the media. It does not
   treat a library "unset" marker as a size.
4. **Given** that #24 reached `rc_1` before hand-off and was absorbed (FR-016), **When** the mock
   nodeconf adopts a node, **Then** the written map validates against 0.1.1's `network_map.xsd`, the
   controller is detected by role, the `controller` role cannot be unadopted, and an offline node
   cannot be adopted.

---

### User Story 3 — The stable changelog lists every build that ever shipped (Priority: P2)

A maintainer or packager reading `0.1.1-1`'s `debian/changelog` or `CHANGELOG.md` finds every released
build: `rc1-1` through `rc6-5`, including the hotfix builds `rc5-2…rc5-6`. The released entries are
byte-identical to what was shipped. The `0.1.1-1` entry says what was reconciled and under which
cuems-utils condition. The packages still build at `0.1.1-1`, with their 016 relation values.

**Why this priority**: The changelog is the fleet's record of what shipped. A gap misleads upgrades,
lintian and anyone bisecting an incident. A built-in check also stops a future release-line merge
from dropping a build silently.

**Independent Test**: A test compares the set of Debian versions in the merged changelog with the
union of the release line, `rc_1` and every `v0.1.0*` tag. It checks that each released entry is
byte-identical and that `CHANGELOG.md` names each Debian version (SC-007).

**Acceptance Scenarios**:

1. **Given** the reconciled `debian/changelog`, **When** it is parsed, **Then** the top version is
   `0.1.1-1`, and the version set contains every header from `origin/debian/bookworm`, `origin/rc_1`
   and `v0.1.0rc5-6`.
2. **Given** `CHANGELOG.md`, **When** its source comments and inline revisions are collected, **Then**
   they name every one of those Debian versions, its top header is `v0.1.1`, and the lead paragraph no
   longer says "not reconciled".
3. **Given** a bookworm chroot, **When** both debs are built, **Then** they carry `Version: 0.1.1-1`,
   the mock package depends on `cuems-engine (>= 0.1.1)`, and the mock's `Conflicts:` names both
   players.

---

### User Story 4 — Siblings know what they owe, and the `stop_project` condition cannot be forgotten (Priority: P2)

The cuems-utils maintainers receive a report that `0.1.1` must carry `stop_project` in its version-2
schema (and three smaller items). The frontend, editor, power-bridge and nodeconf maintainers each
receive a note naming the engine contracts their reconciliation must confirm. On the day cuems-utils
ships `stop_project`, the engine's suite turns red on purpose, so someone drops the xfails.

**Why this priority**: The engine reconciles first. Without written obligations, the siblings'
reconciliations cannot check their halves. Without the strict xfails, a 0.1.1 cluster could publish
while refusing every project that contains a STOP-project cue.

**Independent Test**: The upstream reports exist under `upstream-reports/`. The strict-xfail list is
exactly the lock test plus the X-1 tests, each reason naming its report (SC-006).

**Acceptance Scenarios**:

1. **Given** a cuems-utils whose version-2 `script.xsd` lacks `stop_project`, **When** a test loads or
   saves a script with that action type, **Then** it is reported as an expected failure, not as a
   pass or an error.
2. **Given** a cuems-utils that has absorbed rc17's value, **When** the same tests run, **Then** they
   fail as XPASS(strict). That is the signal to remove them.

---

### User Story 5 — A contributor can tell what is live in the repository (Priority: P3)

A contributor who opens the repository for the first time after 0.1.1 finds a `dev/` that holds only
developer tools, not archived engines mixed with live fixtures. There is no unit file for a service that does not exist,
no stale schema copy, no uncollected `testdev_*.py`, and no stray `src/cuems/` package. Every
developer tool lives in `dev/scripts/`, with a `dev/README.md` saying none of it ships, and there is
no top-level `scripts/`. The tests are laid out
as in cuems-utils: `unit/`, `integration/`, `contract/`, `support/` and `data/`, each marked by its
directory. The documentation names paths that exist.

**Why this priority**: It is the first stable release, and the cleanup prevents repeat confusion. It
changes no behaviour and runs last, so P1/P2 do not depend on it.

**Independent Test**: The cleanup acceptance of WO §14.6 holds (SC-009). The pass set before and after
is identical, apart from listed retirements.

**Acceptance Scenarios**:

1. **Given** the cleaned tree, **When** the repository is searched for `dev/test_xml_files`,
   `test_json_files`, `pytest_cuems_plugin`, `CuemsEngine_old`, or a `scripts/link-dev.sh` path not
   preceded by `dev/` outside `specs/`, **Then** nothing is found.
2. **Given** a host without network, **When** the unit and contract tests run in parallel, **Then**
   they pass. The 8 environmental failures of M5 now live in `integration/`.
3. **Given** a test file placed in `tests/unit/`, **When** it is collected, **Then** it carries the
   `unit` marker and no other directory marker, without a hand-written decorator.

---

### User Story 6 — The maintainer can gate publication with one cloud run (Priority: P2)

Before publishing, the maintainer dispatches CI manually on the release candidate. They choose the
cuems-utils git ref to validate against. They get parallel unit and integration jobs, one combined
coverage gate, and a summary stating the engine SHA, the cuems-utils ref and commit, the pass and
xfail counts, and the strict-xfail list. A dispatch on a feature branch never overwrites the
published badge.

**Why this priority**: cuems-utils 0.1.1 is not on PyPI, so without a ref input CI cannot validate
0.1.1 at all. This run is also the hand-off evidence.

**Independent Test**: A `workflow_dispatch` run on the 009 head SHA, with `cuemsutils_ref` set to the
current utils candidate tag, is green and recorded in `evidence/ci-gate.md` (SC-010).

**Acceptance Scenarios**:

1. **Given** a dispatch on this branch with a `cuemsutils_ref`, **When** it runs, **Then** cuemsutils
   is installed from that ref and not from PyPI, and the job logs the resolved commit and
   `cuemsutils.__version__`.
2. **Given** a dispatch on any ref other than `main` or `rc_1`, **When** the coverage job finishes,
   **Then** no badge is pushed.
3. **Given** a push or pull request on `feat/xml-refactor`, **When** CI triggers, **Then** the same
   jobs run.

### Edge Cases

- **The release line moves during 009** (for example a new `0.1.0rc6-6`, or branches 22–24 landing on
  `rc_1`). It is re-measured at the start and before hand-off. The delta is merged the same way
  (FR-002). Heads that `rc_1` has meanwhile taken are not merged twice: merging by SHA makes the
  second route a no-op.
- **cuems-utils lands rc17 `stop_project` before 009 finishes.** The X-1 tests turn XPASS(strict), and
  the suite goes red. Handling: provisional default under FR-021.
- **A §5 hunk looks like it should be "ours" wholesale.** Whole-side strategies (`-X ours`/`-X theirs`)
  are forbidden (FR-005), because they silently drop absorbed fixes.
- **A "unit" file actually opens a socket.** It is moved to `integration/` at re-layout time, or its
  socket is mocked. It is not left as a parallel unit test.
- **The engine deb ships `/usr/lib/cuems/CACHEDIR.TAG`.** Handling: FR-034 (provisional: strip it).
- **The controller UUID is a `Uuid` in the map but a `str` in a sender payload.** The comparison must
  go through `as_id` (FR-017).
- **An empty `<name/>` or a CueList child in the cue-name walk** must yield `""`, never a crash or
  `None` (R-2).
- **A rolling upgrade with mixed engine versions.** It is unsupported, because the GO payload became a
  dict carrying `run_seq`. The release note states it (FR-038).

## Requirements *(mandatory)*

Every adaptation and fix requirement below starts from a **red test** (constitution principle II).
"Merge" always means `--no-ff` with a GPG-signed commit (FR-061). Inventory item numbers (#1–#24)
refer to the [Inventory](#inventory-what-the-merge-brings-wo-4-and-41).

### Absorbing the release line (merge, resolution, ancestry)

- **FR-001**: The branch MUST absorb `origin/debian/bookworm` with **one real merge**. The merge commit
  contains the FR-004 resolutions **and nothing else**. Then `origin/rc_1` is merged, for ancestry
  only. No inventory item may be cherry-picked (WO §3 method C). Cherry-picking is a fallback only
  for an item a maintainer explicitly excludes from 0.1.1, and none is excluded.
- **FR-002**: The implementation MUST re-measure the line at its start and again before hand-off: the
  behind-counts, the new changelog headers, and the WO §4.1 stray-head sweep. Anything newer MUST be
  merged the same way, and the measurement recorded in `evidence/`. Measuring against `master`
  (`92f03c6`, 2025-02) is wrong.
- **FR-003**: A baseline suite run on the branch before any merge (arm A), and a run on the merge
  commit (arm B), MUST be recorded in `evidence/`. Arm B is expected to show exactly the 10 failures
  of M5. Any other red is a new finding to be recorded and explained.
- **FR-004**: Conflicts MUST be resolved per WO §5:

  | File / hunk | Resolution |
  |---|---|
  | `ControllerEngine.py` hunk 1 (`status_operation_callback`) | **Theirs.** The `script_finished` branch is deleted (869fhjdp8 removed it on purpose). 008's `as_id` care for senders moves to the `stop_project` and follow-relay sender checks (FR-013). |
  | `ControllerEngine.py` hunk 2 (arm watchdog message) | **Combine** theirs' `f"{what} stalled…"` with ours' `_sorted_ids(pending)`. |
  | `tests/test_controller_commands.py` ×2 | **Theirs** (three-state `project_status`), keeping 008's uuid4 literal. |
  | `tests/test_nodelist_modify.py` | **Ours** (the typed `adopted_network_map(...)` fixture). |
  | `pyproject.toml` ×2 | **Ours** (`0.1.1`, `cuemsutils >=0.1.1,<0.1.2`, the pyossia wheel), plus one comment line: 0.1.1 must contain rc17's `stop_project`. |
  | `src/cuemsengine/__init__.py` | **Ours** (`__version__ = "0.1.1"`) plus theirs' added `SPDX-FileContributor` line. |
  | `debian/control` ×2 | **Ours** for every versioned `Depends` and its comment. **Theirs** for the SPDX header, the mock `Conflicts: cuems-audioplayer, cuems-dmxplayer` and the renamed mock binaries in the description. |
  | `debian/changelog` | As FR-030. |
  | The `origin/rc_1` merge | **Ours** for its `0.1.0rc2` version sites and its `debian/`. |

- **FR-005**: Whole-side merge strategies (`git merge -X ours`, `-X theirs`) MUST NOT be used.
- **FR-006**: Branch heads `35cbe78` (item 22) and `d50ee4b` (item 23) MUST be merged **by SHA**, after
  the `rc_1` merge, unless `rc_1` has already taken them. They are never cherry-picked. Both are
  included even if their PRs are still unreviewed (clarified 2026-10-17).
- **FR-007**: Heads `5a1811c` and `3c11c60` (item 24) MUST NOT be merged by 009. #24 lands in 0.1.1
  **after** 009, once cuems-nodeconf's consolidation is done, rebuilt on FR-016a's structure. The
  sweep evidence records the sequencing with a pointer to FR-016a's message. Safety net: if `rc_1`
  has taken #24 by the hand-off re-measurement, SC-001 still forces it in, and FR-016 then applies.
- **FR-008**: The five released entries `0.1.0rc5-2 … rc5-6` MUST be copied verbatim from
  `git show v0.1.0rc5-6:debian/changelog` into their dpkg-order position. A content merge of the
  hotfix line is forbidden: backports onto an rc5 base would re-conflict across #22–#29. Ancestry
  MUST also be recorded with `git merge -s ours v0.1.0rc5-6` (clarified 2026-10-17). Before that
  merge, the code-equivalence table (WO §4.1 row 21: each hotfix commit → its `rc_1` commit, or
  "patch-equivalent") MUST be written to `evidence/hotfix-rc5-equivalence.md` and re-verified with
  `git cherry`. The merge commit's message cites that file. If any hotfix commit has no equivalent,
  the `-s ours` merge is blocked until that commit's content is absorbed.
- **FR-009**: The rig build `0.1.0rc6-3+nodeadopt2` (`integ/rc6-3-node-adoption`, `363b92a`), the
  `gh-pages` branch and the `archive/*` and 2020–2025 abandoned refs MUST stay out. Each exclusion is
  recorded in `evidence/` with its reason (provisional default, WO §12 Q7).

### Adapting absorbed code to the 008 contract (method A)

- **FR-010 (A-1)**: The 008 test for a version-1 `fade_out` read as `stop` MUST expect
  `disarm(..., reason="stop_action")` and keep its assertion that `fade_out` becomes `stop`.
- **FR-011 (A-2)**: 008's media-duration fixture MUST give the player handler a `(w, h)` media-dimensions
  answer, and keep 008's duration assertions unchanged. A new test MUST show that a version-2-loaded
  VideoCue with **absent** pixel sizes falls back to probing (see FR-018).
- **FR-012 (A-3)**: The wraparound fixture MUST build its media duration the 008 way, as a timecode
  object. The engine's duration helper MUST NOT be widened to accept strings, because 008 made the
  type explicit.
- **FR-013 (A-4)**: 008's test of the deleted `script_finished` aggregator MUST be retired and recorded
  in `evidence/test-retirements.md`. It is replaced by the same identity property on the surviving
  paths: a `stop_project` op and a `follow` op whose `str` sender comes from an adopted node with a
  `Uuid` map id are accepted, and the same ops from a non-adopted sender are refused.
- **FR-014 (A-6)**: 008's editor cue-id identity test MUST arrange `running = yes`. A negative twin
  MUST show that with `running = no` the ADD is ignored, with a `str` id.
- **FR-015**: `specs/008-cuems-utils-migration/` is frozen history and MUST NOT be rewritten. Retirements
  and replacements are recorded only in 009's evidence.
- **FR-016 (A-8, item 24, safety net)**: Only if #24 arrives through `rc_1` before hand-off (FR-007):
  the absorbed mock nodeconf MUST be brought onto the structure of FR-016a, built on cuemsutils'
  **public** 0.1.1 network-map API:
  - detect the controller by `node_role`, never by `node_type … endswith("master")`
  - use the typed `adopted: bool`, written as `true`/`false`
  - use the published validate and write path, never `cuemsutils.xml.XmlReaderWriter`

  Red tests first: unadopting the `controller` role is refused; an offline node cannot be adopted;
  the written map validates against 0.1.1's `network_map.xsd`. `test_public_surface.py` stays green.
- **FR-016a (#24 structure message)**: 009 MUST write
  `upstream-reports/rc_1-mock-nodeconf-structure.md`, addressed to #24's author and the `rc_1`
  maintainer. It states the agreed structure for the engine's mock nodeconf, so that #24 can be
  rebuilt once, correctly:
  - **Where it lives**: the packaged entry point `src/cuemsengine/scripts/mock_nodeconf.py`, used only
    by `cuems-engine-mock` (FR-049). It is not a developer tool, so not `dev/scripts/`. Its drop-in
    ships from `debian/` in the mock package.
  - **What it answers**: `nodelist_modify` on `/tmp/nodeconf.ipc`, with the reply shape the engine's
    `nodelist_modify` expects. It replies exactly once and never answers by raising.
  - **API rules**:
    - Only cuemsutils' public 0.1.1 network-map API. It reads and writes through the published
      load/validate/write path; `cuemsutils.xml` is forbidden, and `test_public_surface.py` must
      stay green.
    - The controller is found by `node_role` (`NodeRole`), never by `node_type`/`master`.
    - `adopted` is the typed `bool`, written `true`/`false`.
    - Ids go through `as_id`/`id_str`, never `str()`, `sorted()` or `.split()`.
  - **Behaviour and its red-first tests (in `tests/unit/`)**:
    - unadopting the `controller` role is refused
    - adopting an offline node is refused
    - the written map validates against 0.1.1's `network_map.xsd`
    - an unknown `modify_action` is refused
    - the map file is untouched after any refusal
  - **Base and timing**: the post-009 `feat/xml-refactor`, or `rc_1` once it tracks cuemsutils 0.1.1,
    because the 0.1.1 public API does not exist on an rc17 base. It lands **after cuems-nodeconf's
    consolidation** and before 0.1.1 is published, through the same merge-by-SHA route as the other
    heads.
  - **Cross-package edge**: the `cuems-nodeconf.service.d` drop-in overrides a unit that
    cuems-nodeconf owns. Its shape is settled in cuems-nodeconf's consolidation, which is why #24
    waits for it (FR-023).
- **FR-017 (A-5, identity)**: In code absorbed from the release line, every id that leaves the
  process MUST leave through `id_str`, and every incoming payload id MUST pass through `as_id` before
  it is compared with project ids. No raw id may be `sorted()`, sliced or `.split()`, and no `src/`
  module may import `Uuid`. The known sites are:
  - `FollowRelay`'s announce and cancel payloads, and its source/target reads
  - `ControllerEngine._handle_stop_project`
  - `get_project_status` (`project_uuid`)
  - `NodeEngine.check_unrouted_video_outputs` (`cue_id`)
  - the NodeEngine stop-project notify
  - `PlayerHandler`'s five `str(cue.id)` uses and the hyphen-stripped slug, also in `run_cue.py`
  - the cue-name OSC address

  `test_identity_sweep.py` MUST gain one case per wire-leaving site. The conversion covers **every**
  `str(id)` and raw id use in absorbed code, including dict keys and log joins, not only the
  wire-leaving sites (clarified 2026-10-17). Tests are required only at the wire-leaving sites.
- **FR-018 (R-1)**: The engine MUST establish, against a **real** version-2 script loaded through the
  library, what a missing `pixel_width`, `pixel_height` or `file_size` reads as under cuemsutils 0.1.1.
  If it reads as the library's "unset" marker rather than as nothing, the "missing → probe" and
  own-media checks MUST treat that marker as missing, through a published library symbol. Any
  dependency on unpublished semantics goes to the cuems-utils report (X-4).
- **FR-019 (R-2, R-3, R-4)**: Tests MUST prove three things:
  - **R-2**: the cue-name walk yields `""` for an empty `<name/>` and descends into CueList children
    of a real version-2 script.
  - **R-3**: `stop_project` is not rejected by any 008 unknown-action guard, and "other project
    actions are still rejected" stays green.
  - **R-4**: the `stop_project` and follow relays use **the same** adopted set as the GO gate.
- **FR-019a (A-7, item 22)**: The output-map fix MUST be checked against 008's typed project-mappings
  read path. If the branch carries no test that mappings with `inputs` leave the output lookup
  unaffected, one MUST be added, red first.

### Sibling obligations and the `stop_project` condition (WO §8)

- **FR-020 (X-1, D1)**: Every engine test that loads or saves a script with
  `<action_type>stop_project</action_type>` through schema validation MUST be written now and marked
  as a strict expected failure. Its reason names the cuems-utils upstream report. Tests that build the
  ActionCue in code stay ordinary passing tests.
- **FR-021**: Provisional default (WO §12 Q4): if cuems-utils lands rc17's value before 009 hands off,
  the X-1 xfails are removed **inside 009**, and the removal is recorded in evidence.
- **FR-022**: An upstream report to cuems-utils MUST be written under `upstream-reports/`. It covers:
  - **X-1**: `stop_project` in the version-2 `ActionType` and in the ActionCue docs.
  - **X-2**: keep `Replaces: cuems-engine (<< 0.1.0rc6-2~)` for the `cffi-gen-src` move, and add it to
    016's relation matrix.
  - **X-3**: CACHEDIR.TAG.
  - **X-4**: the `Media` "unset" versus "nothing" contract on a version-2 load.

  Linking it from cuems-utils' "still owed" list is an edit in cuems-utils, so it is handed to that
  maintainer.
- **FR-023**: One note each MUST be written for cuems-frontend, cuems-editor, cuems-power-bridge and
  cuems-nodeconf. Each names the engine contracts this merge adds:
  - the GO dict with `run_seq`, and the `follow` ops
  - `project_status` with three states and `project_unix_name`
  - `/engine/status/cue_name/<uuid>`
  - authored `stop_project`
  - the mock's planned `cuems-nodeconf.service.d` drop-in (#24, FR-016a), which would override a unit
    that nodeconf owns. Its shape is to be settled in cuems-nodeconf's consolidation, and #24 lands
    in 0.1.1 after that.

  No sibling's files are changed by this feature.

### Packaging, versions, changelogs (WO §7)

- **FR-030**: `debian/changelog` MUST be ordered by dpkg version, highest first:
  1. `0.1.1-1` UNRELEASED, kept, with its body extended
  2. `rc6-5 … rc6-1`, verbatim from bookworm
  3. `rc5-6 … rc5-2`, verbatim from `v0.1.0rc5-6`
  4. `rc5-1, rc4-1, rc3-2, rc3-1`, verbatim from bookworm
  5. `rc2-3 … rc1-1`, kept

  Released entries are never rewritten or renumbered.
- **FR-031**: The `0.1.1-1` entry body MUST do three things. It replaces the "NOT YET RECONCILED"
  bullet with "Reconciled with debian/bookworm at `<sha>` (0.1.0rc6-5)", listing items #1–#13 one line
  each. It adds the X-1 condition. It keeps the `poetry.lock` bullet. The top version stays `0.1.1-1`.
- **FR-032**: `CHANGELOG.md` MUST cover every released Debian build:
  - `## v0.1.0rc6` is extended to `rc6-2…rc6-5`, with one source comment per build and the inline
    revision and date under the existing Added/Changed/Fixed sub-headers.
  - `## v0.1.0rc5` is extended to `rc5-2…rc5-6`.
  - Every older section is audited build by build. `rc2-3` and `rc1-1` are the unverified rows.
  - The `## v0.1.1` lead paragraph is rewritten to "Contains every change released in 0.1.0rc3-1 …
    0.1.0rc6-5, absorbed from debian/bookworm at `<sha>`", followed by the X-1 condition.
  - `## v0.1.1` stays the top header. A `-N` revision never gets a top-level header.
- **FR-033**: A **permanent** contract test MUST check the changelog completeness of SC-007, so that a
  future release-line merge cannot drop a build silently.
  - **Source of truth**: it reads the live git refs and tags (`origin/debian/bookworm`, `origin/rc_1`
    and every `v0.1.0*` tag) at test time. There is no committed manifest (clarified 2026-10-17).
  - **Absent refs**: when any required ref or tag is missing (a shallow clone, a tarball, a deb
    build), the test **skips**. The skip reason names the missing refs, so it is never a silent pass.
  - **Proof**: SC-007's evidence MUST come from a run in which the test executed and did not skip.
  - **Resolved by the plan** (research R2, contract C1): the `unit` job checks out full history and
    fetches `debian/bookworm`, `rc_1` and the tags, so the test runs in the gate.
- **FR-034**: `debian/rules` MUST still carry, after the merge:
  - the isolated build venv and the rtmidi vendoring check (item 14)
  - the `cffi-gen-src` strip (item 15)
  - the renamed mock wrappers (item 16)
  - 016's venv `home = /usr/bin`

  The built engine deb MUST be checked for `/usr/lib/cuems/CACHEDIR.TAG` and the result recorded.
  Provisional default (WO §12 Q2): if the file is present, strip it the way the siblings do.
- **FR-035**: Both debs MUST be built in a bookworm chroot, and not published. The evidence shows
  `Version: 0.1.1-1`, the mock's `Depends: cuems-engine (>= 0.1.1)`, and its `Conflicts:` naming both
  players.
- **FR-036**: cuems-utils' 016 `verdicts.sh` MUST be re-run for the engine rows and report 27/27. The
  new evidence goes to 009's `evidence/`; 016's is never overwritten.
- **FR-037**: These MUST NOT move:
  - the version (`0.1.1` / `0.1.1-1`)
  - `python3-pyossia (>= 2.0.0-rc6+124+cuems3)` and the dev wheel
  - the `cuemsutils` constraint `>=0.1.1,<0.1.2`
  - `poetry.lock`, which is not relocked; `test_lock_is_current.py::test_poetry_lock_is_current` stays strict-xfail
- **FR-038**: The release notes and the tag message MUST state that every host in a cluster upgrades
  together. A mixed-version cluster is unsupported, because of the GO dict with `run_seq`
  (provisional default, WO §12 Q5).

### Documentation (WO §9)

- **FR-040**: CLAUDE.md MUST state that `stop_project` needs cuems-utils "≥ 0.1.1, which must absorb
  rc17's value". The merged file MUST also be cleared of leftover `script_finished` wording and of
  sections duplicated between 008's rc7 notes and rc_1's notes.
- **FR-041**: `docs/unattended-playback.md` MUST cite `0.1.1` / `0.1.1-1` in place of its `0.1.0rc17`
  and `0.1.0rc6-3` claims. `docs/` stays end-user only.

### First-stable-release cleanup (WO §14.1–§14.4)

These requirements run **last**, after the final re-fetch and re-merge. They are pure moves, deletes
and rewires, one commit per sub-section, and the suite runs after each commit.

- **FR-045 (`dev/`)**: After the cleanup, `dev/` MUST contain only `scripts/` (the kept developer
  tools) and `README.md`.
  - **Delete**:
    - the superseded engines `CuemsEngine.py` and `CuemsEngine_old.py`
    - the player prototypes
    - `NodeControl.score`
    - the misleading `cuems-engine.service`
    - the stale `network_map.xsd`
    - `display.py`, `editor-engine-commands.txt` and `diagnose_env_output.txt`
    - `test_cleanup_demo.py`
    - the pyossia investigation scripts. One line naming them and their last commit is added to
      `PYOSSIA_EVALUATION_RESULTS.md`, which is the record of their findings.
    - the retired master/slave/firstrun scripts
    - `diagnose_env.py` and `run_cpu_tests.py`. The latter is replaced by one documented `pytest … -m
      slow` line.
    - the scratch JSON files
  - **Move**:
    - the live fixtures (`dev/test_xml_files/*`) to `tests/data/`
    - `scripts/osc_send.py` to `dev/scripts/osc_send.py`. The now-empty top-level `scripts/` is removed.
  - **Keep in place**: `dev/scripts/link-dev.sh` and, if kept, one `kill_cuems` implementation in
    `dev/scripts/`. The kept one is re-checked against the binary names fixed by 869evtdf7.
  - The `.gitignore` rule `dev/local/` is removed.
  - Re-point the `.gitignore` media rule to `tests/data/media/`.
  - Provisional default (WO §12 Q9): keep `osc_send.py` and the shell `kill_cuems.sh`, and delete the
    Python duplicate.
- **FR-046 (developer tools)**: `dev/scripts/` MUST hold the kept developer tools, including
  `osc_send.py`. A short `dev/README.md` states what each tool is for and that nothing under `dev/` is
  packaged or run by CI. No top-level `scripts/` directory remains. The stale `scripts/link-dev.sh`
  references in README, CONTRIBUTORS and the constitution MUST name `dev/scripts/link-dev.sh`. The constitution change is a **MINOR** amendment (1.1.0 → 1.2.0) made through `/speckit-constitution`. It corrects the `link-dev.sh` path and rewrites the test-location standard (lines 117–118) to describe FR-047's split into `tests/unit/`, `tests/integration/` and `tests/contract/` (helpers in `tests/support/`, fixtures in `tests/data/`), with modules still named after the source module they cover.
- **FR-047 (`tests/`)**: `tests/` MUST follow cuems-utils' layout:
  - `support/`: the helpers, plus one `paths.py` with `DATA_DIR`, the only place the data path is
    written
  - `data/`
  - `unit/`
  - `integration/`: a test goes here if it binds or connects a real socket or device, starts a real
    subprocess or player, touches JACK or ALSA, or relies on a `sleep` ≥ 0.5 s
  - `contract/`: the repository and packaging invariants, including FR-033's test

  Further rules:
  - A root `conftest.py` hook marks every test by its directory. `slow` stays an explicit mark, the
    unused `cuems` marker goes, and `--strict-markers` stays.
  - The rule is written in `tests/README.md` and `CONTRIBUTORS.md`.
  - The commented-out data-path copies and the import from `conftest` are removed.
  - Provisional default (WO §12 Q10): split `test_port_handler.py`, so that only the concurrent-draws
    case is integration.
- **FR-048 (strays)**: These MUST be deleted:
  - `src/cuems/`
  - `src/cuemsengine/scripts/system_ports.py`
  - `tests/pytest_cuems_plugin.py`, whose still-true content in `README_CLEANUP.md` is folded into
    CONTRIBUTORS before that README is deleted
  - the three `testdev_*.py` files. A passing case is moved to `integration/` only if no existing
    test covers it; every retirement is recorded.

  `.venv/pyvenv.cfg` MUST be untracked, keeping only its ignore rule. `.gitignore` MUST gain
  `.venv-*/`, `.ruff_cache/`, `.016-native/` and a root `/__pycache__`. `README_CPU_TESTS.md` is
  rewritten to the plain pytest line or folded into CONTRIBUTORS. No document may still name the
  deleted `VideoPlayer`.
- **FR-049**: The mock entry points stay inside the production venv for 0.1.1 (YAGNI). They are
  recorded as a known wart for 0.1.2.

### The pre-publication CI gate (D5, WO §14.5)

- **FR-050**: The workflow file MUST keep the name `.github/workflows/ci.yml`, because dispatch requires
  the file to exist on the default branch `main`, and 009 never touches `main`. Its jobs:

  | Job | Needs | Runs |
  |---|---|---|
  | `lint` | — | unchanged |
  | `unit` | `lint` | unit + contract tests, parallel, with coverage |
  | `integration` | `lint` | integration tests without `slow`, with coverage; parallel with `unit` |
  | `coverage` | `unit`, `integration` | combines both; the 45 % gate applies to the **combined** number |
  | `gate-summary` | all | engine SHA, cuemsutils ref and resolved commit, pass/xfail counts, strict-xfail list |

- **FR-051**: The workflow MUST take a `cuemsutils_ref` dispatch input, defaulting to the cuems-utils
  `xml-refactor-merge-candidate` tag. It installs cuemsutils from that git ref, not from PyPI, and push
  and PR runs use the same default. Each run logs the resolved commit and `cuemsutils.__version__`.
- **FR-052**: The install path MUST cope with the stale lock, which resolves `cuemsutils 0.1.0rc16`
  against the `>=0.1.1,<0.1.2` constraint, and keep every **other** dependency at its locked version.
  The relock is never committed. The variant is chosen during planning, after research into Poetry
  2.4.1's behaviour on that mismatch.
- **FR-053**: `feat/xml-refactor` MUST be added to the push and pull-request triggers.
- **FR-054**: The badge and gh-pages push MUST run only when the ref is `main` or `rc_1`.
- **FR-055**: `slow` tests stay out of the hosted run. The evidence states that they run by hand on a
  rig.
- **FR-056**: One `workflow_dispatch` run on the 009 head SHA MUST be green, with `cuemsutils_ref` set to
  the current utils candidate tag. Its URL, the engine SHA, the cuemsutils ref and commit, and the
  xfail list are recorded in `evidence/ci-gate.md`.
- **FR-057**: The pre-publication checklist line MUST be written into the tag message and into
  CONTRIBUTORS' release section. It reads: #24 has landed on FR-016a's structure after the
  cuems-nodeconf consolidation; then dispatch again on the post-merge `feat/xml-refactor` head against
  utils' reconciled tag, before the PyPI and `.deb` upload.

### Hand-off

- **FR-058**: `../.xml-refactor-tag-messages/cuems-engine.txt` MUST be rewritten:
  - `Tag:` points at the post-merge `feat/xml-refactor` head.
  - "NOT YET RECONCILED" is replaced by "Reconciled with origin/debian/bookworm at `<sha>`
    (0.1.0rc6-5)" plus the X-1 condition.
  - "Carries" gains items #1–#13.
  - "Pairs with" is unchanged.

  The `--no-ff` merge into `feat/xml-refactor` and the tag re-cut are maintainer acts.
- **FR-059**: The hand-off MUST include a note in CONTRIBUTORS' testing section, and a message to the
  `rc_1` maintainer (`upstream-reports/rc_1-test-layout.md`), about the new test layout, so that new
  tests stop landing at the `tests/` root.
- **FR-060**: The **final task** MUST delete `specs/planning/release-line-reconciliation-0.1.1.md`,
  after verifying two things: every WO section is traceable from this directory, and `git grep -n
  release-line-reconciliation-0.1.1 -- . ':!specs/009-*'` returns nothing. Any hit is re-pointed first.
  009 records the file's last commit, so its history stays reachable.
- **FR-061**: Every commit MUST be GPG-signed. On a signing failure, retry; never use
  `--no-gpg-sign`. The commit shape:
  1. the bookworm merge
  2. the rc_1 merge, then the stray-head merges
  3. one commit per adaptation
  4. packaging and changelog
  5. docs
  6. the re-verification record
  7. one commit per cleanup sub-section
  8. CI
  9. the tag-message rewrite
  10. the planning-file deletion

  Note: the FR-008 hotfix work (the changelog-entry copy with its contract test, then the
  `-s ours` merge) belongs to the merge group (2), not to "packaging and changelog" (4). The
  `-s ours` merge cites the copied entries, so they must land first. Item 4 covers the rest of
  FR-030…FR-038.

### Constraints

- **FR-062**: The feature MUST add no runtime dependency and no new behaviour beyond what the release
  line already shipped. Logging added by adaptations follows the engine's structured-logging
  convention; no silent failure is introduced.

### Inventory: what the merge brings (WO §4 and §4.1)

"Released in" is the bookworm changelog entry that shipped the item. M = merge, R = conflict
resolution, A = adaptation, D = direct copy.

| # | Item (ClickUp / PR) | Released in | Method | Seam |
|---|---|---|---|---|
| 1 | Video scale readback with float32 tolerance; placement failures at ERROR, recorded per cue; disarm skips layers removed by `/reset` and logs a reason (869f8hfra, #20) | rc6-2 | M | A-1 |
| 2 | The dead `VideoPlayer` deleted (869f8v8yv, #21) | rc6-2 | M | — |
| 3 | Pre-arm of the next segment; one arm in flight per cue; arm epochs; the JACK wait ends on a dead player; a GO that cannot arm skips and advances (869f9wqpn, #22) | rc6-2 | M | — |
| 4 | Pre-arm measurement log lines (#22) | rc6-2 | M | — |
| 5 | Video pixel size taken from the project; nodes report their own media files that differ (869fat84r, #22) | rc6-2 | M | A-2, R-1 |
| 6 | Video wraparound only for repeating cues (869fa89uh, #23) | rc6-3 | M | A-3 |
| 7 | Cross-node Auto follow relay, `run_seq`, `FollowRelay` (869fc8ytz, #25) | rc6-3 | M | A-5 |
| 8 | Audio ready gate: wire on RUNNING, edge-by-edge repair at GO (869fbyjzx/869fcvz85, #27, #30) | rc6-3 | M | — |
| 9 | Cue names on the `:9190` channel (869fedahu, #28) | rc6-3 | M | A-5, R-2 |
| 10 | Orphan-kill sweeps never abort a load and match own-user players only (869evtdf7, #29) | rc6-3 | M | — |
| 11 | `project_status` with three states; a failed load clears `load` (869dr2kzh/869dr2k2h, #32) | rc6-4 | M + R | A-5 |
| 12 | Unrouted video outputs stay dark; `display.conf` `enabled=` (869fgq3xv, #33) | rc6-4 | M | A-5 |
| 13 | `stop_project` ActionCue; cue ADD/UPDATE ignored while not running; arm watchdog restarts after STOP; `script_finished` removed (869fhjdq5/869fhjdp8, #35/#36) | rc6-5 | M + R | A-4, A-6, R-3, R-4, X-1 |
| 14 | Isolated build venv; the build fails if rtmidi is not vendored (869f79ecc) | rc6-1 | M | — |
| 15 | `cffi-gen-src` no longer shipped | rc6-2 | M | X-2 |
| 16 | Mock wrappers renamed; mock `Conflicts:`; postinst path text | rc3-2/rc4-1 | M + R | — |
| 17 | SPDX headers on `debian/control` and `debian/rules` | rc6-x | M + R | — |
| 18 | Changelog entries `rc3-1…rc6-5` | — | M + R | FR-030 |
| 19 | `docs/unattended-playback.md`, `docs/index.md`, CLAUDE.md additions | — | M | FR-040, FR-041 |
| 20 | `cuemsutils >= 0.1.0rc17` | rc6-5 | R → ours | subsumed only if X-1 holds |
| 21 | Hotfix line `rc5-2…rc5-6` (code equivalent to rc_1 commits already in scope) | rc5-2…rc5-6 | D + `-s ours` (ancestry) | FR-008 |
| 22 | `35cbe78`: output maps ignore inputs (silent-audio bug) | unreleased | M by SHA | A-7 |
| 23 | `d50ee4b`: mock players report JACK ready | unreleased | M by SHA | — |
| 24 | `5a1811c` + `3c11c60`: mock nodeconf and its drop-in | unreleased | not in 009; lands in 0.1.1 after the cuems-nodeconf consolidation | FR-016a (A-8 only as safety net) |

Checked and found to be no item: `66aeb1f` and `ea81c50`, which rc_1 superseded, and `2cf205b`, whose
`postinst` is identical on both sides.

### Key Entities

- **Release line**: `origin/debian/bookworm` (packaging and releases) fed by `origin/rc_1`
  (development). It is a moving target: it is measured, never assumed.
- **Released build**: one `cuems-engine (<version>)` entry in a shipped `debian/changelog`. It is
  identified by its Debian version and must appear verbatim in the stable changelog.
- **Inventory item**: a unit of shipped or pending change, with a method (M/R/A/D) and a seam, and
  one named test that proves it is present.
- **Adaptation**: a post-merge commit that brings absorbed code under the 008 contract, always opened
  by a red test.
- **Strict xfail**: a test that must fail today and must turn red once its upstream obligation is met.
  Allowed set: `test_lock_is_current.py::test_poetry_lock_is_current` plus the X-1 tests.
- **Upstream report / sibling note**: a written obligation for another repository. This feature never
  edits the other repository.
- **Gate run**: a dispatched CI run, identified by the engine SHA and the cuemsutils ref and commit.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: At hand-off, against freshly fetched refs, 0 commits are reachable from
  `origin/debian/bookworm` or `origin/rc_1` but not from HEAD. Items 22–23 (or their rc_1 merges) are
  ancestors of HEAD, item 24 is either an ancestor (safety net, FR-016) or recorded as sequenced after the cuems-nodeconf
  consolidation, and so is `v0.1.0rc5-6` (FR-008). Every row of the
  re-run stray-head sweep has a recorded verdict.
- **SC-002**: The evidence table names one proof per inventory item, and every proof passes on the
  hand-off head. For behavioural items #1–#13, #22, #23 and (if absorbed) #24, the proof is a test (for #1–#13, the rc_1
  test that came with the item). For packaging, changelog and docs items #14–#21, it is a test or a
  recorded check.
- **SC-003**: On the same host, the CI-equivalent suite shows **no failure that `e994a5e` does not also
  show**, in three interleaved runs of both arms. The 10 merge-induced failures are fixed, not skipped.
- **SC-004**: The strict-xfail set is exactly `test_lock_is_current.py::test_poetry_lock_is_current` plus the X-1 tests, and every
  reason names an upstream-report path.
- **SC-005**: The identity audit re-run over the merged `src/` finds 0 raw `str()`, `sorted()`,
  slicing or `.split()` on an id that leaves the process, and 0 `src/` imports of `Uuid`.
- **SC-006**: The cuems-utils upstream report (X-1…X-4), the four sibling notes, the #24 structure
  message (FR-016a) and the `rc_1` test-layout message (FR-059) exist, and no sibling repository's
  files were changed. Two paths outside the repository are allowed: the tag-message file that FR-058
  rewrites, and temporary measurement worktrees, which are removed after use.
- **SC-007**: The changelog contract test **runs, not skips,** against freshly fetched refs and tags,
  and passes:
  - the top version is `0.1.1-1`
  - the Debian versions in `debian/changelog` ⊇ bookworm ∪ rc_1 ∪ every `v0.1.0*` tag, so the
    comparison returns an empty difference, `rc2-3` included
  - `rc3-1…rc6-5` are byte-identical to bookworm's entries, and `rc5-2…rc5-6` to `v0.1.0rc5-6`'s
  - every one of those versions is named in `CHANGELOG.md`, whose top is `v0.1.1` without "not
    reconciled"
- **SC-008**: The engine relation verdicts are 27/27. Both debs build in bookworm at `0.1.1-1` with the
  required `Depends` and `Conflicts`, and the CACHEDIR.TAG result is recorded. `black`, `isort` and
  `flake8` are clean.
- **SC-009**: The cleanup acceptance (WO §14.6) holds:
  - `dev/` holds only `scripts/` and `README.md`, the README lists every surviving tool, and there is
    no top-level `scripts/`.
  - The forbidden-path search outside `specs/` returns nothing.
  - No `test_*.py` is left at the `tests/` root, and a contract test asserts that every collected test
    carries exactly one directory marker.
  - The unit and contract tests pass in parallel without network, with 0 of the 8 environmental
    failures.
  - The pass set before and after the cleanup is identical, apart from listed retirements, and
    combined coverage is ≥ 45 %.
  - README, CONTRIBUTORS, the constitution and CLAUDE.md name the new paths.
- **SC-010**: A dispatched CI run on the 009 head SHA is green, and its record in `evidence/ci-gate.md`
  carries the URL, the SHA, the cuemsutils ref and commit, and the xfail list. A dispatch on a ref
  other than `main` or `rc_1` pushes no badge.
- **SC-011**: The tag message is rewritten per FR-058, and the planning file is deleted with 0
  remaining references outside `specs/009-*`.

## Assumptions

- **A1 — Base.** The branch was created at `945ccba` rather than `e994a5e`. The only difference is the
  work-order document itself, which this feature needs until FR-060.
- **A2 — "CI green" in the out-of-scope list.** The input lists "CI green" as out of scope, but D5 and
  the same input require a green dispatched run on the 009 head. Reading: D5 supersedes the stale
  exclusion (the WO strikes it through in §1). **In scope**: the restructure and one green dispatch on
  the 009 head (FR-056). **Out of scope**: CI on `main` or `rc_1`, and the pre-publication run against
  utils' reconciled tag, which is a maintainer act after 009 (FR-057).
- **A3 — `.venv/pyvenv.cfg`.** WO §7.4 calls untracking it out of scope, but WO §14.4 and the input
  say to untrack it. The later decision wins (FR-048).
- **A4 — `kill_cuems` location.** Settled by the clarification of 2026-10-17: the kept copy stays at
  `dev/scripts/kill_cuems.sh`, as WO §14.1 says (FR-045).
- **A5 — Clarify list.** The input names WO §12 (Q1–Q10) as the clarify list. This spec therefore
  carries each question's **recommended answer as a provisional default**, marked "provisional (WO §12
  Qn)", and uses no `[NEEDS CLARIFICATION]` markers. The 2026-10-17 clarify session settled Q1, Q3, Q6
  and Q8 (see Clarifications) and added the `dev/scripts/` decision. Q2, Q4, Q5, Q7, Q9 and Q10 keep
  their recommended answers as **accepted defaults**. They are still marked "provisional" so that a
  maintainer can overturn one cheaply before its task runs.
- **A6 — Indicative measurements.** M4/M5 were measured with an editable cuems-utils 4 commits ahead of
  its tag, and with a stub for the absent `libmtcmaster.so.0` in both arms. They are indicative only.
  FR-003 re-measures on this branch.
- **A7 — The `gh` CLI was not available at planning time.** The PR state of heads 22–24 is checked at
  the start of implementation (FR-002).
- **Out of scope**: publishing (PyPI, `.deb` upload); relocking `poetry.lock`; CI on `main`/`rc_1`; any
  edit to a sibling repository; moving or cutting tags; new behaviour; renumbering the version.

## Traceability to the work order

FR-060 deletes the WO, so each of its sections must have a home in 009.

| WO § | Home in 009 |
|---|---|
| 0 Decisions | Context: D1–D5 |
| 1 Goal / scope | Context, Assumptions (out of scope) |
| 2 Measurements | M1–M8; re-measured into `evidence/` (FR-002) |
| 3 Strategy, methods, commit shape | FR-001, FR-005, FR-061 |
| 4, 4.1 Inventory, sweep | Inventory table, FR-006…FR-009 |
| 5 Conflict rules | FR-004 |
| 6 Seams | FR-010…FR-019a |
| 7 Packaging | FR-030…FR-038 |
| 8 Siblings | FR-020…FR-023 |
| 9 Docs | FR-040, FR-041 |
| 10 Acceptance | SC-001…SC-011 |
| 11 Order | FR-061; seed for `tasks.md` |
| 12 Open questions | Clarifications (Q1, Q3, Q6, Q8 settled); A5 (the rest, accepted defaults) |
| 13 Measurement recipe | `research.md` / `evidence/` (plan phase) |
| 14 Cleanup + CI | FR-045…FR-059, SC-009, SC-010 |
