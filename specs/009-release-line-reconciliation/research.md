<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Research: Release-line reconciliation before 0.1.1-1

**Phase 0 of** [plan.md](plan.md) · **Measured** 2026-10-17 on `009-release-line-reconciliation` @
`945ccba`, after `git fetch --all --tags`. The scratch work lives outside the repository. Every
command below can be re-run.

## R0 — Re-measurement at plan time (FR-002, first pass)

| Measure | Value | Same as the WO? |
|---|---|---|
| `HEAD..origin/debian/bookworm` | **119** (`b8431a3`) | yes |
| `HEAD..origin/rc_1` | **84** (`698e777`) | yes |
| `35cbe78`, `d50ee4b`, `5a1811c`, `3c11c60` ancestors of `origin/rc_1`? | **no**, for all four | yes (still unmerged) |
| Newest ref activity | 2026-10-15 (`v0.1.0rc6-5`, the four stray heads) | no new release |
| `xml-refactor-merge-candidate^{commit}` | `e994a5e` | yes |
| `v0.1.0*` tags and where they are reachable from | `rc2`, `rc6-1…rc6-5` → bookworm; `rc5-2`, `rc5-3`, `rc5-6` → `v0.1.0rc5-6` only | yes. The FR-033 universe is bookworm ∪ rc_1 ∪ `v0.1.0rc5-6` |
| `gh` CLI | **not installed** | PR state of #22/#23 cannot be read. They are merged by SHA either way (FR-006) |

**Decision**: the snapshot in the spec stands. The implementation re-measures at its start and at
hand-off (`quickstart.md` §1).

## R1 — The stale lock under Poetry 2.4.1 (FR-052)

**Question.** `poetry.lock` resolves `cuemsutils 0.1.0rc16`, while `pyproject.toml` asks for
`>=0.1.1,<0.1.2`. What does Poetry 2.4.1, CI's pinned version, do with that? And which install path
keeps every *other* dependency at its locked version?

**Measured** (scratch copy of `pyproject.toml` + `poetry.lock`, Poetry 2.4.1 from `.venv-016`):

| Command | Result |
|---|---|
| `poetry check --lock` | rc 1: "pyproject.toml changed significantly since poetry.lock was last generated" |
| `poetry install --with dev` | **rc 1**, same message, before any package is installed |
| `poetry install --with dev --no-root` | **rc 1**, same |
| `poetry sync --with dev` | **rc 1**, same |
| `poetry add --lock "git+https://github.com/stagesoft/cuems-utils.git#xml-refactor-merge-candidate"` | **rc 0**. It rewrites the constraint to `{git = …, rev = "xml-refactor-merge-candidate"}` and relocks. **Diff of the 48 locked packages: only `cuemsutils 0.1.0rc16 → 0.1.1`**; the other 47 keep their locked versions |

So today's `ci.yml`, run on `feat/xml-refactor`, fails at "Install dependencies". It only appears to
work where a cached venv keyed on the lock hash is restored, which is exactly the trap that
`test_lock_is_current` was written to expose.

**Second-order finding.** `test_lock_is_current` runs `poetry check --lock` in the **workspace**. If
the job leaves the relocked files in place, that strict xfail passes, turns into XPASS(strict) and
fails the gate.

**Decision — "relock, install, restore":**
1. `poetry add --lock "git+https://github.com/stagesoft/cuems-utils.git#${CUEMSUTILS_REF}"`. This
   changes the job workspace only.
2. `poetry install --with dev --no-interaction`.
3. Read the resolved commit from the rewritten lock (`[package.source] resolved_reference` of
   `cuemsutils`), and log it together with `cuemsutils.__version__`.
4. `git checkout -- pyproject.toml poetry.lock`, then `git diff --exit-code`. pytest runs against
   the **committed** files, so `test_lock_is_current` still fails as designed.
5. The venv cache key is computed **after step 1**, from the rewritten lock plus the ref. A restored
   cache can then never carry another ref's cuemsutils.

