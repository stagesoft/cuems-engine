<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Implementation Plan: Release-line reconciliation before 0.1.1-1

**Branch**: `009-release-line-reconciliation` | **Date**: 2026-10-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/009-release-line-reconciliation/spec.md` (clarified
2026-10-17, 5 answers), work order `specs/planning/release-line-reconciliation-0.1.1.md` @ `945ccba`.

## Summary

This feature makes `0.1.1-1` carry everything the engine shipped between `0.1.0rc3-1` and
`0.1.0rc6-5`, and turns the repository into a clean first stable release.

**Approach:**
1. **Absorb the release line.** Merge `origin/debian/bookworm` once, with the spec's FR-004
   resolutions. Merge `origin/rc_1` for ancestry, and the stray heads #22 and #23 by SHA. Copy the
   `rc5-2…rc5-6` entries and record that line with `-s ours`.
2. **Adapt, test-first.** Fix the 10 red tests the merge produces. Bring the absorbed code under
   008's identity and typed-map contract.
3. **Close the record.** Complete both changelogs, under a permanent live-ref test. Write the
   sibling obligations as reports, including the agreed structure for the deferred mock nodeconf
   (#24).
4. **Clean up last.** Run the first-stable cleanup (`dev/` reduced to `dev/scripts/`, `tests/`
   re-laid as unit/integration/contract).
5. **Prove it with the gate.** Restructure `ci.yml` into the pre-publication gate, dispatched with a
   `cuemsutils_ref` input, and prove it with one green run on the 009 head.

**Key measured decisions** (research):
- **CI install (R1)**: Poetry 2.4.1 refuses any install on the stale lock. CI therefore relocks in
  the job only, against the cuems-utils git ref, which changes `cuemsutils` and nothing else (48→48
  packages, 1 changed). It installs, then **restores** the committed `pyproject.toml` and
  `poetry.lock`, so that `test_lock_is_current.py::test_poetry_lock_is_current` stays a meaningful strict xfail.
- **`Media` sizes (R3)**: `Media.get("pixel_width")` returns `None`, not `Unset`, on 0.1.1. R-1 is
  likely a no-op, to be confirmed by a real version-2 load test.
- **X-1 (R4)**: cuems-utils' own 017 pre-spec already carries X-1…X-4, and it adds the
  targetless-`stop_project` seam. The X-1 xfails build targetless cues.

## Technical Context

**Language/Version**: Python 3.11 (pyenv 3.11.9; CI container `debian:bookworm`, python3 3.11)
**Primary Dependencies**: cuemsutils `>=0.1.1,<0.1.2` (installed from a cuems-utils git ref in CI and
editable locally; **unpublished**); pyossia (pinned dev wheel; `python3-pyossia (>= 2.0.0-rc6+124+cuems3)`
in production); pynng; python-osc; libmtcmaster (native). **No new runtime dependency.**
**Storage**: files only: `debian/changelog`, `CHANGELOG.md`, XML fixtures, evidence markdown
**Testing**: pytest + xdist + pytest-cov; markers derived from the directory (C2); strict xfails as
obligation trackers
**Target Platform**: Debian 12 bookworm (production and CI container); GitHub Actions hosted runners
for the gate
**Project Type**: Python service (two systemd services from one source tree) plus Debian packaging
(`cuems-engine`, `cuems-engine-mock`)
**Performance Goals**: none new. No runtime behaviour changes beyond what the release line already
shipped
**Constraints**:
- every commit GPG-signed
- no whole-side merge strategies and no cherry-picks (FR-001, FR-005)
- no committed relock
- no edits in sibling repositories, and no tag moves
- version stays `0.1.1` / `0.1.1-1`
- `specs/008-*` frozen
- `docs/` end-user only
**Scale/Scope**:
- 119 + 84 commits behind; 7 conflicting files (12 hunks); 10 merge-induced red tests
- 24 inventory items; about 15 identity sites
- 77 test modules to re-lay; about 25 `dev/` paths to delete or move
- 1 workflow restructured

## Constitution Check

*GATE: must pass before Phase 0 research. Re-checked after Phase 1 design (below).*

| Principle / rule | Status | How 009 satisfies it |
|---|---|---|
| **I. SOLID** | ✅ | Adaptations are local edits inside the absorbed classes. No new abstractions. `FollowRelay` and `PlayerHandler` keep their single responsibilities. The id conversion goes through the existing `tools/ids.py` (no new helper) |
| **II. TDD (non-negotiable)** | ✅ with one noted boundary | Every adaptation has a red test captured in `evidence/failing-first-*.txt` before its commit. The merge commit itself is the red step for A-1…A-6. New tests go red first: identity cases, R-1…R-4, A-7, the changelog test, the layout test. **Boundary**: the `ci.yml` restructure has no pytest test. Its verification is the dispatched run (SC-010), the same evidence class the constitution's "PR discipline: CI pass" names. **Refactor step**: A-5's conversions at sites that do not leave the process (dict keys, log joins; clarified Q5) are the *refactor* step of Red-Green-Refactor. They run under tests that are already green and change no observable behaviour; T041 records the covering tests per touched function. Any such site whose behaviour does change gets its own red test |
| **III. Integration & contract testing** | ✅ | The re-layout gives integration tests their own directory and job, running against real NNG, sockets and pyossia on the hosted runner. Contract tests get their own directory (C2) |
| **IV. Simplicity & YAGNI** | ✅ | Mock entry points stay put (FR-049). No manifest file (clarified). No `gh-pages.yml` edit (R7). No relock tool. R-1 gets code only if its test is red (R3). #24 is not built in 009 |
| **V. Observability** | ✅ | Absorbed code keeps its structured logs. Adaptations add none silently. The changelog test's skip is loud. The gate summary records the cuemsutils commit, the counts and the xfails |
| No new runtime dependency | ✅ | None. CI-only `coverage combine` uses the existing `coverage` / `pytest-cov` |
| Tech standard: "tests under `tests/` at repository root, mirroring `src/cuemsengine/`" (lines 117–118) | ⚠ **amended** | The split by kind (`unit/`, `integration/`, `contract/`) is written into the constitution by the MINOR amendment 1.1.0 → 1.2.0 (FR-046, R8; maintainer, 2026-10-18). Module names keep naming the code they cover |
| Tech standard / workflow §6: `scripts/link-dev.sh` (lines 122, 139) | ⚠ **stale path** | Corrected to `dev/scripts/link-dev.sh` in the same 1.2.0 amendment (FR-046) |
| Workflow §5: atomic conventional commits; no force-push to `master` | ✅ | Commit shape FR-061; no force pushes |
| Workflow §7: layout of specs, planning and docs | ✅ | Artefacts are in `specs/009-*`. `docs/` only gets end-user version fixes (FR-041). The WO in `specs/planning/` is deleted at the end (FR-060) |

**Gate result: PASS.** The only constitution edit is the 1.2.0 MINOR amendment (test-layout standard
and `link-dev.sh` path), made through `/speckit-constitution`. Nothing violates a
principle.

**Post-design re-check (after Phase 1)**: unchanged. The contracts add only:
- tests (C2's layout test, C3's changelog test)
- a CI workflow (C1)
- documents (C4 and C5 are records and messages)

None adds a dependency, an abstraction or a runtime path. C5 is explicitly *not* built in 009. PASS.

## Project Structure

### Documentation (this feature)

```text
specs/009-release-line-reconciliation/
├── spec.md                 # clarified 2026-10-17
├── plan.md                 # this file
├── research.md             # R0–R10
├── data-model.md           # release-engineering entities + state machine
├── quickstart.md           # commands, in execution order, with evidence targets
├── contracts/
│   ├── ci-gate.md                  # C1  ci.yml jobs, inputs, gate summary
│   ├── test-layout.md              # C2  tests/ layout, marker hook, classification rule
│   ├── changelog-completeness.md   # C3  live-ref changelog test
│   ├── engine-wire-additions.md    # C4  what siblings consume (W1–W6)
│   └── mock-nodeconf-structure.md  # C5  #24's agreed structure (FR-016a)
├── checklists/requirements.md
├── evidence/               # remeasure-*, suite-arm-*, failing-first-*, hotfix-rc5-equivalence,
│                           #   stray-head-sweep, identity-audit-009, changelog-check,
│                           #   relation-verdicts-009, bookworm-build, test-layout-moves,
│                           #   test-retirements, cleanup-check, ci-gate, environment
├── upstream-reports/       # cuems-utils-x1-x4, rc_1-mock-nodeconf-structure, rc_1-test-layout,
│                           #   {frontend,editor,power-bridge,nodeconf}-engine-contracts
└── tasks.md                # /speckit-tasks
```

### Source code (repository root): the state at hand-off

```text
src/cuemsengine/            # absorbed rc6-2…rc6-5 code + adaptations (FollowRelay.py, …)
  scripts/                  # packaged entry points (system_ports.py removed; mock_* stay, FR-049)
