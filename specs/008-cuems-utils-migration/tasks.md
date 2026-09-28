# Tasks: Migrate onto cuemsutils' post-008 public API

**Input**: `specs/008-cuems-utils-migration/` — spec.md (clarified), plan.md, research.md,
data-model.md, contracts/, quickstart.md
**Prerequisites**: plan.md, spec.md (both present)

**Tests**: MANDATORY. Constitution II (TDD, non-negotiable) and spec FR-003. Every test task that
precedes an implementation task MUST be run and seen **red for its stated reason** before the
implementation task starts, with the run captured under `evidence/`.

**Standing rules for every task** (do not repeat per task):
- Run from the repo root with `export SPECIFY_FEATURE=008-cuems-utils-migration` and
  `E=specs/008-cuems-utils-migration/evidence`.
- **Never** run `poetry install` or `poetry lock` (FR-017a): the lock pins rc11 and would replace
  the editable `../cuems-utils`. Use `poetry run pytest -q -p no:cacheprovider …`.
- **Never** edit `../cuems-utils` (FR-022). Defects go into `upstream-reports/`.
- Tests feed **typed maps loaded through the public surface** (`tests/network_map_helpers.py`,
  T003). Never stub the adoption reader, and never assert how the library decodes a node — that is a
  node-model test and a regression here (FR-004, FR-030a-i).
- A red test must be red **for the value it targets**. When it fails, read the failure and confirm
  the reason before capturing it (00-runnable-flow.md §7).
- Lint every changed file locally (CI cannot, FR-017a): `poetry run black --check`, `isort --check`,
  `flake8` on `src/`.
- Commits are GPG-signed; on a signing failure retry, never `--no-gpg-sign`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5 from spec.md

---

## Phase 1: Setup

**Purpose**: evidence scaffolding and the one shared test helper.

- [ ] T001 Create `specs/008-cuems-utils-migration/evidence/README.md` indexing every evidence file this feature will produce (baseline-*, step1-*, step2-*, failing-first-*, us*-green.txt, test-retirements.md, not-performed.md, ci-red-by-construction.md, final-suite.txt), and create `evidence/test-retirements.md` and `evidence/not-performed.md` with a header and an empty table (columns: item, reason, date)
- [ ] T002 Record the environment check from quickstart.md §0 (`cuemsutils.__version__` is `0.1.0rc16` and `__file__` is under `/disk/Projects/StageLab/cuems-utils/`) in `evidence/step0-environment.md`; if either differs, STOP — every later run would test a different library
- [ ] T003 [P] Create `tests/network_map_helpers.py` with `typed_network_map(tmp_path, nodes)`: writes a current-vocabulary `network_map.xml` (namespace and root exactly as `dev/test_xml_files/network_map.xml`; per node `<uuid>`, `<mac>`, `<name>`, `<node_role>`, `<ip>`, `<adopted>`, `<online>` in that order) from a list of dicts, loads it with `ConfigManager(config_dir=str(tmp_path), load_all=False).load_network_map()`, and returns `cm.network_map`. Include SPDX header. No assertions about decoded types in this file

---

## Phase 2: Foundational — fixture sequence and the surface guard

**Purpose**: FR-002. Clear the M1 fixture failures in order, without touching `src/`, so every
remaining red test is a named failing-first test. **Blocks every user story.**

- [ ] T004 FR-002 step 1: convert `dev/test_xml_files/network_map.xml` with `poetry run python ../cuems-common/usr/bin/cuems-migrate-network-map dev/test_xml_files/network_map.xml` (positional path, in place); confirm with `grep node_role` that both nodes read `controller`/`node`; then run the full suite into `$E/step1-network-map-converted.txt` (tool invocation and output at the top of the file)
- [ ] T005 Write `$E/step1-attribution.md`: every failure and error from T004 attributed to exactly one of (a) FR-003 sites 1–2 — `No controller node found in network map` on a map that has one; (b) FR-007/M9 — version-1 `script.xml` rejected by `XmlReaderWriter` (`<duration>` *character data between child elements*); (c) the `settings.xml` fixture (T006). Any failure fitting none of them: STOP and report it
- [ ] T006 FR-002 step 2: convert `dev/test_xml_files/settings.xml` with `poetry run python -m cuemsutils.xml.convert_documents dev/test_xml_files/settings.xml`; confirm `doc_version="2"` and that `<audio_cards>`/`<universes>` are gone; run the suite into `$E/step2-settings-converted.txt`; append its attribution to `$E/step1-attribution.md`. Gate: only (a) and (b) failures remain
- [ ] T007 [P] Write `tests/test_public_surface.py` per `contracts/public-surface.md`: scan `src/cuemsengine/**/*.py` source text for imports from `cuemsutils.xml` or `cuemsutils.config` (all three spellings) and for the names `get_nodes_by_adoption`, `partition_by_adoption`, `_adopted_uuids_from_network_map`, `find_hosts`, `CONTROLLER_NETWORK_FLAG`, `NodeType.`; include the anti-vacuity guard (fail if zero files scanned or zero `cuemsutils` imports found). Run it: expect red naming `BaseEngine.py:17`, `ControllerEngine.py:15` and the symbols; capture to `$E/failing-first-public-surface.txt`