**Rationale**: it is the only measured variant that installs at all and leaves the other 47 packages
unchanged. Nothing is committed (the spec's out-of-scope relock is respected), and the strict xfail
keeps its meaning.

**Alternatives rejected**:
- Commit a relock: out of scope, and it would name a git source in a published lock.
- `pip install` the locked versions parsed from the lock by a script: a new tool to maintain (YAGNI).
- `poetry export`: export fails on the same freshness check.
- Rewrite only the constraint to `0.1.0rc16`: the content hash still mismatches, and it would
  validate the wrong library.

**Note (local only)**: on this host `poetry add` needed `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`,
because the desktop keyring's D-Bus does not answer. Hosted runners have no keyring, and the CI job
sets the same variable defensively.

## R2 — Making the changelog test run in the gate (FR-033, SC-007)

**Question.** The clarified test reads `origin/debian/bookworm`, `origin/rc_1` and the `v0.1.0*` tags,
and skips when they are absent. `actions/checkout@v4` defaults to `fetch-depth: 1` and fetches no
tags and no other branches. In CI the test would therefore always skip.

**Decision**: the `unit` job, which also runs `tests/contract/`, checks out with `fetch-depth: 0`. It
then runs
`git fetch origin +refs/heads/debian/bookworm:refs/remotes/origin/debian/bookworm +refs/heads/rc_1:refs/remotes/origin/rc_1 --tags`.
Before that fetch the job needs `git config --global --add safe.directory`, which already exists.
`gate-summary` lists every skipped test with its reason, so a skip in the gate is visible. SC-007's
evidence is a local run with fresh refs **and** the gate run.

**Rationale**: it keeps the clarified "live refs" design (Q4 → B), and still lets the test act as a
pre-publication guard where it matters.

**Alternatives rejected**: the committed manifest (rejected at clarify); `fetch-depth: 0` without
the explicit branch fetch (gives history, but not the `origin/*` refs the test names).

**Test design notes for tasks**:
- The test resolves the three sources with `git rev-parse --verify`. If any is missing, it calls
  `pytest.skip(reason="missing refs: …")`.
- It reads changelog blobs with `git show <ref>:debian/changelog`.
- It splits entries on the `cuems-engine (` header line and compares the entries for the absorbed
  versions byte for byte.
- It parses `CHANGELOG.md` for `<!-- source: … -->` comments and inline `(0.1.0rcN-M, YYYY-MM-DD)`
  revisions.
- It gets the top version from `dpkg-parsechangelog` when available, falling back to the first header
  line. `dpkg-dev` is not in the CI image, and the header parse is sufficient.

## R3 — `Media` pixel and size fields on a version-2 load (FR-018, R-1, X-4)

**Measured** with cuemsutils 0.1.1, editable, at cuems-utils `2318dee`, which is 8 commits past the
candidate tag `4b336cd`:
- `Media.DECLARED_DEFAULTS` gives `pixel_width`, `pixel_height`, `file_size` and `file_md5` the value
  `Unset`.
- `helpers.py` documents `Unset` as "declared, but the key stays **absent**".
- `Media({'file_name': 'a.mp4', 'id': 'x'})` has keys `['file_name', 'id']`.
- `.get('pixel_width')` → **`None`**, and `.get('file_size')` → **`None`**.

**Decision**: the absorbed `media.get("pixel_width") is None → probe` branch is expected to be
correct as written. FR-018's test still loads a **real** version-2 script through `CuemsScript.load`
with the elements absent, because constructor and loader paths can differ, and it asserts the probe
fallback. If it passes, R-1 needs no code change, and X-4 in the cuems-utils report becomes "confirm
`Unset` stays key-absent (documented contract)" rather than a defect.

**Alternatives rejected**: an `is Unset` guard in the engine with no failing test (YAGNI;
constitution II).

## R4 — State of X-1 in cuems-utils

**Measured**:
- `grep -rn stop_project cuems-utils/src` → **nothing**, at the local HEAD `2318dee` and therefore at
  the tag.
- cuems-utils' own pre-spec for **017** (`2318dee`, 2026-10-17) already lists the engine's X-1…X-4,
  citing this repository's work order at `945ccba`, and plans to absorb rc17's `stop_project`.
- That pre-spec also records a seam, **S-1**: rc17's `stop_project` has no target, and utils 0.1.1's
  `action_target_required` would refuse it at save and at load until its adaptation A-1 lands. D5
  there leaves open whether *only* `stop_project` or *every* `*_project` value may omit a target.

**Decisions**:
1. The X-1 strict xfails (FR-020) build `stop_project` cues **without** a target, the shape rc17
   authors produce. That way they turn XPASS only when **both** the enumeration and S-1's adaptation
   have landed in utils.
2. The cuems-utils upstream report (FR-022) states the targetless expectation explicitly, as
   engine-side evidence for utils' D5.
3. **Cross-repository link.** The utils pre-spec links this work order **by commit (`945ccba`)**, so
   FR-060's deletion does not break it. The upstream report names
   `specs/009-release-line-reconciliation/` as the successor, so that utils' 017 artefacts can
   re-point. Editing them is the utils maintainer's act.

## R5 — Test layout in cuems-utils, the model FR-047 copies

**Measured** (cuems-utils `feat/xml-refactor`):
- `tests/` has `contract/`, `data/`, `golden/`, `integration/`, `packaging/`, `support/` and `unit/`
  (56 modules in `unit/`).
- **About 20 `test_*.py` files and one `testdev_*.py` still sit at its root.**
- Its `conftest.py` has **no** `pytest_collection_modifyitems`. Markers are not derived from the
  directory.
- Its `pyproject.toml` registers only `slow` and `expects_deprecation`.

**Decision**: copy the **directory vocabulary** (`unit/`, `integration/`, `contract/`, `support/`,
`data/`). The engine goes further than utils in two ways the spec requires:
- The root is empty of tests (SC-009).
- Markers come from the directory through a root-`conftest.py` hook (FR-047). `pyproject.toml`
  registers `unit`, `integration` and `contract`, keeps `slow`, and drops `cuems`.

`golden/` and `packaging/` are not needed: the engine has no golden outputs, and its packaging
invariants belong to `contract/`. The utils root leftovers are noted in the sibling note for
cuems-utils, as information only.

**Hook rule**: the path segment directly under `tests/` decides the marker. A test outside the three
directories fails collection with an explicit error, so a test cannot slip back to the root.
Existing hand-written `@pytest.mark.unit` and `@pytest.mark.integration` decorators are removed in
the move commit, because the directory makes them redundant. With `--strict-markers` the hook's
markers must be registered.

## R6 — Combined coverage across two jobs (FR-050)

**Decision**:
- Each job runs `pytest --cov=src --cov-report=` with `COVERAGE_FILE=.coverage.<job>` and uploads that
  file.
- The `coverage` job downloads both, runs `coverage combine`, then `coverage report
  --fail-under=45`, `coverage xml`, and the badge.
- `[tool.coverage.run]` gains `relative_files = true`, so that data from two containers combines
  without a path-mapping table. Both jobs use the same `debian:bookworm` container, but relative
  paths make the combine independent of the workspace path.
- `--cov-fail-under` is removed from the per-job runs, so splitting cannot move the gate.

**Alternatives rejected**: keeping one sequential test job, which contradicts D5/FR-050; and
`pytest-cov`'s combine inside a single job, which does not parallelise.

## R7 — Badge and pages gating (FR-054)

**Measured**:
- `ci.yml` pushes the badge whenever `github.event_name == 'push'`, on any branch.
- `gh-pages.yml` triggers on `workflow_run` of "CI" for `[master, rc_1]`; `master` is stale, and the
  default branch is `main`.

**Decision**:
- The badge steps move to the `coverage` job, under
  `if: github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/rc_1')`.
  A dispatch never pushes a badge.
- `contents: write` is granted to the `coverage` job only.
- `gh-pages.yml` is **not** edited in 009. Its `master` entry is a separate wart (recorded in
  `evidence/`). Its `workflow_run` fires for "CI" runs on `rc_1`, which the badge rule already covers,
  and changing the docs deploy is not required by any FR (YAGNI).

## R8 — Constitution text touched by the cleanup

**Measured** in `.specify/memory/constitution.md` v1.1.0:
- **Lines 117–118**: "Test files live under `tests/` at repository root, mirroring
  `src/cuemsengine/` structure". **No conflict** (maintainer, 2026-10-17). `unit/`, `integration/`
  and `contract/` live *inside* `tests/`, so every test file still lives under `tests/` at the
  repository root. "Mirroring" is read as each test module naming the source module it covers
  (`test_<module>.py`), which the moves preserve.
- **Lines 122 and 139**: `scripts/link-dev.sh`, a path that does not exist. The new path is
  `dev/scripts/link-dev.sh`.

**Decision** (revised 2026-10-18 after `/speckit-analyze` finding D1): one **MINOR amendment
(1.1.0 → 1.2.0)** through `/speckit-constitution`. It corrects the `link-dev.sh` path and rewrites
lines 117–118 to state the split by kind (`tests/unit/`, `tests/integration/`, `tests/contract/`,
plus `tests/support/` and `tests/data/`), so the constitution states the layout instead of relying
on a reading of "mirroring" (FR-046). It is MINOR because it changes a standard's content, not
only its wording.

## R9 — Post-merge test population (FR-047 sizing)

**Measured** as the union of `HEAD` and `origin/debian/bookworm` under `tests/`:
- **77 `test_*.py` modules**, 19 of them new from the release line, plus `d50ee4b`/`35cbe78`
  additions at merge time.
- 7 support files: `conftest`, `fixtures`, `helpers`, `network_map_helpers`, `reader`,
  `pytest_cuems_plugin` and `__init__`.
- 3 `testdev_*.py`.
- 7 modules carry `@pytest.mark.integration`.

**Decision**: the classification is decided per file at move time, by the FR-047 rule. WO §14.3's
initial split is the starting hypothesis, and the moves are recorded in
`evidence/test-layout-moves.md` (file → directory → signal).

## R10 — Smaller decisions

| Topic | Decision | Why |
|---|---|---|
| Agent context (CLAUDE.md) | Add a `<!-- SPECKIT START -->…<!-- SPECKIT END -->` block naming this plan. The markers did not exist yet | Required by the plan workflow; one line, re-pointed by the next feature's `/speckit-plan` |
| The 8 environmental failures (§6.1) | Re-checked on this host at arm A. Expected to land in `integration/` (FR-047) | SC-009's "0 environmental failures in unit/contract" |
| `kill_cuems` | Keep the shell `kill_cuems.sh` in `dev/scripts/`. Delete `kill_cuems_processes.py` after its argv[0] names are diffed against 869evtdf7's | Accepted default Q9 |
| `test_port_handler.py` | Split: the concurrent-draws case goes to `integration/`, the rest to `unit/` | Accepted default Q10 |
| CACHEDIR.TAG | Checked on the bookworm build. If present, strip it in `debian/rules` the way utils does | Accepted default Q2 |
