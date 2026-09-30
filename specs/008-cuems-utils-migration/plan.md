# Implementation Plan: Migrate onto cuemsutils' post-008 public API

**Branch**: `feat/xml-refactor` (spec dir `008-cuems-utils-migration`; spec-kit scripts run with
`SPECIFY_FEATURE=008-cuems-utils-migration`) | **Date**: 2026-09-28, re-planned 2026-09-29 after
merging `rc_1` (`956a0f3`) at `27b27f5` | **Spec**: [spec.md](spec.md)
**Input**: [spec.md](spec.md), the `specs/planning/xml-refactor/` bundle, [research.md](research.md)
(R1–R15)

## Summary

Move the engine off the `cuemsutils` surface that upstream US10 deletes, and fix what that surface
now gets silently wrong. Seven groups:

1. **Node vocabulary** onto `NodeRole`/`NodeIndex`; `find_hosts` deleted.
2. **Deprecated imports** onto `CuemsScript.load` and `ConfigManager` — which also fixes the engine's
   inability to load any version-1 show (M9).
3. **The mutating adoption API**: one non-mutating reader; the workaround, the one-pass hazard and
   the ORDER-MATTERS convention deleted.
4. **Dead fade handlers** deleted — with FR-014 corrected: `fade_out` → `stop` is a behaviour change
   (a fix), not preservation (M17).
5. **The release gate**: bounded pins, `cuems-common` floor, CI red by construction until rc16
   publishes, no PR before the re-lock.
