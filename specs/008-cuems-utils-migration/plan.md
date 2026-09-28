# Implementation Plan: Migrate onto cuemsutils' post-008 public API

**Branch**: `feat/xml-refactor` (spec dir `008-cuems-utils-migration`; spec-kit scripts run with
`SPECIFY_FEATURE=008-cuems-utils-migration`) | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)
**Input**: [spec.md](spec.md) (clarified), the `specs/planning/xml-refactor/` bundle, and
[research.md](research.md)

## Summary

Move the engine off the `cuemsutils` surface that upstream US10 deletes, and fix what that surface
now gets silently wrong. Six groups: node vocabulary (onto `NodeRole`/`NodeIndex`), deprecated
imports (onto `CuemsScript.load` and `ConfigManager`), the mutating adoption API (one
non-mutating `str`-typed reader; delete the workaround and `find_hosts`), the dead fade handlers,
the release gate (bounded pins, `cuems-common` floor, the rc2 → rc3 version bump with an
`UNRELEASED` `CHANGELOG.md` entry carrying the upgrade order — the bump is the coordination point
for `xml-refactor-merge-candidate`), and the duration-wrap cleanup
(explicit, logged `None` → zero).

**Where this plan departs from the pasted §3 context block**, by recorded decision — the spec wins:

| §3 says | Plan does | Why |
|---|---|---|
| `dev/test_xml_files/network_map.xml` exempt, "not shipped" | converted; in scope | the suite loads it (spec M2) |
| `get_nodes_by_adoption` → `partition_by_adoption` | public map read + UR-1 | no public path (M3, clarify Q1 → A) |
| "the shape inverts: bare nodes" | **keep** the single unwrap | the public map still wraps (M10); applying the inversion is the silent failure |
| `find_hosts`: decide | deleted | clarify Q2 → A |
| `CTimecode` wraps: optional | in scope, `None` handled | maintainer decision; M13 |

**What research added that no earlier document knew**: the engine cannot load a version-1 show
against the current library at all (M9 — the deprecated reader does no conversion);
`cluster_status` raises `TypeError` on any typed map (M12 — `Uuid` is unorderable); an empty
`<duration/>` loads as `None` from a valid document (M13).

## Technical Context

**Language/Version**: Python 3.11.9 (pyenv; Poetry venv at `.venv`)
**Primary Dependencies**: `cuemsutils` 0.1.0rc16 (editable `../cuems-utils` @ `0ba239b`; unpublished,
PyPI latest rc14); `cuems-common` ≥ 1.3.0-23~ (packaging only). **No new dependency.**
**Storage**: XML files — `/etc/cuems/network_map.xml`, `<library>/projects/<p>/script.xml` (read only)
**Testing**: pytest, `poetry run pytest` (`testpaths = ["tests"]`, 45 files); baseline red —
28 F / 7 E / 720 P (`evidence/baseline-suite.txt`)
**Target Platform**: Debian (bookworm) controller and node hosts; two systemd services from one source
**Project Type**: single Python package (`src/cuemsengine/`), shipped as a `.deb`
**Performance Goals**: none new. The duration change must not alter dispatch timing (FR-016c);
the adoption reader is O(nodes) as today
**Constraints**: no edits to `../cuems-utils` (upstream reports only); no `poetry install`/`lock`
during the feature; CI red by construction until rc16 publishes; commits GPG-signed; never
auto-stop a running project
**Scale/Scope**: ~7 source files touched (`BaseEngine.py`, `ControllerEngine.py`,
`ActionHandler.py`, `run_cue.py`, `loop_cue.py`, `CueHandler.py`, plus packaging); ~8 test files
changed or added; 3 fixtures converted, 1 fixture added

No NEEDS CLARIFICATION remains; research R1–R11 resolved every unknown by measurement.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0. Checked, **not amended**.