**Checkpoint**: suite red only for named failing-first reasons; the surface guard is red for the
two imports and the symbols.

---

## Phase 3: User Story 1 — A controller on the new library finds itself and its nodes (P1) 🎯 MVP

**Goal**: controller-IP fallback, OSC handler registration, the GO gate's required set and
`cluster_status` are correct on a current-vocabulary map, with no mutating API and no string
comparisons (FR-003, FR-005, FR-005a, FR-006, FR-009, FR-009a, FR-010, FR-010a, FR-011).

**Independent test**: `poetry run pytest tests/test_core_baseengine_controller_ip.py
tests/test_cluster_status_contract.py tests/test_controller_gating.py tests/test_cluster_warning.py
tests/test_nodelist_modify.py` green on typed maps; `find_hosts` and the workaround absent.

### Tests for User Story 1 — write first, see red, capture

- [ ] T008 [US1] In `tests/test_core_baseengine_controller_ip.py`, replace `_master`/`_slave` (`:33-38`) and the `:101` fixture with typed maps from `tests/network_map_helpers.py` (`_engine_with_map` sets `engine.cm.network_map` to the returned object). Keep every existing case. Add the negative "no controller" case using a map of `node_role=node` entries only (`contracts/controller-lookup.md`: never a pre-007 map, which the library now refuses for a different reason). Run against unchanged `src/`: expect the positive cases red with `No controller node found in network map`; confirm that message is the reason; capture to `$E/failing-first-site1-2-controller-lookup.txt`
- [ ] T009 [US1] In the same file add the FR-005a case: a map with two `controller` nodes (distinct uuid/ip); assert the first controller's `ip` is returned and exactly one ERROR log record lists both `uuid=… ip=…` pairs (use `caplog`; check `BaseEngine`'s `Logger` propagates to it, else patch `Logger.error`). Expect red (pre-change: no controller found at all); capture to `$E/failing-first-fr005a-multiple-controllers.txt`
- [ ] T010 [P] [US1] Create `tests/test_cluster_status_contract.py` per `contracts/cluster-payloads.md`: build the ControllerEngine the way `tests/test_controller_gating.py:41-70`'s `controller` fixture does, set `cm.network_map` to a typed map (controller + two adopted + one unadopted), stub only the liveness probe (`_probe_cluster_liveness`) — not adoption — and assert `get_cluster_status` returns exactly the keys `alive`/`adopted`/`controller`, both lists sorted and all `str`, `adopted` = the adopted uuids. Expect red with `TypeError: '<' not supported between instances of 'Uuid' and 'Uuid'`; capture to `$E/failing-first-fr009a-cluster-status.txt`
- [ ] T011 [P] [US1] Rewrite `tests/test_controller_gating.py:283-298` (`test_adopted_uuids_reader_handles_python_bool`) as FR-009's test: with a typed map of N adopted nodes, `_register_node_osc_handlers()` calls `communications_thread.register_osc_handler` once per adopted uuid plus the controller's own, every route `f"/{uuid}/*"` with a `str` uuid and none `None`; and the map is field-for-field equal before and after (compare `copy.deepcopy` snapshots). Delete the string-form `adopted: "True"` case; record the retirement (test id, reason: decoding `adopted` belongs to cuemsutils, FR-030a-i; clarify Q4) in `$E/test-retirements.md`
- [ ] T012 [P] [US1] In `tests/test_cluster_warning.py:81` and `:337`, replace `patch.object(controller, "_adopted_uuids_from_network_map", …)` with a typed map on `controller.cm.network_map` carrying the same adopted set; keep every assertion; add one assertion that `missing`/`unreachable` in the payload contain only `str`
- [ ] T013 [P] [US1] In `tests/test_nodelist_modify.py:410` and `:484`, replace the same `patch.object` with a typed map carrying the same adopted set; keep every assertion
- [ ] T014 [US1] Add `tests/test_find_hosts_characterization.py`: call `BaseEngine.find_hosts()` on an engine whose `cm.network_map` is a valid typed map with one adopted online controller; record exactly what it raises (research M8 predicts `AttributeError` from `self.cm.network_map.get_nodes_by_adoption`; F1 predicts the wrapper bug behind it). Capture the run to `$E/failing-first-site3-4-find-hosts.txt` with a line stating which prediction held. This test is temporary: it is removed in T018 and its retirement recorded
- [ ] T015 [US1] Run T012 and T013 against unchanged `src/`: they must be **green** (the old reader tolerates a typed map); capture to `$E/us1-moved-tests-pre.txt`. They are characterization for T017–T019, not failing-first

