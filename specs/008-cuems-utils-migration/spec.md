# Feature Specification: Migrate onto cuemsutils' post-008 public API

**Feature Branch**: `feat/xml-refactor` (spec directory `008-cuems-utils-migration`; spec-kit's
branch hook deliberately **not** run — this repository's share of the ecosystem-wide xml-refactor
lives on the shared branch name, see `specs/planning/xml-refactor/00-runnable-flow.md` §1)
**Base**: `feat/nodelist-modify-dispatch` @ `dbc9e6d` (decision 2026-09-25, not `rc_1`)
**Created**: 2026-09-28
**Status**: Planned and tasked 2026-09-28; `/speckit.analyze` findings applied — ready for `/speckit.implement`
**Input**: `specs/planning/xml-refactor/` bundle (00–04), `00-runnable-flow.md` §3 context block,
and thirteen measurements taken 2026-09-28 at `afbd5cf` that the bundle does not carry (M1–M13).

## Context

`cuemsutils` has moved to a typed, public object API (its features 006–010): the node vocabulary is
`node_role` (`controller` / `node` / `firstrun`) instead of `node_type` (`NodeType.master` / …),
`adopted`/`online` decode to real booleans, the `cuemsutils.xml` package is internal machinery that
exports nothing, and the show document (`script`) is at version 2. This engine still speaks the old
dialect in a handful of places. Some of those places **stop resolving** (loud, at import, once
upstream US10 removes the deprecated paths). The dangerous ones **keep resolving and return the
wrong answer** (007 FR-030a-ii): nothing fails and the operator is told something false.

This feature is on the ecosystem's critical path: upstream US10 (deleting the deprecated surface) is
gated on a measured census of zero consumer imports, and `BaseEngine.py:17` / `ControllerEngine.py:15`
are two of them.

### Measured 2026-09-28 — what the bundle does not say