| Principle | Status | How |
|---|---|---|
| **I. SOLID** | ✅ | One adoption reader replaces two divergent ones (single responsibility); controller role interpretation stays in the library (`NodeIndex.controllers`); `find_hosts` deleted rather than rewritten. Not a licence to restructure `BaseEngine` — none is planned |
| **II. TDD (non-negotiable)** | ✅ | Every behaviour change has a failing-first test with captured evidence: FR-003 sites 1–2 (fixture step 1), FR-007 (M9), FR-009/009a (M12), FR-005a, FR-016b. Removals (`find_hosts`, fade handlers, wraps) are refactors under characterization tests (FR-016a) or discharged by captured pre-deletion runs. The fixture-first sequence (FR-002) is what keeps each red test observable |
| **III. Integration & contract** | ✅ | Contract tests for `cluster_status`/`cluster_warning` and the public surface are written first; moved tests feed a **real typed map** instead of stubbing the reader (clarify Q4) — the constitution's own "not mocks" rule |
| **IV. Simplicity / YAGNI** | ✅ | Deletes: `find_hosts`, the mutation workaround, the ORDER-MATTERS convention, two fade handlers, five wraps. Adds: one reader, one duration helper — each justified by a current defect. No shim: the `None` → zero rule preserves existing behaviour made explicit, not a compatibility path |
| **V. Observability** | ✅ | Two silent paths become logged: >1 controller (error) and `None` duration (warning naming the cue) |
| Workflow §4 — *"Each PR MUST … include test evidence (CI pass)"* | ⚠ **exception** | CI is red by construction until rc16 publishes (clarify Q3). See Complexity Tracking |
| Workflow §6 — `scripts/link-dev.sh` supported | ✅ | untouched |
| Workflow §7 — layout | ✅ | all artefacts in `specs/008-*/`; the relations text is a hand-off file here, not `docs/` |
| Tech standards — CI blocks on lint | ✅ | black/isort/flake8 run locally on every changed file, since CI can't |

**Post-design re-check (after Phase 1)**: unchanged. The contracts add one test file
(`test_public_surface.py`) and no production abstraction. The R10 reading of exit criterion 4
("deleted, not renamed") is recorded, not silently assumed.

## Project Structure

### Documentation (this feature)

```text
specs/008-cuems-utils-migration/
├── spec.md                 # clarified
├── plan.md                 # this file
├── research.md             # R1–R11, all measured
├── data-model.md           # the engine-side view of library models
├── quickstart.md           # verification per exit criterion
├── contracts/
│   ├── cluster-payloads.md     # cluster_status / cluster_warning — UNCHANGED shape
│   ├── public-surface.md       # allowed cuemsutils imports + guard test
│   ├── controller-lookup.md    # _controller_ip_from_map table, incl. >1 controller
│   └── package-relations.md    # debian/control, pyproject, rc3 bump + CHANGELOG, hand-off
├── checklists/requirements.md
├── evidence/               # baseline-*, step1/step2 runs, failing-first per site,
│                           # test-retirements.md, not-performed.md, ci-red-by-construction.md
├── upstream-reports/       # UR-1 … UR-4 (Phase 2+)
├── handoff-relations-release-order.md   # for ../cuems-relations (Phase 2+)
└── tasks.md                # /speckit.tasks
```

### Source Code (repository root)