### Implementation for User Story 1

- [ ] T016 [US1] In `src/cuemsengine/core/BaseEngine.py`: add `from cuemsutils.tools.NodeList import NodeIndex, NodeRole`; rewrite `_controller_ip_from_map` (`:401-415`) to build `NodeIndex.from_nodes([item["node"] for item in node_list if isinstance(item, dict) and "node" in item], key=lambda n: str(n["uuid"]))`, read `.controllers`, raise the unchanged `ValueError`s for zero controllers / missing `ip`, and on `len > 1` log one `Logger.error` listing every `uuid=… ip=…` then return the first; update the docstrings at `:354` and `:402` from `NodeType.master` to `node_role=controller`. T008 and T009 go green
- [ ] T017 [US1] Delete `find_hosts` (`src/cuemsengine/core/BaseEngine.py:417-449`), then `CONTROLLER_NETWORK_FLAG` (`:33`) — in that order, so no step leaves an undefined name for flake8. Grep `src/` and `tests/` for both names: zero hits
- [ ] T018 [US1] Delete `tests/test_find_hosts_characterization.py` (its method is gone); record the retirement in `$E/test-retirements.md` (reason: evidence captured in T014, method deleted per clarify Q2)
- [ ] T019 [US1] In `src/cuemsengine/ControllerEngine.py`, add `_adopted_node_uuids(self) -> frozenset[str]` beside `_node_label`: iterate `(self.cm.network_map or {}).get("node_list", [])`, unwrap `entry["node"]` once (M10 — do NOT drop the unwrap), include `str(node["uuid"])` when `node.get("adopted") is True`, no string parsing; on exception `Logger.warning` with context and return `frozenset()`. Docstring: why it exists (no public non-mutating partition — UR-1), that it never mutates the map, and that uuids are `str` because `Uuid` is unorderable (UR-4, `cluster_status` sorts)
- [ ] T020 [US1] In `_register_node_osc_handlers` (`src/cuemsengine/ControllerEngine.py:259-298`), replace the `NetworkMap.get_nodes_by_adoption` block (`:285-293`) with `node_uuids |= self._adopted_node_uuids()`; delete the `⚠ get_nodes_by_adoption() mutates…` paragraph (`:272-277`) and replace it with one line: safe to call any number of times, it only reads. Delete `from cuemsutils.xml.Settings import NetworkMap` (`:15`). T011 goes green
- [ ] T021 [US1] Point the three callers (`src/cuemsengine/ControllerEngine.py:1489`, `:1553`, `:1738`) at `_adopted_node_uuids()`; delete `_adopted_uuids_from_network_map` (`:1418-1440`); in `_reload_network_map`'s docstring (`:928-943`) delete the `ORDER MATTERS` paragraph and state instead that re-registration after reload is ordinary, not order-sensitive. T010, T012, T013 green
- [ ] T022 [US1] Run the US1 independent test plus `tests/test_public_surface.py` (still red only for `BaseEngine.py:17`, which US2 removes); lint the two changed source files; capture to `$E/us1-green.txt`

**Checkpoint**: US1 complete — controller lookup, adoption, `cluster_status`, `cluster_warning` all on typed maps; FR-030a-ii sites 1–4 discharged.

---