src/cuems/                  # DELETED (FR-048)
dev/
  README.md                 # NEW: what each tool is for; nothing here ships or runs in CI
  scripts/                  # link-dev.sh, kill_cuems.sh (kept), osc_send.py (moved in)
scripts/                    # REMOVED (osc_send.py moved to dev/scripts/)
tests/
  conftest.py               # + directory-marker hook (C2)
  README.md                 # classification rule
  support/                  # helpers, fixtures, network_map_helpers, reader, paths.py (DATA_DIR)
  data/                     # ← dev/test_xml_files/*
  unit/  integration/  contract/
debian/                     # merged rules/control/changelog (0.1.1-1 on top; rc1-1…rc6-5 below)
CHANGELOG.md                # v0.1.1 top; rc6 and rc5 sections extended
.github/workflows/ci.yml    # C1 (same file name)
.specify/memory/constitution.md   # 1.2.0 MINOR: tests/ split by kind; link-dev.sh path
specs/planning/release-line-reconciliation-0.1.1.md   # DELETED by the final task
```

**Structure decision**: one Python project with packaging. The only structural changes are three:
the `tests/` re-layout (C2), `dev/` reduced to `dev/scripts/` + `README.md` (clarified), and the
removal of top-level `scripts/` and `src/cuems/`.

## Phases (seed for `/speckit-tasks`; follows WO §11 and spec FR-061)

| Phase | Content | FRs / SCs | Ends with |
|---|---|---|---|
| **P0 Setup** | environment record; re-measure (start); baseline arm A | FR-002, FR-003 | `evidence/remeasure-start.md`, `suite-arm-A.txt` |
| **P1 Merge** | bookworm merge with FR-004 resolutions; arm B; rc_1 merge; #22/#23 by SHA; hotfix equivalence + entry copy + `-s ours` | FR-001, FR-004…FR-009 | behind-counts 0; arm B = the 10 expected reds |
| **P2 Adapt (US2)** | A-1…A-4, A-6 (red from arm B); A-5 identity (new red cases per wire site, then every `str(id)`); R-1…R-4 and A-7 (red first) | FR-010…FR-019a | the 10 reds green; `identity-audit-009.md` clean |
| **P3 Obligations (US4)** | X-1 strict xfails (targetless); cuems-utils report; sibling notes; #24 structure message (C5) | FR-016a, FR-020…FR-023 | SC-004, SC-006 |
| **P4 Packaging & changelogs (US3)** | changelog test red → `debian/changelog` body + `CHANGELOG.md` → green; rules audit; CACHEDIR; bookworm build; verdicts | FR-030…FR-038 | SC-007, SC-008 |
| **P5 Docs** | CLAUDE.md `stop_project` wording and dedup; `docs/unattended-playback.md` | FR-040, FR-041 | — |
| **P6 Re-fetch & full verify** | re-measure (hand-off); re-merge any delta (loop to P1); arms A/B ×3 interleaved; lint | FR-002, SC-001…SC-003 | `remeasure-handoff.md` |
| **P7 Cleanup (US5)** | one commit each: `dev/` (14.1), `dev/scripts` + docs paths + constitution 1.2.0 amendment (14.2), `tests/` re-layout + hook + layout test (14.3), strays (14.4); collect-diff after each | FR-045…FR-049 | SC-009 |
| **P8 CI gate (US6)** | `ci.yml` per C1; dispatch on the 009 head; record | FR-050…FR-057 | SC-010 |
| **P9 Hand-off** | tag message; rc_1 layout note; traceability check; **delete the WO** | FR-058…FR-060 | SC-011 |

**Ordering constraints**:
- P7 must come after P6, because moving files before the final merge turns clean merges into rename
  conflicts (WO §14).
- P8 must come after P7, because the jobs select tests by directory.
- If P6 finds that the line moved, its delta is merged and adapted **before** P7.

**Rollback**: every phase is a set of signed commits on the feature branch, and nothing outside it
moves. Abandoning a phase means resetting the branch to the previous phase's last commit, which is
recorded in evidence. No published artefact exists to undo.

## Risks

| Risk | Mitigation |
|---|---|
| The line moves mid-feature (rc6-6; #22/#23 land on rc_1) | Merge by SHA makes a second route a no-op; the P6 loop |
| Arm B shows reds other than the 10 (the cuems-utils checkout has moved 8 commits past its tag) | Record and classify in `suite-arm-B.txt`; run the gate against the **tag**, not the checkout |
| Environmental failures hide a real one in the sandbox | They move to `integration/`; the hosted run is authoritative (SC-009, SC-010) |
| cuems-utils lands rc17 during 009 | X-1 tests go XPASS → red; removed inside 009 (FR-021, accepted default) |
| `gh` missing locally | Dispatch from the web UI; record by hand in `ci-gate.md` |

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| CI relocks in the job (never committed) | R1: Poetry 2.4.1 refuses every install on the stale lock, and cuemsutils 0.1.1 is not on PyPI | Committing a relock is out of scope (publication act). Parsing the lock into pip pins is a new tool to maintain |
| The changelog test reads live git refs (clarified Q4 → B) and therefore needs a full-history fetch in `unit` | Keeps the test's source of truth equal to what shipped | The committed manifest was rejected at clarify |