```text
src/cuemsengine/
├── core/BaseEngine.py        # :17 import; :33 constant removed; :401-415 controller lookup on
│                             #   NodeIndex (+ >1 error); :417-449 find_hosts DELETED;
│                             #   :503-510 read_script -> CuemsScript.load (:505 name kept, FR-015)
├── ControllerEngine.py       # :15 import removed; :259-298 _register_node_osc_handlers uses
│                             #   _adopted_node_uuids; :272-277 and :937-943 hazard docstrings
│                             #   removed; :1418-1440 _adopted_uuids_from_network_map DELETED;
│                             #   callers :1489 :1553 :1738 -> _adopted_node_uuids
├── cues/ActionHandler.py     # :38-39, :516-557, :784-785 fade handlers DELETED
├── cues/run_cue.py           # :176, :430 wraps -> duration helper
├── cues/loop_cue.py          # :112, :276 wraps -> duration helper
└── cues/CueHandler.py        # :166 wrap -> duration helper (helper's home: decided in tasks,
                              #   next to its five callers under cues/)

tests/
├── test_core_baseengine_controller_ip.py   # fixtures :34 :38 :101 -> node_role; >1 controller
├── test_controller_gating.py               # :283 rewritten (FR-009); string case retired
├── test_cluster_warning.py                 # :81 :337 typed map
├── test_nodelist_modify.py                 # :410 :484 typed map
├── test_action_cue.py                      # :254-330 fade classes retired
├── test_cluster_status_contract.py         # NEW — FR-009a / contracts/cluster-payloads.md
├── test_public_surface.py                  # NEW — contracts/public-surface.md
├── test_media_duration.py                  # NEW — FR-016a characterization + FR-016b
├── test_version_single_source.py           # NEW — FR-019b: __version__ vs its three copies
└── test_project_load.py                    # parametrized over v1 and v2 script (SC-007)

dev/test_xml_files/
├── network_map.xml             # converted (cuems-migrate-network-map)
├── settings.xml                # converted to v2 (convert_documents)
└── projects/complex_test_v2/   # NEW — v2 copy of complex_test

src/cuemsengine/__init__.py:5 (__version__ rc3 — the single source) · copies kept equal by
tests/test_version_single_source.py: pyproject.toml:7, CHANGELOG.md (## v0.1.0rc3 — UNRELEASED),
debian/changelog (0.1.0rc3-1 UNRELEASED) · pyproject.toml:41 (pin) · debian/control:18-19
```

**Structure Decision**: single existing package; no new modules except possibly the duration helper
(placed beside its callers in `cues/`, decided in tasks). No directory is added under `src/`.

## Phasing (input to `/speckit.tasks`)

Order is load-bearing; each phase ends on a recorded suite run.

| Phase | Content | Exit |
|---|---|---|
| **0 — evidence** | FR-002 steps 1–2 (fixtures via owning tools); attribute every failure | only named failing-first tests red; `step1/2` files + attribution |
| **1 — contracts first** | `test_public_surface.py`, `test_cluster_status_contract.py`, controller-lookup tests (incl. >1), duration characterization + `None` warning test | each new test red for its stated reason, captured |
| **2 — loader & vocabulary** | FR-007 `CuemsScript.load`; FR-005/005a controller lookup; delete `CONTROLLER_NETWORK_FLAG` | project-load + controller tests green |
| **3 — adoption** | `_adopted_node_uuids` (str, frozenset); rewire four sites; delete workaround + docstrings; move/rewrite tests (Q4); capture `find_hosts` failure, delete it | contract + gating + nodelist + warning tests green |
| **4 — dead code** | fade handlers + their tests (retirement recorded); duration wraps → helper | suite green; SC-004, SC-011 greps empty |
| **5 — release** | pins, `cuems-common` floor, rc3 version bump + `CHANGELOG.md` entry (last source change — the tag's coordination point), hand-off, UR-1…4, `ci-red-by-construction.md`, `not-performed.md` | SC-001…011 per quickstart |

Upstream reports (UR-1…4) and the relations hand-off can be written in parallel with any phase.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Constitution Workflow §4: PRs from this branch cannot show a CI pass until `cuemsutils` 0.1.0rc16 is published | The release gate (FR-017) requires `>=0.1.0rc16`; rc16 is unpublished and, by D27, `cuems-utils` publishes last. `poetry install` in CI then refuses the stale lock | A temporary git-source dependency (pin would not state the gate until swapped); publishing rc16 early (reverses D27); leaving the pin unbounded (the whole of C7). **Mitigation**: every suite claim is a local run with its environment recorded (FR-001 format), lint runs locally, and `evidence/ci-red-by-construction.md` names the one step that clears it (re-lock at publish) |
| Exit criterion 4 read as "no workaround survives" rather than literally "no adoption reader exists" (research R10) | With no public partition (UR-1), some reader of `adopted` must exist | Importing internal `partition_by_adoption` (clarify Q1 rejected it); leaving two readers (keeps the divergence F3 describes) |