6. **Duration wraps** removed, `None` → zero made explicit and logged.
7. **Identity**: `Uuid` canonical **as the library delivers it** — `as_id` at ingress (uuid4 →
   `Uuid`, anything else stays `str`, mirroring the library's own lenient decoder), `id_str` at
   egress (sorts, slices, JSON, OSC). Test ids all uuid4. **Shrunk 2026-09-29**: rc7 ships with
   `cuems-utils` 012–014, so no pre-012 bridges; the NOT PROVISIONED sentinel (011) gets a pre-load
   check; `node_host` is deleted; release order with 012 stated (G1).

Plus the release: `CHANGELOG.md` rc3–rc6 backfilled from history, **rc7 `UNRELEASED`** on top,
`__version__` the single source, `debian/changelog` left to the packaging branch; the rc7 commit is
the `xml-refactor-merge-candidate` coordination point.

**Where this plan departs from the pasted §3 context block**, by recorded decision — the spec wins:

| §3 says | Plan does | Why |
|---|---|---|
| `dev/test_xml_files/network_map.xml` exempt, "not shipped" | converted; in scope | the suite loads it (M2) |
| `get_nodes_by_adoption` → `partition_by_adoption` | public map read + UR-1 | no public path (M3, clarify Q1) |
| "the shape inverts: bare nodes" | **keep** the single unwrap | the public map still wraps (M10) |
| `find_hosts`: decide | deleted | clarify Q2 |
| fade conversion "behaviour-preserving" | preserving for `fade_in`, a **change** for `fade_out` | M17 |
| version bump: not in §3 | rc3–rc6 backfill + rc7, no `debian/changelog` | M15, clarified 2026-09-29 |
| ids: not in §3 | `Uuid` canonical, library-lenient | M12, M16, M18, clarified 2026-09-29 |

## Technical Context

**Language/Version**: Python 3.11.9 (pyenv; Poetry venv at `.venv`)
**Primary Dependencies**: `cuemsutils` 0.1.0rc16 (editable `../cuems-utils` @ `0ba239b`; unpublished,
PyPI latest rc14 — the lock after the merge); `cuems-common` ≥ 1.3.0-23~ (packaging). **No new
dependency.**
**Storage**: XML — `/etc/cuems/network_map.xml`, `settings.xml`, `<library>/projects/<p>/script.xml` (read only)
**Testing**: pytest, `poetry run pytest` (`testpaths = ["tests"]`, 49 files after the merge);
baseline red — **28 F / 7 E / 831 P** (`evidence/baseline-suite-postmerge.txt`; same 35 failing ids
as the pre-merge record)
**Target Platform**: Debian (bookworm) controller and node hosts; two systemd services from one source
**Project Type**: single Python package (`src/cuemsengine/`), shipped as a `.deb`
**Performance Goals**: none new. Duration and identity changes must not alter dispatch timing
(FR-016c; `rc_1`'s dispatch-reorder and chain-epoch suites stay green)
**Constraints**: no edits to `../cuems-utils`; no `poetry install`/`lock`; CI red by construction
until rc16 publishes and no PR until then; commits GPG-signed; never auto-stop a running project;
`debian/changelog` untouched on this branch
**Scale/Scope**: source — `BaseEngine.py`, `ControllerEngine.py`, `NodeEngine.py`,
`ActionHandler.py`, `run_cue.py`, `loop_cue.py`, `CueHandler.py`, new `tools/ids.py`, `__init__.py`;
packaging — `pyproject.toml`, `debian/control`, `CHANGELOG.md`; ~14 test files changed or added;
3 fixtures converted, 2 added

No NEEDS CLARIFICATION remains: R1–R15 measured; the four 2026-09-29 decisions are in spec
§Clarifications.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.0. Checked, **not amended**.

| Principle | Status | How |
|---|---|---|
| **I. SOLID** | ✅ | One adoption reader replaces two; role interpretation stays in the library; id conversion has one home (`tools/ids.py`) instead of ad-hoc `str()` at call sites; `find_hosts` deleted |
| **II. TDD (non-negotiable)** | ✅ | Failing-first with captured evidence for every behaviour change: FR-003 sites 1–2, FR-005a, FR-007, FR-009a, FR-016b, FR-019b, FR-024–FR-027 (`test_ids`, `test_cluster_identity`, the non-uuid4 warning). Removals are refactors under characterization (FR-016a, T048, T052) or discharged by captured pre-deletion runs |
| **III. Integration & contract** | ✅ | Contract tests first (`cluster_status`, public surface, ids); moved tests feed **real typed maps**, never a stubbed reader |
| **IV. Simplicity / YAGNI** | ✅ | Deletes more than it adds. Adds: one reader, one duration helper, one ids module — each tied to a measured defect. No shim: `None` → zero and non-uuid4-as-`str` both preserve existing behaviour, made explicit |
| **V. Observability** | ✅ | Silent or misleading paths become explicit: >1 controller (error), `None` duration (warning), an unprovisioned node (NOT PROVISIONED instead of a generic load error, FR-027), a stale pre-re-mint `output_name` prefix (listed in `cluster_warning.missing`, FR-026) |
| Workflow §4 — PR CI pass | ✅ | Followed: no PR from this branch until the re-lock turns CI green (FR-017a) |
| Workflow §5 — atomic commits | ✅ | One commit per checkpoint; backfill + rc7 bump (T043+T044) one commit, the tag's target |
| Workflow §6, §7; SPDX; lint | ✅ | `link-dev.sh` untouched; artefacts in `specs/008-*/`; SPDX on every new file; lint locally |

**Post-design re-check (2026-09-29)**: unchanged verdict. The ids module mirrors ~6 lines of the
library's internal decoder — recorded under Complexity Tracking, not a constitution issue.

## Project Structure

### Documentation (this feature)

```text
specs/008-cuems-utils-migration/
├── spec.md, plan.md, research.md (R1–R15), data-model.md, quickstart.md, tasks.md
├── contracts/
│   ├── cluster-payloads.md     # cluster_status / cluster_warning — shape unchanged, str at egress
│   ├── public-surface.md       # allowed cuemsutils imports + guard; Uuid only in tools/ids.py
│   ├── controller-lookup.md    # _controller_ip_from_map, incl. >1 controller
│   ├── ids.md                  # as_id / id_str — Group 7
│   └── package-relations.md    # pins, cuems-common floor, rc7 + rc3–rc6 backfill, hand-off
├── checklists/requirements.md
├── evidence/                   # baseline-suite.txt (pre-merge), baseline-suite-postmerge.txt, …
├── upstream-reports/           # UR-1, 2, 4, 5, 6, 7 (+ UR-3 if not environmental), NOTE-012
└── handoff-relations-release-order.md
```

### Source Code (repository root) — post-merge coordinates

```text
src/cuemsengine/
├── tools/ids.py              # NEW — as_id, id_str (T010)
├── core/BaseEngine.py        # :17 import; :33 constant; :315/:325 own uuid; :401-415 controller
│                             #   lookup; :417-449 find_hosts DELETED; :503-510 read_script
├── ControllerEngine.py       # :15 import; :259-298 registration; :272-277, :937-943 docstrings;
│                             #   :551/:568/:588 senders; :987 output_name; :1444-1466 reader
│                             #   DELETED (callers :1515/:1579/:1764); :1468-1488 _node_label;
│                             #   sorts :1557-:1767; :310, :472, :609 ingress
├── NodeEngine.py             # :632 own uuid
├── cues/ActionHandler.py     # :38-39, :541-564, :567-583, :810-811 fade handlers DELETED
├── cues/run_cue.py           # :176, :430 wraps
├── cues/loop_cue.py          # :112, :276 wraps
├── cues/CueHandler.py        # :212 wrap
└── __init__.py               # :5 __version__ 0.1.0rc7 — the single source

tests/  NEW: network_map_helpers.py, test_public_surface.py, test_ids.py, test_cluster_status_contract.py,
        test_cluster_identity.py, test_read_script.py, test_media_duration.py, test_identity_sweep.py,
        test_version_single_source.py
        CHANGED: test_core_baseengine_controller_ip.py, test_controller_gating.py, test_cluster_warning.py,
        test_nodelist_modify.py, test_project_load.py, test_default_mappings_valid.py, test_action_cue.py,
        + every file with a non-uuid4 literal (T008)

dev/test_xml_files/  network_map.xml, settings.xml converted; projects/complex_test_v2/, projects/fade_actions_v1/ added

pyproject.toml :11 version, :48 pin · debian/control :18-19 · CHANGELOG.md (rc7 UNRELEASED + rc6–rc3) · debian/changelog UNCHANGED
```

**Structure Decision**: single existing package. One new module, `src/cuemsengine/tools/ids.py`, in
the engine's existing utilities package — ids cross `core/`, the engines and `cues/`, so they belong
to none of them.

## Phasing (input to `/speckit.tasks`)

Order is load-bearing; each phase ends on a recorded suite run. `tasks.md` phase ↔ plan phase:

| Plan phase | Content | Tasks |
|---|---|---|
| **0 — evidence & base** | fixtures via owning tools; failure attribution; uuid4 test literals; surface guard; ids helpers | Phase 2, T004–T010 |
| **1 — contracts first** | controller lookup, `cluster_status`, cluster identity, moved adoption tests, script load, default-mappings, durations | *Tests* subsections of US1 (T011–T019) and US2 (T028–T033) |
| **2 — loader & vocabulary** | `CuemsScript.load`; `NodeIndex` lookup; delete `find_hosts`, the constant | T020–T022, T034 |
| **3 — adoption & controller ids** | `_adopted_node_uuids`; rewire; delete workaround; `as_id`/`id_str` in cluster paths | T023–T027 |
| **4 — dead code & durations** | duration helper + wraps; fade handlers (after the floor) | T035–T037, US5 T047–T051 |
| **5 — identity sweep** | remaining ingress/egress; non-uuid4 warning; audit | Phase 8, T052–T056 |
| **6 — release** | pins, floor, CI record; drift test; **backfill + rc7 as one commit, last**; hand-off; reports | US3 T038–T041, US4 T042–T046, Phase 9 |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Exit criterion 4 read as "no workaround survives" rather than "no adoption reader exists" (research R10) | With no public partition (UR-1), some reader of `adopted` must exist | Importing internal `partition_by_adoption` (clarify Q1 rejected it); two readers (F3's divergence) |
| `as_id` mirrors ~6 lines of the library's internal uuid decoder (uuid4 → `Uuid`, else `str`) | "`Uuid` canonical, as the library behaves" (clarified); the decoder is internal (Q14 forbids importing it) | Enforcing `Uuid(x)` at ingress (crashes on the nil uuid and uuid1 values the library accepts); `str` canonical (rejected in clarify). Replace the mirror when UR-6 yields a public helper. **Resolved 2026-09-30**: the mirror is deleted; `as_id` is cuems-utils 012's `cuemsutils.tools.coerce_identity` |