| # | Finding | Consequence for this spec |
|---|---|---|
| **M1** | **The baseline suite is red**, not green: 28 failed, 7 errors, 720 passed (45 files, 86.6 s) at `afbd5cf`, against the editable sibling `cuems-utils` (`feat/xml-refactor` @ `0ba239b`, `__version__ = 0.1.0rc16`). Two causes, both *the library has moved past the fixtures*: (a) the library now **refuses** `dev/test_xml_files/network_map.xml` (retired `<node_type>`; `network_map` has no convert-on-read — the error names `cuems-migrate-network-map`) — every failure but two; (b) `test_default_mappings_valid` raw-validates `dev/test_xml_files/settings.xml` against a `settings.xsd` that went to **version 2** in `cuems-utils` `782f669` (2026-09-23), retiring `audio_cards`/`universes`. Evidence: `evidence/baseline-suite.txt` | "Never implement on a red suite" must be reconciled — see FR-001/FR-002 and Assumption A1 |
| **M2** | `dev/test_xml_files/network_map.xml` is **not** a non-shipped exempt fixture: `tests/fixtures.py:35`, `:128`, `:442` load it and seven test files depend on it | It moves **out** of the exempt set and **into** scope. The exempt set is `dev/network_map.xml` and `dev/CuemsEngine_old.py` only |
| **M3** | `partition_by_adoption` has **no public path**. It exists only on `cuemsutils.xml.settings.NetworkMap`, which is internal (Q14). Inventory groups 2 and 3 and exit criterion 3 cannot all hold as written | Resolved by **Q1 → A**: public read + upstream report UR-1 |
| **M4** | "`script` is at version 2, the other five at 1" is stale: `versioning.CURRENT_VERSION` has `script` 2, `settings` 2, `hardware_outputs` 2; `network_map`, `project_mappings`, `project_settings` 1. The library's own comment (`versioning.py:30-32`) repeats the stale claim | Upstream report (UR-2). The engine reads neither retired `settings` field — measured by grep over `src/` |
| **M5** | The deploy manifest (`CuemsDeploy.py:647-652`) ships `script.xml` **and** the project's `mappings.xml` and `settings.xml` | C11 reaches `script` only today; a future version bump of `project_mappings` or `project_settings` extends it (FR-020) |
| **M6** | Converting the `network_map` fixture to `node_role` is itself the failing-first test for FR-030a-ii sites 1–2: against the pre-migration code, `_controller_ip_from_map` then raises *"No controller node found"* on a map that contains one | The red baseline and TDD's red step coincide; they are separated in time by FR-002 |
| **M7** | `poetry.lock` pins `cuemsutils` **0.1.0rc11** from PyPI; the dev environment is an editable sibling at rc16 whose installed metadata is stale at rc12. `poetry install` (CLAUDE.md's build step) would silently replace the editable library with rc11 | rc16 is also unpublished; resolved by clarify: pin now, re-lock at publish, CI red by construction meanwhile (FR-017, FR-017a) |
| **M8** | By reading (to be confirmed by a characterization test in the plan): `find_hosts` (`BaseEngine.py:433`) calls `get_nodes_by_adoption` **on `self.cm.network_map`** — the typed document, which on the post-007 library carries no such method — a *third* independent defect in the same method, before the wrapper bug F1 names | Supports **Q2 → A** (delete); the characterization run confirms or refutes it before deletion |

**Measured during `/speckit.plan`, 2026-09-28** (full method in `research.md`):

| # | Finding | Consequence |
|---|---|---|
| **M9** | The deprecated `XmlReaderWriter(...).read_to_objects()` path that `read_script` uses **does not convert on read**: it rejects version-1 `complex_test/script.xml` (`<duration>00:00:00.000</duration>`). `CuemsScript.load` reads the same file. **Against the current library the engine cannot load any version-1 show today** — a third baseline-failure cause, hidden behind M1(a) | FR-007 is a fix, not hygiene; its failing-first test surfaces once the `network_map` fixture is converted |
| **M10** | The public `ConfigManager.network_map` still holds `{"node": node}` **wrappers** in `node_list`. The bundle's "shape inverts" applies only to `partition_by_adoption`'s return value; under Q1 → A the existing unwrap stays correct, and *applying* the inversion is what would yield `None` uuids | FR-009 |
| **M11** | `node_role` decodes to the `NodeRole` enum; `node_role == "controller"` is **`False`** | FR-005: compare to the enum, never a string |
| **M12** | Node `uuid` decodes to `cuemsutils`' `Uuid`: equal and hash-equal to its string, but **not orderable** — `sorted()` raises `TypeError`. `get_cluster_status` returns `sorted(adopted)`, so the `cluster_status` contract breaks on any map the current library loads | FR-009a; upstream report UR-4 |
| **M13** | `CTimecodeType` is `<xs:choice minOccurs="0">`: an empty `<duration/>` is valid, and `CuemsScript.load` returns `media.duration is None` for it in a version-2 document | A `None` duration comes from **real documents**, not only in-memory construction; FR-016b covers it |

All other coordinates in `03-migration-inventory.md` were re-verified unchanged at `afbd5cf`:
`BaseEngine.py` :17/:33/:410/:433/:440/:443/:505; `ControllerEngine.py` :15/:287/:937-943/:1418
(dual read :1434; callers :1489/:1553/:1738); `ActionHandler.py` :38-39/:516/:542/:784-785; the
five `CTimecode(cue.media.duration)` wraps; `pyproject.toml:41`; `debian/control:18`.

## Clarifications

### Session 2026-09-28 — raised by `/speckit.specify`, answered by the maintainer

- **Q1 (M3)**: `partition_by_adoption` is reachable only through internal `cuemsutils.xml` — what
  replaces the adoption read? → **A: read `adopted` directly off the public
  `ConfigManager.network_map` node objects (already a real `bool` after 007), and file upstream
  report UR-1 asking for a public non-mutating partition.** Rejected: B (a named internal import —
  reopens Q14 and keeps this repository in the census US10 is gated on); C (block on upstream —
  this feature is on the critical path). Filtering on a typed field the library decoded is
  *consuming* the node model, not re-implementing it (FR-030a-i holds). Switching to a public
  partition once one exists is a one-line follow-up, not this feature's work.
- **Q2 (F1, M8)**: `find_hosts` — delete, or fix-and-wire? → **A: delete.** A characterization run
  showing its current unconditional failure on a valid map is captured first, then the method is
  removed. Rejected: fix-and-wire — it has no caller in the seven-repository ecosystem,
  `_controller_ip_from_map` already serves the adjacent need, and wiring it means inventing a caller
  (constitution YAGNI). FR-030a-ii sites 3 (`:440`) and 4 (`:443`) are discharged by deletion.
- **Q3 (M1, M6)**: How is the red baseline brought to green without masking the FR-030a-ii red
  tests? → **A: sequence the fixture work.** (1) Convert `dev/test_xml_files/network_map.xml` to
  `node_role` with **no engine change** and capture that run — it is the failing-first evidence for
  sites 1–2 (`_controller_ip_from_map` raises "No controller node found" on a map that contains
  one). (2) Convert `dev/test_xml_files/settings.xml` to version 2. (3) Only then implement.
  Rejected: B (keep the retired-vocabulary fixture alongside a new one) — it preserves the fixture
  that makes the green suite certify the defect.

### Session 2026-09-28 — `/speckit.clarify`

- Q: Where does the nodes-before-controller ordering (C11) live? → A: **Both** a
  `## v0.1.0rc3 — UNRELEASED` entry in this repository's `CHANGELOG.md` **and** a
  release-procedure section in `cuems-relations` (the ecosystem index, checked out locally at
  `../cuems-relations`, `master` @ `c9f1cd9`; no such section exists there today), **plus** an exit
  criterion. The `cuems-relations` text is drafted in this feature's directory and handed off; it is
  not committed from this feature. *Revised by the maintainer 2026-09-28*: the answer first named a
  `debian/NEWS` file; that is replaced by the `CHANGELOG.md` entry, and **the rc2 → rc3 version bump
  is the coordination point for the `xml-refactor-merge-candidate` tag** (FR-019a).
- Q: Does `debian/control` get a `Breaks:` as well as an upper bound? → A: **No `Breaks:` of its
  own.** The `cuems-utils` relation gets the upper bound (FR-017); the engine's `cuems-common` floor
  is raised to the release that carries `cuems-common`'s existing `Breaks: cuems-nodeconf (<< 0.1.0-8)`
  (`1.3.0-23~` — confirmed in planning: the `Breaks:` landed in `cuems-common` `d92317d`
  2026-08-24 on unreleased branches only, after `1.3.0-22` shipped; matches `cuems-nodeconf`'s own
  `Breaks: cuems-common (<< 1.3.0-23~)`). Rationale: sibling `Breaks:` lines target co-consumers of a
  shared file, never the library; the engine's exposure is a `network_map.xml` written by a
  pre-`node_role` nodeconf, and inheriting the existing guard beats duplicating it.
- Q: `cuemsutils` 0.1.0rc16 is not on PyPI (latest published rc14, checked 2026-09-28), the lock is
  tracked and CI installs from it — how are lock and CI handled? → A: **Set the bounded pin in both
  files now; do not re-lock until rc16 is published.** CI on `feat/xml-refactor` is **red by
  construction** until then (`poetry install` refuses a lock that no longer matches
  `pyproject.toml`), recorded with that reason; the local suite against the editable sibling, with
  its environment recorded, is the evidence. Re-locking is an exit step performed once `cuems-utils`
  publishes (it tags last, D27). Rejected: a temporary git-source dependency (the pin would not
  state the gate until swapped back); untracking the lock (fixes nothing alone); asking upstream to
  publish early (reverses D27's ordering).
- Q: What happens to the tests tied to the deleted adoption read? → A: **Move four, rewrite one,
  retire one case.** The four `patch.object(controller, "_adopted_uuids_from_network_map", …)` sites
  (`test_cluster_warning.py:81`, `:337`; `test_nodelist_modify.py:410`, `:484`) move to feeding a
  typed node map so the real read runs — not a stub of the replacement, which would hide the
  wrapper/node inversion. `test_controller_gating.py:283` is rewritten as FR-009's test. Its
  string-form `adopted: "True"` case is **retired as a recorded event**: decoding `adopted` is the
  library's (FR-030a-i), so keeping it would be a node-model test in this repository. No test
  enforced the reload→register order; nothing retires there.
- Q: With `find_hosts` gone, what happens on a map with more than one controller? → A: **Log a
  loud structured error naming every controller's uuid and ip, then use the first match**
  (deterministic, documented). Matches the engine's warn-never-block rule for missing nodes; ends a
  silent failure (constitution: observability) without refusing to start on a misconfigured map.
  Rejected: no check (silent); refusing to start (turns a misconfiguration into a dead show).

- Q: Do the five `CTimecode(cue.media.duration)` wraps get cleaned up? → A: **Yes, in this
  feature** (maintainer decision, 2026-09-28; it overrides an interim "leave unchanged" default).
  Measured the same day, and it changes what "redundant" means:
  - `CTimecode(CTimecode(x)) == CTimecode(x)` — idempotent on a timecode (inventory §6).
  - **`CTimecode(None)` returns `00:00:00.000`.** The wrap is also a silent `None` → zero coalescer;
    dropping it naively turns a missing duration into an `AttributeError` on the playback path.
  - `script.xsd` makes the `<duration>` *element* required (`:137`, `:232`), and `CuemsScript.load`
    of the version-1 `dev/test_xml_files/projects/complex_test/script.xml` yields `CTimecode` for
    all six media cues. **Corrected during planning (M13):** the element's *content* is optional —
    an empty `<duration/>` loads as `None` from a valid version-2 document. So `None` reaches the
    playback path from real shows, which makes FR-016b a production requirement.

  Consequence (FR-016): the wraps go; the `None` case is kept as zero but made **explicit and
  logged**, since the constitution forbids silent failures.

## User Scenarios & Testing *(mandatory)*

The actors are the **show operator** (loads a project, presses GO, reads the cluster warning), the
**maintainer releasing the ecosystem**, and the **cluster** (controller + node hosts, upgraded by
package manager but fed show documents by the engine itself).

### User Story 1 — A controller on the new library finds itself and its nodes (Priority: P1)

A controller whose `network_map.xml` is written in the current vocabulary (`node_role=controller`,
boolean `adopted`/`online`) starts, resolves the controller address from the map, registers OSC
handlers for every adopted node, and gates GO on exactly the adopted-and-alive set — with no
deprecation warning from `cuemsutils`.

**Why this priority**: Today this path is either refused by the library (the map will not load) or,
once loadable, answers wrongly and silently — the FR-030a-ii class. It is the feature's reason to
exist.

**Independent Test**: A post-007 map fixture drives the controller-IP fallback, OSC-handler
registration and the arm-gate's required set; each assertion is shown to fail against the
pre-migration code before it passes.

**Acceptance Scenarios**:

1. **Given** a map whose one controller node carries `node_role=controller` and an `<ip>`, **When**
   the engine falls back to the map for the controller address, **Then** it returns that `<ip>` —
   and against the pre-migration code the same fixture raises "No controller node found".
2. **Given** a map with two adopted nodes and one unadopted, **When** OSC handlers are registered,
   **Then** handlers exist for exactly the two adopted uuids — never zero, never a `None` uuid.
3. **Given** the same map, **When** a project is loaded, **Then** the required set and the
   `missing`/`unreachable` lists published on `cluster_warning` are identical to what the
   pre-migration code published for the equivalent pre-007 map.
4. **Given** an operator adopts a node through `nodelist_modify`, **When** the map is re-read in
   place, **Then** the new node reaches the GO gate, with no ordering constraint between re-reading
   the map and registering handlers.

---

### User Story 2 — Shows still load and play across the script version change (Priority: P1)

An operator loads a project whose `script.xml` is either still version 1 or already converted to
version 2, and it loads and dispatches identically. An unconverted document carrying a
`fade_in`/`fade_out` action still plays (as play / stop), because the library converts it on read.

**Why this priority**: A show that will not load is the most visible failure there is. The fade-handler
deletion is only safe because of an ordering this story makes explicit.

**Independent Test**: Load and GO against a version-1 and a version-2 `script.xml`, including one
with a legacy fade action, and record both.

**Acceptance Scenarios**:

1. **Given** a version-1 `script.xml`, **When** the project loads, **Then** it loads, the file on disk
   is untouched, and cues dispatch as before.
2. **Given** a version-2 `script.xml`, **When** the project loads, **Then** it loads and dispatches
   identically.
3. **Given** a version-1 document with an action of type `fade_in`, **When** it is revealed, **Then**
   it behaves as `play` — delivered by the library's conversion, not by an engine handler.
4. **Given** a loaded show, **When** audio, video and DMX cues play, loop and reach their end,
   **Then** their durations, framerate conversions and follow/postwait timing are identical to
   before the duration-wrap cleanup.
5. **Given** a cue built in memory with no media duration, **When** it runs, **Then** it behaves as
   a zero-length cue as before, and a warning naming the cue is logged.
6. **Given** a `script.xml` newer than the installed library supports, **When** the project loads,
   **Then** the load fails with the library's distinguishable "newer than library" error surfaced to
   the operator, not a generic parse error.

---

### User Story 3 — The release gate refuses a mismatched library (Priority: P2)

The maintainer installs the engine beside a `cuems-utils` that is either too old (pre-rc16) or has
moved past it (0.1.1, where the deprecated paths are gone). The package manager refuses the
combination rather than letting the engine fail at import or answer wrongly at runtime.

**Why this priority**: Three sibling repositories already express the gate; this one and
`cuems-editor` are the holdouts (C7, F4). Without it, D27's coordinated release has no mechanical edge
here.

**Independent Test**: Read both dependency declarations and confirm they agree and are bounded on
both sides; where a packaging sandbox exists, attempt the out-of-range install and record the refusal
(or record it **not performed**).

**Acceptance Scenarios**:

1. **Given** the source and package dependency declarations, **When** compared, **Then** they state
   the same floor and both state an upper bound.
2. **Given** a library at `0.1.1`, **When** installation is attempted, **Then** it is refused.
3. **Given** a host with a `cuems-nodeconf` older than `0.1.0-8`, **When** this engine is installed,
   **Then** the package manager refuses, through the raised `cuems-common` floor.

---

### User Story 4 — The cluster is upgraded in an order that cannot strand a node (Priority: P2)

The maintainer upgrading a cluster upgrades every node host before the controller, because a
controller on the new library ships version-2 show documents to nodes at show-load time — a path no
package manager mediates (C11).

**Why this priority**: The only item in this feature that cannot be discharged in code. It fails at
show time, in front of an audience, not at install time.

**Independent Test**: The named release artefact states the ordering and why; the exit criteria
carry it; a trial against a node on the old library is performed and recorded, or recorded **not
performed**.

**Acceptance Scenarios**:

1. **Given** the release procedure, **When** read, **Then** it states "nodes before controller",
   names the documents the deploy ships, and names which of them are past version 1.
2. **Given** a node still on the old library and a controller on the new one, **When** a project is
   deployed and loaded, **Then** the outcome is recorded (expected: the node refuses the document).

---

### User Story 5 — Dead and deceptive code is removed, not dressed up (Priority: P3)

Code that exists only to work around the mutating adoption API, handlers for action types no document
will carry, and a method with no caller that fails unconditionally are removed — each removal
recorded with its reason — rather than migrated into something that merely *looks* current.

**Why this priority**: Pure risk reduction; nothing an operator sees changes. But a migrated-looking
dead method is exactly how the next reader treats a broken site as closed.

**Independent Test**: The named symbols are absent; the suite that characterized their callers is
green against the replacement contract.

**Acceptance Scenarios**:

1. **Given** the migrated tree, **When** searched, **Then** `get_nodes_by_adoption`,
   `_adopted_uuids_from_network_map` and `find_hosts` appear nowhere in `src/` or `tests/` (except
   the ban list in `tests/test_public_surface.py`), and
   `find_hosts`' pre-deletion failure is captured in `evidence/`.
2. **Given** the migrated tree, **When** searched, **Then** no `fade_in`/`fade_out` handler or
   supported-action entry remains, and the spec's ordering statement (FR-014) is cited where they
   were.

### Edge Cases

- **A map with no controller node** still raises "No controller node found" — the negative fixture
  must be re-checked to raise for *that* reason after the vocabulary change, not for a missing key
  (00-runnable-flow.md §7: a test red for the wrong reason is worse than one that fails).
- **A map with a node whose `adopted` is still a string** (hand-edited, pre-typing): the library's
  load decides; the engine does not re-parse booleans. If the library refuses, that is correct.
- **A map with two or more controllers**: the controller-IP fallback logs a structured error naming
  every controller (uuid, ip) and uses the first match; the engine still starts (FR-005a).
- **`online` vs `alive`**: `online` is nodeconf's ~30 s discovery view; `alive` is this engine's
  sub-second ping/pong, the only signal the GO gate trusts. Retyping `online` must not touch `alive`
  or the `cluster_status` / `cluster_warning` payload shape — both are cross-repository contracts
  (F2a).
- **nodeconf start-up window** (F2a): `cf5c4ad`'s socket-existence probe reports nodeconf available
  before it can serve an adopt. This feature must not deepen that dependency; the fix is nodeconf's.
- **Empty `node_list`** (fresh node boot): the controller-IP fallback raises its existing
  "No nodes found" error, unchanged.

## Requirements *(mandatory)*

### Functional Requirements

**Baseline and discipline**

- **FR-001**: The pre-change suite result MUST be captured as evidence before any source or fixture
  change, with the commit, the library version and the library's source (editable path or wheel)
  recorded alongside. *(Done 2026-09-28: `evidence/baseline-suite.txt`.)*
- **FR-002**: `/speckit.implement` MUST NOT start on an **unexplained** red suite. Per Q3, fixture
  work runs first and in order, with no engine change: (1) convert
  `dev/test_xml_files/network_map.xml` to `node_role` and capture the run; (2) convert
  `dev/test_xml_files/settings.xml` to version 2. After step 2, every remaining failure MUST be a
  recorded failing-first test of FR-003 (controller lookup, sites 1–2) or FR-007 (version-1 script
  load, M9), each named in the evidence with the reason it fails; any other failure blocks
  implementation.
- **FR-003**: Every FR-030a-ii site (§1 of the inventory: `BaseEngine.py` :33, :410, :440, :443) MUST
  have captured evidence of failing against the pre-migration value, verified to fail **for the value
  it was written to catch**. Sites 1–2 (`:33`, `:410`): the step-1 run of FR-002 against the
  converted fixture. Sites 3–4 (`:440`, `:443`, inside `find_hosts`): discharged by deletion (Q2) — a
  characterization test run against a valid post-007 map showing the method's current failure (and
  confirming or refuting M8), captured, then removed with the method.
- **FR-004**: No test of the node model itself (parsing, vocabulary, boolean decoding) MAY be added
  to this repository (007 FR-030a-i). Tests assert the engine's behaviour given a node map.

**Group 1 — node vocabulary**

- **FR-005**: The controller MUST be identified by the library's role vocabulary, not by the string
  `"NodeType.master"`. The `CONTROLLER_NETWORK_FLAG` constant is removed or redefined from the
  library's role type; no string literal of either vocabulary remains in `src/`.
- **FR-005a**: When the node map holds more than one controller, the controller-IP fallback MUST
  log a structured error listing every controller's uuid and ip, then return the first match in
  map order. It MUST NOT raise for this reason. A test MUST show both the error and the returned
  address; it fails against the pre-migration code, which logs nothing.
- **FR-006**: `find_hosts` MUST be deleted (Q2), taking with it the only `online == "True"`
  comparison and its `get_nodes_by_adoption` call. Wherever the engine still reads `online` or
  `adopted`, it consumes the boolean the library provides; no string comparison of either remains.


**Group 2 — deprecated imports**

- **FR-007**: Script loading (`read_script`) MUST use the public show object (`CuemsScript.load`),
  which converts version-1 documents in memory, loads version-2, and refuses a newer document (US2).
  Today's path cannot load a version-1 show at all (M9); the failing-first evidence is a project
  load of the version-1 fixture after FR-002 step 1.
- **FR-008**: Network-map access MUST use the public configuration surface (`ConfigManager`). No
  import from `cuemsutils.xml` or `cuemsutils.config` remains in `src/` — no exceptions (Q1 → A).

**Group 3 — mutating adoption API**

- **FR-009**: The surviving `get_nodes_by_adoption` call site (`ControllerEngine.py:287`; the other
  goes with `find_hosts`) MUST be replaced by a non-mutating read of each node's typed `adopted`
  field off the public `ConfigManager.network_map` (Q1 → A). Because that map keeps the
  `{"node": …}` wrapper (M10), the read unwraps it exactly once. A test MUST show that registering
  handlers for N adopted nodes registers N handlers with non-`None` uuids, and that the map is
  field-for-field unchanged after the read.
- **FR-009a**: Node uuids MUST leave that read as `str` (M12), so `cluster_status`'s sorted lists,
  OSC addresses and `set[str]` comparisons keep working. A test MUST call `get_cluster_status` with
  a map loaded through the public surface and assert sorted string lists; it fails against the
  pre-migration code with `TypeError`.
- **FR-010**: `_adopted_uuids_from_network_map` MUST be deleted, not ported; its three callers read
  the same non-mutating source. The one-pass hazard docstring (`ControllerEngine.py:272-277`) and
  the "ORDER MATTERS" convention (`:937-943`) are removed as obsolete, and the spec records this as a
  simplification the migration buys.
- **FR-010a**: Tests that reach the deleted method MUST move to the new contract by feeding a typed
  node map, never by stubbing the replacement read: `test_cluster_warning.py:81`, `:337` and
  `test_nodelist_modify.py:410`, `:484`. `test_controller_gating.py:283` MUST be rewritten as
  FR-009's test, and its string-form `adopted` case retired, with the retirement and its reason
  (FR-030a-i) recorded in `evidence/test-retirements.md`. Test counts before and after account for
  it (SC-006).
- **FR-011**: The `cluster_status` reply and `cluster_warning` broadcast MUST keep their exact shape
  (cross-repository contracts with `cuems-editor`).

**Group 4 — dead fade handlers**

- **FR-012**: The `fade_in`/`fade_out` handlers, their supported-action entries and dispatch-table
  entries MUST be deleted.
- **FR-013**: The deletion MUST NOT land in a build that can run against a library without the
  script 1→2 conversion — enforced by FR-017's floor, so the commit raising the `debian/control`
  and `pyproject.toml` floor precedes the commit deleting the handlers.
- **FR-014**: The spec states the ordering the deletion depends on: *the library's convert-on-read
  rewrites `fade_in`/`fade_out` to `play`/`stop` before the engine ever sees the document; that is
  behaviour-preserving because these two handlers already did exactly that; therefore the handlers
  are unreachable on any library at or above the floor.*

**Out-of-scope items that must still be recorded**

- **FR-015**: `BaseEngine.py:505`'s hardcoded `"script.xml"` (vs `cuems-editor`'s configured
  `script_file_name`) MUST be recorded as a trap for `cuems-utils` feature 012, and left unchanged.