## Phase 4: User Story 2 — Shows load and play across the script version change (P1)

**Goal**: `read_script` loads version-1 and version-2 shows and refuses newer ones (FR-007);
the duration re-wraps go, with an explicit, logged `None` → zero (FR-016–016c).

**Independent test**: `poetry run pytest tests/test_project_load.py tests/test_read_script.py
tests/test_media_duration.py tests/test_loop_rebase.py tests/test_effective_duration.py
tests/test_chain_anchoring.py tests/test_reveal_mechanism.py` green.

### Tests for User Story 2 — write first, see red, capture

- [ ] T023 [US2] Create the version-2 fixture: `cp -r dev/test_xml_files/projects/complex_test dev/test_xml_files/projects/complex_test_v2`, then `poetry run python -m cuemsutils.xml.convert_documents dev/test_xml_files/projects/complex_test_v2/script.xml`; confirm `doc_version="2"`; record the output in `$E/fixture-complex-test-v2.txt`. The v1 original stays untouched
- [ ] T024 [US2] Parametrize `test_complex_project_load_on_controller` in `tests/test_project_load.py` over `complex_test` and `complex_test_v2`. Run against unchanged `src/`: expect both red at `read_script` (v1 for M9's `<duration>` rejection); confirm the reason; capture to `$E/failing-first-fr007-script-load.txt`
- [ ] T025 [P] [US2] Create `tests/test_read_script.py`: (a) `read_script` on a v1 project leaves the file's bytes unchanged (hash before/after); (b) a copy of `complex_test_v2/script.xml` with `doc_version="3"` makes `read_script` raise the library's newer-than-library error (assert on its message fragment `newer than this library's current version`), not a generic parse error; (c) a missing file keeps raising `FileNotFoundError`. Use `tmp_path` project libraries. Capture the red run to `$E/failing-first-fr007-read-script.txt`
- [ ] T026 [P] [US2] Create `tests/test_media_duration.py` characterization (FR-016a), green **before** any wrap is touched: for `run_audioCue` and `run_videoCue` (`src/cuemsengine/cues/run_cue.py`), assert `cue._end_mtc == cue._start_mtc + <duration>.return_in_other_framerate(mtc.main_tc.framerate)` for durations `00:00:12.500` and `00:01:00.000` at framerates 25 and 30 (mock players/OSC as `tests/test_reveal_mechanism.py` does for `run_audioCue`; `run_videoCue` has **no existing coverage** — build its harness here); for `_effective_duration_ms` assert the body term equals `milliseconds_exact`. `loop_audioCue`/`loop_videoCue` are covered by `tests/test_loop_rebase.py` — add a duration-conversion assertion there only if it has none. Capture the green run to `$E/us2-duration-characterization-pre.txt`
- [ ] T027 [US2] In `tests/test_media_duration.py` add the FR-016b case: a cue whose `media.duration is None` (build it the way M13 measured — `<duration/>` in a v2 document loaded with `CuemsScript.load`, or set it directly) through each of the five paths: no exception, behaves as zero, and one WARNING naming the cue id. Expect red (pre-change: silent zero, no warning); capture to `$E/failing-first-fr016b-none-duration.txt`

### Implementation for User Story 2

- [ ] T028 [US2] In `src/cuemsengine/core/BaseEngine.py:503-510` (`read_script`), replace `XmlReaderWriter(schema_name="script", xmlfile=xml_file).read_to_objects()` with `CuemsScript.load(xml_file)` (already imported at `:12`); keep the `FileNotFoundError` check and the hardcoded `"script.xml"` (FR-015); delete `from cuemsutils.xml import XmlReaderWriter` (`:17`). T024, T025 and `tests/test_public_surface.py` go green
- [ ] T029 [US2] Add the duration helper in `src/cuemsengine/cues/` beside its callers (module name chosen to fit the package, e.g. a function in an existing shared module used by `run_cue.py`, `loop_cue.py` and `CueHandler.py`): returns `cue.media.duration` when it is a `CTimecode`; for `None` logs one `Logger.warning` naming the cue id and returns `CTimecode()` zero. Comment one line on WHY (empty `<duration/>` is schema-valid, M13)
- [ ] T030 [US2] Replace the five wraps with the helper: `src/cuemsengine/cues/run_cue.py:176`, `:430`; `src/cuemsengine/cues/loop_cue.py:112`, `:276`; `src/cuemsengine/cues/CueHandler.py:166` (keep each site's `.return_in_other_framerate(...)` / `.milliseconds_exact` and `CueHandler`'s `if cue.media else 0`). `grep -rn 'CTimecode(cue.media.duration)' src/` → zero. T026 stays green, T027 goes green
- [ ] T031 [US2] Run the US2 independent test; lint the changed files; capture to `$E/us2-green.txt` — FR-016c: every timing test that was green before T030 is green after

**Checkpoint**: v1 and v2 shows load; durations unchanged; empty durations visible in logs.

---

## Phase 5: User Story 3 — The release gate refuses a mismatched library (P2)

**Goal**: FR-017, FR-017a, FR-018 per `contracts/package-relations.md`.

**Independent test**: `sed -n 41p pyproject.toml` and `grep -n 'cuems-utils\|cuems-common' debian/control` match the contract.

- [ ] T032 [P] [US3] `pyproject.toml:41` → `cuemsutils = ">=0.1.0rc16,<0.1.1"`. Do **not** run `poetry lock`
- [ ] T033 [P] [US3] `debian/control:18` → two lines `cuems-utils (>= 0.1.0rc16),` and `cuems-utils (<< 0.1.1~),`; `debian/control:19` → `cuems-common (>= 1.3.0-23~),`; add a comment block above `Depends:` in the style of `../cuems-common/debian/control:51-56` stating why each bound exists (C7 gate; inherited `Breaks: cuems-nodeconf (<< 0.1.0-8)` because the engine reads `node_role`) and that the engine deliberately carries no `Breaks:` of its own
- [ ] T034 [US3] Write `$E/ci-red-by-construction.md`: CI's `poetry install --with dev` (`.github/workflows/ci.yml:38`, `:109`) refuses the rc11 lock after T032; rc16 unpublished (PyPI latest rc14, checked 2026-09-28); the single step that clears it is `poetry lock` once `cuemsutils` 0.1.0rc16 is on PyPI; cite constitution Workflow §4 and plan.md Complexity Tracking
- [ ] T035 [US3] Record in `$E/not-performed.md` (unless a packaging sandbox is available — then perform and capture): `dpkg` refusal against `cuems-utils` 0.1.1 (US3 scenario 2) and against `cuems-nodeconf` < 0.1.0-8 via the `cuems-common` floor (US3 scenario 3); and the re-lock (SC-005), reason: rc16 unpublished

**Checkpoint**: both declarations agree and are bounded; the red CI state is documented, not silent.

---

## Phase 6: User Story 4 — Nodes upgrade before the controller (P2)

**Goal**: FR-019, FR-019a, FR-020, FR-023a — the C11 ordering in `CHANGELOG.md`'s rc3 entry and in a hand-off for `../cuems-relations`; the rc2 → rc3 bump that `xml-refactor-merge-candidate` coordinates on.

**Independent test**: `poetry run pytest tests/test_version_single_source.py` green; quickstart SC-008 row — the rc3 `UNRELEASED` entry states the ordering, the reason and the three deployed documents with versions; the hand-off exists.

- [ ] T036 [US4] Create `tests/test_version_single_source.py` (FR-019b; SPDX header): `cuemsengine.__version__` is the single source, and the test asserts each copy equals it — `pyproject.toml`'s `[tool.poetry] version` (parse with `tomllib`), the first `## v<version>` header in `CHANGELOG.md`, and the upstream part (before the last `-`) of the first line of `debian/changelog`. Each assertion message names the stale file and the fix ("pyproject.toml:7 says X; set it to `__version__`"). Anti-vacuity: fail if the `CHANGELOG.md` header or `debian/changelog` line cannot be parsed. Run now: expect green (all four say `0.1.0rc2`); capture to `$E/us4-version-drift-pre.txt`
- [ ] T037 [US4] Version bump and changelog, per `contracts/package-relations.md` §Version bump and §`CHANGELOG.md`. **Edit the source first**: set `__version__ = "0.1.0rc3"` in `src/cuemsengine/__init__.py:5`, run T036's test and capture it **red** naming the three stale copies (`$E/failing-first-fr019b-version-drift.txt`); then bring the copies into line: (1) `pyproject.toml:7` `version = "0.1.0rc3"` (the literal Poetry requires — clarify: Poetry 2.4 refuses a dynamic version in package mode, measured; the test keeps it from going stale); (2) prepend to `debian/changelog` a `cuems-engine (0.1.0rc3-1) UNRELEASED; urgency=medium` entry (maintainer line in the file's existing format; bullets summarizing Groups 1–6 and the new `Depends:` bounds); (3) insert `## v0.1.0rc3 — UNRELEASED` above `## v0.1.0rc2 — 2026-05-19` in `CHANGELOG.md` (`:3`), matching that entry's style: a summary paragraph, `### Added` / `### Changed` / `### Removed` for this feature's changes (cite FR ids only where the rc2 entry cites spec ids), and an `### Upgrade notes` section stating — in this order — upgrade every node host before the controller; why (the controller converts show scripts to version 2 and deploys them to nodes at show load, no package manager mediates it); the deployed documents `script.xml` 2, `mappings.xml` 1, `settings.xml` 1; the new `Depends:` bounds. Do **not** create `debian/NEWS`. T036's test goes green. Run this task **last among source changes** (after US1–US5 are green): the bump commit is the tag's coordination point, so nothing that belongs in rc3 may land after it without amending the entry
- [ ] T038 [P] [US4] Write `specs/008-cuems-utils-migration/handoff-relations-release-order.md`: draft release-procedure section for `../cuems-relations` (same three items, plus the rule that a future bump of `project_mappings`/`project_settings` extends C11), and the FR-023a note: `Plans/phase2-engine-late-binding.md:198-204` (R3) relied on `find_hosts` raising on >1 controller; that guard never ran (no caller, re-swept 2026-09-28) and is deleted; after this feature >1 controller is logged as an error but not refused — R3's owner decides whether that suffices. Header: *draft for hand-off, not committed to cuems-relations from this feature*
- [ ] T039 [US4] Record US4 scenario 2 (old-library node + new-library controller, deploy and load) in `$E/not-performed.md` unless a two-host rig is available — then perform and capture