**Group 6 — the duration wraps (in scope by decision, 2026-09-28)**

- **FR-016**: The five `CTimecode(cue.media.duration)` re-wraps MUST be removed —
  `run_cue.py:176`, `:430`; `loop_cue.py:112`, `:276`; `CueHandler.py:166` — consuming the
  `CTimecode` the library's `Media.duration` already returns (D17/D18b).
- **FR-016a**: Before removal, each site MUST be covered by a characterization test pinning its
  result for a `CTimecode` duration (including the framerate conversion at the four
  `return_in_other_framerate` sites), green before and after — a behaviour-preserving refactor under
  constitution II's refactor step.
- **FR-016b**: A `None` media duration MUST keep today's effective value, zero, but explicitly: each
  site (or one shared helper) treats `None` as zero **and logs a warning naming the cue**. A test
  for that warning is written first and fails against the pre-change code, which coalesces silently.
  No site may raise for a `None` duration (never auto-stop a running project).
- **FR-016c**: The cleanup changes no dispatch timing: the CLAUDE.md MTC-anchored reveal and
  postwait-tail invariants (`_effective_duration_ms`, `loop_cue` end detection) produce identical
  values for every duration the characterization tests cover.

**Group 5 — release gate**

- **FR-017**: `pyproject.toml` and `debian/control` MUST declare the same `cuems-utils` range,
  `>= 0.1.0rc16` and `< 0.1.1` (`<< 0.1.1~` in Debian syntax), modelled on `cuems-nodeconf`'s
  `debian/control:18-19`. The lock file is **not** regenerated on this branch while rc16 is
  unpublished; regenerating it so a fresh install cannot resolve rc11 (M7) is an exit step taken
  once `cuems-utils` publishes rc16.