---

## Phase 7: User Story 5 — Dead and deceptive code is removed (P3)

**Goal**: FR-012–FR-014 (fade handlers). `find_hosts` and the adoption workaround were removed in US1 (T017, T021) because the vocabulary change could not land without them.

**Independent test**: `grep -rn "fade_in\|fade_out" src/cuemsengine/cues/ActionHandler.py` → zero; SC-004 grep empty.

- [ ] T040 [US5] Add to `tests/test_action_cue.py` a case: an `ActionCue` with `action_type="fade_in"` built in memory yields a `failed` result with reason `Unsupported action_type: 'fade_in'` (the `ActionHandler.py:244-245` path). Expect red now (the handler exists and returns `applied`); capture to `$E/failing-first-fr012-fade-unsupported.txt`
- [ ] T041 [US5] Delete from `src/cuemsengine/cues/ActionHandler.py`: `"fade_in"`, `"fade_out"` in `SUPPORTED_CUE_ACTIONS` (`:38-39`), `_handle_fade_in` (`:516-539`), `_handle_fade_out` (`:542-557`), and their `_ACTION_HANDLERS` entries (`:784-785`). Where they were, add one comment stating FR-014's ordering: the library's convert-on-read rewrites `fade_in`/`fade_out` to `play`/`stop` before the engine sees a document, which these handlers already emulated, and the `cuems-utils (>= 0.1.0rc16)` floor guarantees that conversion is present
- [ ] T042 [US5] Delete the T011/T012 fade classes in `tests/test_action_cue.py:254-330`; record each retired test id in `$E/test-retirements.md` (reason: handler deleted; behaviour now delivered by the library's conversion, FR-014). T040 goes green
- [ ] T043 [US5] Run `tests/test_action_cue.py` and the SC-004 grep (`get_nodes_by_adoption|_adopted_uuids_from_network_map|find_hosts` over `src/ tests/` → zero); lint `ActionHandler.py`; capture to `$E/us5-green.txt`

---

## Phase 8: Polish & cross-cutting

- [ ] T044 [P] Update `CLAUDE.md`'s field note *"A successful adoption re-reads network_map.xml in place … ⚠ Order is load-bearing: `get_nodes_by_adoption()` mutates…"*: the hazard is gone — `_reload_network_map` re-reads and re-registers through the non-mutating `_adopted_node_uuids`, with no ordering constraint. Keep the partial-success paragraph
- [ ] T045 [P] Write `specs/008-cuems-utils-migration/upstream-reports/UR-1-no-public-adoption-partition.md`, `UR-2-versioning-comment-stale.md`, `UR-4-uuid-unorderable.md` — each: observed, reproduction (the probe from research.md), expected, impact on this consumer, the workaround taken here. For UR-3 (stale `0.1.0rc12` dist metadata) first check whether a fresh `pip install -e ../cuems-utils` fixes it — if yes, record it in `$E/not-performed.md` as environmental and do not file
- [ ] T046 [P] Record `BaseEngine.py:505`'s hardcoded `"script.xml"` (FR-015) in `specs/008-cuems-utils-migration/upstream-reports/NOTE-012-script-filename.md` for cuems-utils feature 012: cuems-editor reads `script_file_name` from configuration; a re-mint procedure that hardcodes the name skips a library silently. No code change
- [ ] T047 Record the F2a interaction (FR-023) in `specs/008-cuems-utils-migration/handoff-relations-release-order.md` §notes: `cf5c4ad`'s socket-existence probe reports nodeconf available before it can serve an adopt; fix belongs to nodeconf (readiness flag at end of `read_network_map`); this feature added no caller of the probe
- [ ] T048 Full suite into `$E/final-suite.txt`; write the before/after table (baseline 28 F / 7 E / 720 P) with every retirement from `$E/test-retirements.md` accounted for (SC-006)
- [ ] T049 Run every command in `quickstart.md` §2 (SC-001…SC-011) and record pass/fail per criterion in `$E/exit-criteria.md`; SC-001's exempt set by name with reason "not shipped": `dev/network_map.xml`, `dev/CuemsEngine_old.py`
- [ ] T050 Complete `$E/not-performed.md`: SC-007 on a rig (load + GO of v1 and v2 from the editor), US3/US4 packaging and cluster items, the re-lock — each performed with output or listed with its reason. Silence is not a third state (SC-009)
- [ ] T051 Run `/speckit.analyze` (read-only) and resolve any CRITICAL finding. `xml-refactor-merge-candidate` is then cut — signed, annotated — on the T037 rc3-bump commit, but only once every consumer flow has landed (D27); cutting it is out of this task list

---

## Dependencies & execution order

```
Phase 1 (T001–T003) ─► Phase 2 (T004–T007) ─┬─► US1 (T008–T022) ─┐
                                            ├─► US2 (T023–T031) ─┼─► Phase 8 (T044–T051)
                                            ├─► US3 (T032–T035) ─┤
                                            ├─► US4 (T036–T039) ─┤
                                            └─► US5 (T040–T043) ─┘
```

- **Phase 2 blocks everything**: its attribution is what lets later red tests be read as intended.
- **US1 and US2 both edit `src/cuemsengine/core/BaseEngine.py`** (T016/T017 vs T028) — run them in sequence, or merge carefully; `tests/test_public_surface.py` goes fully green only after both.
- **US3 T032 makes CI red** — land it after US1/US2 are green locally, so a CI signal exists for as long as possible.
- **US5 is independent** of US1/US2 in code (different file), but T041's comment relies on T033's floor.
- **T037 (rc3 bump) runs after US1, US2, US3 and US5 are green** — it is the last source change and the tag's coordination point. T038/T039 can run any time.
- Within a story: tests → capture red → implementation → capture green. Never skip the capture.

## Parallel opportunities

- Phase 1: T003 alongside T001/T002.
- Phase 2: T007 alongside T004–T006.
- US1: T010, T011, T012, T013 (four different test files) together, after T008/T009.
- US2: T025 and T026 together after T024.
- US3: T032 ∥ T033. US4: T036 early (it is green on rc2), T038 ∥ T039 at any time, T037 last (ordering rule above). Polish: T044 ∥ T045 ∥ T046.
- US3, US4 and US5 can run in parallel with each other once Phase 2 is done.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + US1.** It removes the live `cluster_status` crash, fixes controller
lookup on converted maps, and deletes the mutating-API machinery — the part upstream US10 is
waiting on. **Then US2** (P1 too, and it fixes the engine's inability to load version-1 shows —
arguably the more urgent live defect; if a rig needs shows before the cluster work, swap the
order, since the two share only `BaseEngine.py`). Then US5, US3, US4, polish.

Stop at any checkpoint and the tree is consistent: each story's capture file says what is green.