- **FR-017a**: Until that re-lock, CI on this branch is red by construction. That state MUST be
  recorded in `evidence/` with its cause, and every suite result claimed by this feature MUST be a
  local run with its environment recorded (FR-001's format). No `poetry install` or `poetry lock` is
  run in the development environment during this feature: it would replace the editable sibling
  with rc11, or fail. **No pull request is opened from `feat/xml-refactor` until the re-lock has
  turned CI green** — constitution Workflow §4 ("each PR MUST include test evidence (CI pass)") is
  followed, not excepted. This costs nothing D27 did not already impose: nothing merges before the
  coordinated release.
- **FR-018**: `debian/control` MUST NOT add a `Breaks:` of its own. It MUST raise the
  `cuems-common` floor from `>= 1.0.0` to the release carrying `Breaks: cuems-nodeconf (<< 0.1.0-8)`,
  so that installing the engine beside a nodeconf that still writes `<node_type>` is refused
  transitively. A short comment in `debian/control` states why, in the style of `cuems-common`'s.

**C11 — ordering**

- **FR-019**: "Nodes upgrade before the controller" MUST appear in (a) a new
  `## v0.1.0rc3 — UNRELEASED` entry at the top of `CHANGELOG.md`, in an upgrade-notes section of
  that entry, (b) a release-procedure section drafted for `cuems-relations` and handed off as
  `specs/008-cuems-utils-migration/handoff-relations-release-order.md`, and (c) the exit criteria
  (SC-008). No `debian/NEWS` file is created.
- **FR-019a**: The version moves `0.1.0rc2` → `0.1.0rc3` in this feature. The edited source is
  `__version__` in `src/cuemsengine/__init__.py`; the copies follow it — the `CHANGELOG.md` entry
  header, `pyproject.toml`'s `version`, and a matching `UNRELEASED` `debian/changelog` entry
  (`0.1.0rc3-1`). The entry stays `UNRELEASED` on this branch.
  **The bump is the coordination point for `xml-refactor-merge-candidate`**: the tag is cut on the
  commit that carries it, once every consumer flow lands (D27); only the release itself replaces
  `UNRELEASED` with a date and distribution. The rc3 entry also records this feature's changes
  (Groups 1–6), in the file's existing Added/Changed/Removed style.
- **FR-019b**: `cuemsengine.__version__` MUST be the single source of the version, enforced by a
  test that fails when `pyproject.toml`'s `version`, the first `CHANGELOG.md` `## v…` header, or the
  upstream part of `debian/changelog`'s first entry differs from it. `pyproject.toml` keeps a
  literal because Poetry requires one: measured 2026-09-28, Poetry 2.4 `check`/`build` refuse
  `dynamic = ["version"]` in package mode (*"Either [project.version] or [tool.poetry.version] is
  required"*). Maintainer decision the same day: keep `poetry-core` and the literal, guarded by the
  test — rejected a hatchling backend with `package-mode = false`, the `poetry-dynamic-versioning`
  plugin, and deferring to a separate feature.
- **FR-020**: Both texts MUST list the documents the deploy path ships (`script.xml`, project
  `mappings.xml`, project `settings.xml`) with their current schema versions, so that a future bump
  of `project_mappings` or `project_settings` is visibly a C11 change (M5).

**Exemptions and upstream reports**

- **FR-021**: The exempt set for the zero-`node_type` criterion is exactly `dev/network_map.xml` and
  `dev/CuemsEngine_old.py`, each with the reason "not shipped". `dev/test_xml_files/network_map.xml`
  is **not** exempt (M2) and is converted.
- **FR-022**: No file in `cuems-utils` is edited from this feature. Defects and gaps found are filed
  as upstream reports in this feature's directory: **UR-1** no public path to a non-mutating
  adoption partition (M3; filed per Q1 → A — the engine works around it by reading the typed field); **UR-2** the stale "only script moves"
  comment in `versioning.py` (M4); **UR-3** the stale editable-install metadata (rc12 vs rc16) that
  makes the environment misreport its own version (M7), if it is the library's to fix; **UR-4**
  `Uuid` is equal and hash-equal to `str` but not orderable, so `sorted()` over node uuids raises
  (M12); **UR-5** `XmlReaderWriter.validate`'s deprecation message recommends
  `CuemsScript.validate` for every schema, but that validates only a loaded show script — the public
  surface has no stand-alone validator for `settings`/`network_map`/`project_*` documents, only the
  `ConfigManager` loaders (measured 2026-09-28).
- **FR-023**: The F2a interaction (socket existence used as nodeconf readiness) is recorded for
  whoever fixes `cuems-nodeconf`; this feature does not add another caller of that probe.
- **FR-023a**: The deletion of `find_hosts` MUST be recorded against
  `cuems-relations/Plans/phase2-engine-late-binding.md:198-204` (R3), whose decision not to add a
  split-brain guard rests on "`find_hosts` raises on >1 controller" — a guard that has never run,
  since the method has no caller (re-swept 2026-09-28 across every checkout under
  `/disk/Projects/StageLab`, including `cuems-wsclient/` and `cuems-relations/`: code hits zero,
  documentation hits only). The deletion removes nothing that executed; the R3 premise was false
  before this feature. After it, the premise is **partly** true: >1 controller is now detected and
  logged (FR-005a), but not refused. Recorded in the same hand-off as FR-019(b), so R3's owner can
  decide whether logging suffices.

### Key Entities

- **Node map**: the cluster topology document — nodes with uuid, ip, role, adopted, online. Owned
  and interpreted by `cuemsutils`; the engine only reads it.
- **Show script**: the per-project cue document, versioned (currently 2); the engine loads it and
  ships it to nodes.
- **Deployed project documents**: `script.xml`, `mappings.xml`, `settings.xml` — the set C11 applies to.
- **Release gate**: the pair of dependency declarations plus the upgrade-order statement.
- **Upstream report**: a dated, reproducible defect note for `cuems-utils`, never a patch.

## Success Criteria *(mandatory)*

Exit criteria from `00-runnable-flow.md` §6, adjusted by M2/M3:

- **SC-001**: A search of shipped sources for the retired node vocabulary returns **zero**; the two
  exempt `dev/` files are listed by name with reason.
- **SC-002**: Each of the four FR-030a-ii sites has captured evidence of a test failing against the
  pre-migration value, for the right reason.
- **SC-003**: A search of shipped sources for internal `cuemsutils` imports returns **zero**.
- **SC-004**: `get_nodes_by_adoption`, `_adopted_uuids_from_network_map` and `find_hosts` appear
  nowhere in `src/` or `tests/`, except in `tests/test_public_surface.py`, whose ban list names
  them by design.
- **SC-005**: The two dependency declarations agree and are bounded above. The lock resolves rc16 —
  or, while rc16 is unpublished, is recorded **not performed** with CI's red-by-construction state
  (FR-017a), and carried as an open release step.
- **SC-006**: The suite is green, with pass/fail/error counts recorded before (28/7 red, 720 passed)
  and after; count growth is not a regression.
- **SC-007**: A show loads and dispatches against a version-1 and a version-2 `script.xml`, both
  recorded.
- **SC-008**: The nodes-before-controller ordering exists in `CHANGELOG.md`'s
  `v0.1.0rc3 — UNRELEASED` entry and in the handed-off `cuems-relations` draft, and is checked off as
  an exit criterion; `__version__` is `0.1.0rc3` and the version drift test (FR-019b) is green.
- **SC-009**: Every hardware/cluster item not performed is recorded **not performed**, per entry.
- **SC-010**: Zero `cuemsutils` deprecation warnings are emitted during a full suite run —
  including `tests/test_default_mappings_valid.py`, which moves off `XmlReaderWriter`: script
  fixtures via `CuemsScript.validate`, config fixtures via the public `ConfigManager` loaders.
- **SC-011**: A search of `src/` for `CTimecode(cue.media.duration)` returns **zero**, and every
  duration characterization test (FR-016a) is green before and after the removal.

Then, and only then, the signed annotated tag `xml-refactor-merge-candidate` on `feat/xml-refactor`,
on the commit carrying the rc3 version bump (FR-019a).
Nothing releases from this branch alone (D27).

## Assumptions

- **A1**: The M1 red baseline's *visible* failures are environmental (library ahead of fixtures):
  each traces to one of two fixture files, and converting them is test work, not a change to engine
  behaviour. Behind them sits a third cause that **is** an engine defect — M9, the version-1 script
  load — which surfaces only once the `network_map` fixture is converted, and is FR-007's to fix.
- **A2**: The editable sibling `cuems-utils` at `0ba239b` is representative of `0.1.0rc16`; no tag
  `v0.1.0rc16` exists locally (tags stop at rc14), so the version is read from `__version__`.
- **A3**: The engine reads neither `audio_cards` nor `universes` from `settings` (grep over `src/`,
  2026-09-28), so the settings 1→2 conversion needs no engine change.
- **A4**: cuemsutils features 011–014 do not block this feature (verified by the bundle in both
  directions); feature 013's edits to `NodeEngine.py` `node_hw_outputs` are out of scope here.
- **A5**: The constitution (v1.1.0) needs no amendment. Principle II is satisfied by FR-003;
  Principle I is served by deleting rather than rewriting (`find_hosts`, Q2). YAGNI supports
  deleting code with no caller.
- **A6**: Commits are GPG-signed; on a signing failure, retry — never bypass.
