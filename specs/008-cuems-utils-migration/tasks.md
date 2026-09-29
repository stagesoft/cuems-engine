# Tasks: Migrate onto cuemsutils' post-008 public API

**Input**: `specs/008-cuems-utils-migration/` — spec.md (re-analysed 2026-09-29), plan.md,
research.md (R1–R15), data-model.md, contracts/, quickstart.md
**Prerequisites**: plan.md, spec.md (both present). Branch `feat/xml-refactor` with `rc_1`
(`956a0f3`) merged at `27b27f5`; all coordinates below are **post-merge**.

**Tests**: MANDATORY. Constitution II (TDD, non-negotiable) and spec FR-003. Every test task that
precedes an implementation task MUST be run and seen **red for its stated reason** before the
implementation task starts, with the run captured under `evidence/`.

**Standing rules for every task** (do not repeat per task):
- Run from the repo root with `export SPECIFY_FEATURE=008-cuems-utils-migration` and
  `E=specs/008-cuems-utils-migration/evidence`.
- **Never** run `poetry install` or `poetry lock` (FR-017a): the lock pins rc14 and would replace
  the editable `../cuems-utils`. Use `poetry run pytest -q -p no:cacheprovider …`.
- **Never** edit `../cuems-utils` (FR-022). Defects go into `upstream-reports/`.
- Tests feed **typed maps loaded through the public surface** (`tests/network_map_helpers.py`,
  T003). Never stub the adoption reader, and never assert how the library decodes a node — that is a
  node-model test and a regression here (FR-004, FR-030a-i).
- **Ids** (Group 7): every id entering engine code goes through `as_id`, every id leaving it
  (sort key, slice, split/join, JSON, OSC, concatenation) through `id_str` —
  `src/cuemsengine/tools/ids.py` (T010, `contracts/ids.md`). Test uuid literals are uuid4 (T008).
- A red test must be red **for the value it targets**. Read the failure and confirm the reason
  before capturing it (00-runnable-flow.md §7).
- Lint every changed file locally (CI cannot, FR-017a): `poetry run black --check`, `isort --check`,
  `flake8` on `src/`.
- **G6**: every captured run records `git -C ../cuems-utils rev-parse HEAD` beside the suite
  output. If the library moved since the last capture, diff the failing test ids against
  `baseline-suite-postmerge.txt` (`comm`) and record the result before continuing.
- Every **new** file carries the SPDX header in the style of the existing `tests/*.py`.
- **Commit at each checkpoint** (one logical change, conventional-commit message), with that
  checkpoint's evidence files in the same commit. T043 + T044 (backfill + rc7 bump) are one commit —
  the tag is cut on it (constitution Workflow §5).
- Commits are GPG-signed; on a signing failure retry, never `--no-gpg-sign`.
- **No pull request** from this branch until the re-lock turns CI green (FR-017a, constitution
  Workflow §4).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US5 from spec.md; unlabelled phases are shared or cross-cutting

---

## Phase 1: Setup

- [X] T001 Create `specs/008-cuems-utils-migration/evidence/README.md` indexing every evidence file this feature produces (baseline-suite.txt = pre-merge record; **baseline-suite-postmerge.txt = the comparison baseline**, 28 F / 7 E / 831 P; step1-*, step2-*, failing-first-*, us*-green.txt, identity-*, test-retirements.md, not-performed.md, ci-red-by-construction.md, final-suite.txt), and create `evidence/test-retirements.md` and `evidence/not-performed.md` with a header and an empty table (item, reason, date)
- [X] T002 FR-001: record the environment check from quickstart.md §0 in `evidence/step0-environment.md`: `cuemsutils.__version__ == "0.1.0rc16"` from `/disk/Projects/StageLab/cuems-utils/`, `cuemsengine` from this checkout's `src/`, `git rev-parse HEAD` a descendant of `27b27f5`, and `git -C ../cuems-utils rev-parse HEAD` (last verified `996617f`, same 35 failing ids as the baseline). If any differs, STOP — or, for a library move, apply G6 first
- [X] T003 [P] Create `tests/network_map_helpers.py` with `typed_network_map(tmp_path, nodes)`: writes a current-vocabulary `network_map.xml` (namespace and root exactly as `dev/test_xml_files/network_map.xml`; per node `<uuid>`, `<mac>`, `<name>`, `<node_role>`, `<ip>`, `<adopted>`, `<online>` in that order) and the minimal `settings.xml` the loader needs to find its own node (copy `dev/test_xml_files/settings.xml`, substituting the first node's uuid), loads with `ConfigManager(config_dir=str(tmp_path), load_all=False).load_network_map()`, returns `cm.network_map`. No assertions about decoded types here

---

## Phase 2: Foundational — fixtures, test ids, the surface guard, the id helpers

**Purpose**: FR-002 and Group 7's base. **Blocks every user story.**

- [X] T004 FR-002 step 1: `poetry run python ../cuems-common/usr/bin/cuems-migrate-network-map dev/test_xml_files/network_map.xml` (positional path, in place); confirm with `grep node_role` both nodes read `controller`/`node`; run the full suite into `$E/step1-network-map-converted.txt` (invocation + output at the top)
- [X] T005 Write `$E/step1-attribution.md`: every failure/error from T004 attributed to exactly one of (a) FR-003 sites 1–2 — `No controller node found in network map` on a map that has one; (b) FR-007/M9 — version-1 `script.xml` rejected by `XmlReaderWriter` (*character data between child elements*); (c) the `settings.xml` fixture (T006); (d) M12/M16 — `TypeError: '<' not supported between instances of 'Uuid'…` from a `sorted()` over map uuids (now reachable because the map loads). Anything else: STOP and report
- [X] T006 FR-002 step 2: `poetry run python -m cuemsutils.xml.convert_documents dev/test_xml_files/settings.xml`; confirm `doc_version="2"`, `<audio_cards>`/`<universes>` gone; run the suite into `$E/step2-settings-converted.txt`; append attribution. Gate: only (a), (b), (d) remain
- [X] T007 [P] Write `tests/test_public_surface.py` per `contracts/public-surface.md`: scan `src/cuemsengine/**/*.py` for imports from `cuemsutils.xml`/`cuemsutils.config` (all three spellings), for `cuemsutils.tools.Uuid` imported anywhere but `src/cuemsengine/tools/ids.py`, and for `get_nodes_by_adoption`, `partition_by_adoption`, `_adopted_uuids_from_network_map`, `find_hosts`, `CONTROLLER_NETWORK_FLAG`, `NodeType.`; anti-vacuity guard (zero files or zero `cuemsutils` imports → fail). Expect red naming `BaseEngine.py:17`, `ControllerEngine.py:15` and the symbols; capture `$E/failing-first-public-surface.txt`
- [X] T008 [P] FR-028: replace every non-uuid4 uuid literal in `tests/` and in the `dev/test_xml_files/` fixtures the suite loads with a fixed uuid4 — **6** today, all in `tests/`: `test_controller_gating.py` ×3 incl. `CONTROLLER_UUID = "aaaaaaaa-099f-11f0-a075-00e04c01b7e3"`, `test_controller_commands.py`, `test_node_comms_mixer.py`, `test_node_comms_ping.py` ×2 (re-run the **full** scan — every 36-char token, not only quoted ones; 40 distinct, 15 non-uuid4 on 2026-09-29). Do **not** edit the unloaded fixtures (`test_jsons.txt`, `sample_audiocue.xml`, `sample_cue.xml`, `sample_cuelist.xml`, `sample_dmxcue.xml`, `sample_videocue.xml`, `script_one_cue_in_a_cuelist.xml`, `script_one_simple_cue.xml`) — record them in `$E/identity-test-literals.txt` as out of scope, reason "not loaded by any test or by `src/`". Keep a readable prefix where tests rely on one (e.g. `aaaaaaaa-…-4…-8…`). Run the suite: the failing set MUST equal T006's exactly (`comm` of the two summaries); capture `$E/identity-test-literals.txt` with old → new per literal
- [X] T009 [P] Create `tests/test_ids.py` pinning `contracts/ids.md`: `as_id` passes a `Uuid` through, turns a uuid4 `str` into a `Uuid`, keeps a uuid1 and the nil uuid as `str` (type asserted), maps `""`/`None` to `None`, never raises, is idempotent; `as_id(u)` and `as_id(str(u))` are one set member; `sorted(mixed, key=id_str)` never raises; `id_str(None) == ""`. Assert the helpers only — never `Uuid` itself. Expect red (`ModuleNotFoundError: cuemsengine.tools.ids`); capture `$E/failing-first-ids.txt`
- [X] T010 FR-029: create `src/cuemsengine/tools/ids.py` with `as_id` and `id_str` per `contracts/ids.md` (no other public helper — a function with no production caller is a dead code path, constitution IV); the only `src/` import of `cuemsutils.tools.Uuid.Uuid`. Module docstring: mirrors the library's lenient uuid decoder (internal — cite it as "the library's uuid decoder", not by module path, so T007's guard stays meaningful) until a public helper exists (UR-6). T009 green

**Checkpoint (commit)**: fixtures current; test ids uuid4; helpers in place; suite red only for (a), (b), (d) and T007.

---

## Phase 3: User Story 1 — A controller on the new library finds itself and its nodes (P1) 🎯 MVP

**Goal**: controller-IP fallback, OSC registration, the GO gate's sets and `cluster_status` correct on a typed map, with `Uuid`/`str` ids mixed as the library delivers them (FR-003, FR-005, FR-005a, FR-006, FR-009, FR-009a, FR-010, FR-010a, FR-011, FR-024–FR-026 for `ControllerEngine`).

**Independent test**: `poetry run pytest tests/test_core_baseengine_controller_ip.py tests/test_cluster_status_contract.py tests/test_cluster_identity.py tests/test_controller_gating.py tests/test_cluster_warning.py tests/test_nodelist_modify.py` green.

### Tests — write first, see red, capture

- [X] T011 [US1] `tests/test_core_baseengine_controller_ip.py`: replace `_master`/`_slave` (`:33-38`) and the `:101` fixture with typed maps (T003); keep every case; add "no controller" with `node_role=node` entries only (`contracts/controller-lookup.md` — never a pre-007 map). Against unchanged `src/`: positive cases red with `No controller node found in network map`; capture `$E/failing-first-site1-2-controller-lookup.txt`
- [X] T012 [US1] Same file, FR-005a: two `controller` nodes → first `ip` returned, exactly one ERROR record listing both `uuid=… ip=…` (`caplog`, or patch `Logger.error` if the engine logger does not propagate). Red; capture `$E/failing-first-fr005a-multiple-controllers.txt`
- [X] T013 [P] [US1] Create `tests/test_cluster_status_contract.py` per `contracts/cluster-payloads.md`: controller built as in `tests/test_controller_gating.py`'s `controller` fixture, own uuid a `str`, `cm.network_map` a typed map (controller + two adopted + one unadopted, uuid4 → `Uuid`), stub only `_probe_cluster_liveness`; assert keys exactly `alive`/`adopted`/`controller`, lists sorted and all `str`, `adopted` = the adopted uuids. Red with `TypeError … 'Uuid'`; capture `$E/failing-first-fr009a-cluster-status.txt`
- [X] T014 [P] [US1] Create `tests/test_cluster_identity.py` (FR-026): controller own uuid `str`, map uuids `Uuid`, pong senders arriving as `str` (drive the NNG status path that fills `_pong_responses` at `ControllerEngine.py:551`, and `_finished_nodes`/`_armed_nodes` at `:568`/`:588`), project nodes from `output_name[:36]` (`:987`); assert `_resolve_cluster_state` (`:1561`) yields the right `required`/`missing`/`unreachable`, the controller in neither list, every set holding one member per node. **G5 case**: one project `output_name` prefixed with a uuid4 absent from the map (a stale pre-re-mint identity) → that uuid, as `str`, in `missing`. Red (pre-change: `sorted(adopted)` at `:1588` raises); capture `$E/failing-first-fr026-cluster-identity.txt`
- [X] T015 [P] [US1] Rewrite `tests/test_controller_gating.py:285-298` (`test_adopted_uuids_reader_handles_python_bool`) as FR-009's test: typed map of N adopted nodes → `_register_node_osc_handlers()` registers one route per adopted node plus the controller's own, each `f"/{id_str(u)}/*"`, none with `None`; map field-for-field equal before/after (`copy.deepcopy`). Delete the string-form `adopted: "True"` case; record the retirement (reason: decoding `adopted` belongs to cuemsutils, FR-030a-i; clarify Q4) in `$E/test-retirements.md`
- [X] T016 [P] [US1] `tests/test_cluster_warning.py:81` and `:337`: replace `patch.object(controller, "_adopted_uuids_from_network_map", …)` with a typed map carrying the same adopted set; keep every assertion; assert `missing`/`unreachable` contain only `str`
- [X] T017 [P] [US1] `tests/test_nodelist_modify.py:410` and `:484`: same replacement; keep every assertion
- [X] T018 [US1] Add temporary `tests/test_find_hosts_characterization.py`: `BaseEngine.find_hosts()` on a valid typed map with one adopted online controller; record exactly what it raises (M8 predicts `AttributeError` from `self.cm.network_map.get_nodes_by_adoption`; F1 the wrapper bug behind it); capture `$E/failing-first-site3-4-find-hosts.txt` stating which held
- [X] T019 [US1] Run T016 and T017 against unchanged `src/`: record whether they are green (characterization) or red on M12's `TypeError`; if red, name the `sorted()` site in `$E/us1-moved-tests-pre.txt` — they then serve as extra failing-first evidence for T026

### Implementation

- [X] T020 [US1] `src/cuemsengine/core/BaseEngine.py`: import `NodeIndex, NodeRole` from `cuemsutils.tools.NodeList` and `as_id, id_str` from `..tools.ids`; rewrite `_controller_ip_from_map` (`:401-415`) on `NodeIndex.from_nodes([...unwrapped nodes...], key=lambda n: id_str(n["uuid"]))`, `.controllers`, unchanged `ValueError`s, `len > 1` → one `Logger.error` listing every `uuid=… ip=…` then the first; docstrings `:354`, `:402` → `node_role=controller`. T011, T012 green
- [X] T021 [US1] Delete `find_hosts` (`BaseEngine.py:417-449`), then `CONTROLLER_NETWORK_FLAG` (`:33`) — that order, so flake8 never sees an undefined name. Grep `src/` and `tests/` for both: zero hits outside `tests/test_public_surface.py`'s ban list
- [X] T022 [US1] Delete `tests/test_find_hosts_characterization.py`; record the retirement (evidence in T018, method deleted per clarify Q2)
- [X] T023 [US1] `src/cuemsengine/ControllerEngine.py`: add `_adopted_node_uuids(self) -> frozenset` beside `_node_label` (`:1468`): unwrap `entry["node"]` once (M10 — do NOT drop it), include `as_id(node["uuid"])` when `node.get("adopted") is True`, no string parsing; on exception `Logger.warning` with context, return `frozenset()`. Docstring cites "UR-1"/"UR-4" only — never the internal symbol or path T007 bans
- [X] T024 [US1] `_register_node_osc_handlers` (`:259-298`): own uuid via `as_id(self.cm.node_conf.get("uuid", ""))` (`:281`), replace the `get_nodes_by_adoption` block (`:285-293`) with `node_uuids |= self._adopted_node_uuids()`, routes `f"/{id_str(u)}/*"`; replace the `⚠ … mutates` paragraph (`:272-277`) with one line (reads only; safe to repeat); delete `from cuemsutils.xml.Settings import NetworkMap` (`:15`) (FR-008). T015 green
- [X] T025 [US1] Point `:1515`, `:1579`, `:1764` at `_adopted_node_uuids()`; delete `_adopted_uuids_from_network_map` (`:1444-1466`); in `_reload_network_map` (`:928-943`) replace the `ORDER MATTERS` paragraph with a note that re-registration after reload is not order-sensitive (no deleted names)
- [X] T026 [US1] Group 7 in the controller's cluster paths: `as_id` at ingress — `operation.sender` (`:551`, `:568`, `:588`), `output_name[:36]` in `_collect_project_nodes` (`:987`), own uuid in `_controller_uuid` (`:1441`) and `:167`, `:350`, `:385`, `:1422`, map uuids in `_node_label` (`:1458`, `:1483`); `id_str` at egress — every `sorted(...)` over ids with `key=id_str` and emitted as `[id_str(u) for u in …]` where the value leaves the process (`:1557`, `:1588`, `:1626-1627`, `:1654-1655`, `:1703`, `:1766-1767`), `_node_label`'s `uuid[:8]` (`:1488`), `get_cluster_status`'s `controller`. T013, T014, T016, T017 green
- [X] T027 [US1] Run the US1 independent test and `tests/test_public_surface.py` (still red only for `BaseEngine.py:17`, removed in US2); lint; capture `$E/us1-green.txt`

**Checkpoint (commit)**: FR-030a-ii sites 1–4 discharged; controller ids consistent.

---

## Phase 4: User Story 2 — Shows load and play across the script version change (P1)

**Goal**: FR-007, FR-016–016c, SC-007, SC-010.

**Independent test**: `poetry run pytest tests/test_project_load.py tests/test_read_script.py tests/test_default_mappings_valid.py tests/test_media_duration.py tests/test_loop_rebase.py tests/test_effective_duration.py tests/test_chain_anchoring.py tests/test_reveal_mechanism.py tests/test_dispatch_reorder.py` green.

### Tests — write first, see red, capture

- [X] T028 [US2] `cp -r dev/test_xml_files/projects/complex_test dev/test_xml_files/projects/complex_test_v2`; `poetry run python -m cuemsutils.xml.convert_documents dev/test_xml_files/projects/complex_test_v2/script.xml`; confirm `doc_version="2"`; record `$E/fixture-complex-test-v2.txt`. v1 original untouched
- [X] T029 [US2] Parametrize `test_complex_project_load_on_controller` (`tests/test_project_load.py`) over `complex_test` and `complex_test_v2`. Against unchanged `src/`: **v1 red** at `read_script` (*character data between child elements*), **v2 green** (the deprecated reader loads v2 — measured); capture `$E/failing-first-fr007-script-load.txt`
- [X] T030 [P] [US2] Create `tests/test_read_script.py`: v1 file bytes unchanged after `read_script` (hash); a `complex_test_v2` copy with `doc_version="3"` raises the library's error containing `newer than this library's current version`; a missing file keeps raising `FileNotFoundError`. `tmp_path` libraries. Capture red `$E/failing-first-fr007-read-script.txt`
- [X] T031 [P] [US2] Move `tests/test_default_mappings_valid.py` off `XmlReaderWriter` (SC-010): script fixtures (`complex_test` v1, `complex_test_v2`) via `CuemsScript.load(path).validate()` falsy; config fixtures through the public `ConfigManager` loaders BaseEngine uses — `settings.xml`/`network_map.xml` via `load_network_map` on a config dir, `default_mappings.xml` via `load_net_and_node_mappings`, `project_settings.xml`/`project_mappings.xml` via `load_project_settings`/`load_project_mappings` on a `tmp_path` project (files named `settings.xml`/`mappings.xml`, the `CuemsDeploy.py:647-652` layout). `CuemsScript.validate` validates only a loaded script (measured) — UR-5. Before/after with `-W error::DeprecationWarning` on this file: before raises, after clean; capture `$E/us2-default-mappings-deprecation.txt`
- [X] T032 [P] [US2] Create `tests/test_media_duration.py` characterization (FR-016a), green **before** any wrap is touched: `run_audioCue` and `run_videoCue` (`src/cuemsengine/cues/run_cue.py`) — `cue._end_mtc == cue._start_mtc + d.return_in_other_framerate(mtc.main_tc.framerate)` for `00:00:12.500` and `00:01:00.000` at 25 and 30 fps (mock players/OSC as `tests/test_reveal_mechanism.py` does for `run_audioCue`; `run_videoCue` has **no existing coverage** — build its harness); `_effective_duration_ms` body = `milliseconds_exact`; `loop_audioCue`/`loop_videoCue` via `tests/test_loop_rebase.py`, adding a conversion assertion only if absent. Capture green `$E/us2-duration-characterization-pre.txt`
- [X] T033 [US2] Same file, FR-016b: `media.duration is None` (M13: `<duration/>` in a v2 document via `CuemsScript.load`, or set directly) through all five paths — no exception, zero, one WARNING naming the cue (`id_str(cue.id)`). Red (silent zero); capture `$E/failing-first-fr016b-none-duration.txt`

### Implementation

- [X] T034 [US2] `BaseEngine.py:503-510` `read_script`: `CuemsScript.load(xml_file)` (imported at `:12`) replaces `XmlReaderWriter(...).read_to_objects()`; keep the `FileNotFoundError` check and the hardcoded `"script.xml"` (FR-015); delete `from cuemsutils.xml import XmlReaderWriter` (`:17`) (FR-008). T029, T030, `tests/test_public_surface.py` green — SC-003
- [X] T035 [US2] Add the duration helper beside its callers in `src/cuemsengine/cues/` (a function in an existing module shared by `run_cue.py`, `loop_cue.py`, `CueHandler.py`): the `CTimecode` as delivered, or for `None` one `Logger.warning` naming `id_str(cue.id)` and `CTimecode()` zero; one-line WHY comment (empty `<duration/>` is schema-valid, M13)
- [X] T036 [US2] Replace the five wraps with the helper: `run_cue.py:176`, `:430`; `loop_cue.py:112`, `:276`; `CueHandler.py:212` (keep each site's `.return_in_other_framerate(...)`/`.milliseconds_exact` and `CueHandler`'s `if cue.media else 0`). `grep -rn 'CTimecode(cue.media.duration)' src/` → zero (SC-011). T032 stays green, T033 green
- [X] T037 [US2] Run the US2 independent test; lint; capture `$E/us2-green.txt` — FR-016c: every timing test green before T036 is green after (incl. `rc_1`'s `test_dispatch_reorder.py`, `test_chain_epoch.py`)

**Checkpoint (commit)**: v1/v2 shows load; durations unchanged; empty durations logged; no `cuemsutils` deprecation in the suite.

---

## Phase 5: User Story 3 — The release gate refuses a mismatched library (P2)

**Goal**: FR-017, FR-017a, FR-018 per `contracts/package-relations.md`.

**Independent test**: `sed -n 48p pyproject.toml`; `grep -n 'cuems-utils\|cuems-common' debian/control` match the contract.

- [ ] T038 [P] [US3] `pyproject.toml:48` `>=0.1.0rc13` → `cuemsutils = ">=0.1.0rc16,<0.1.1"`. Do **not** run `poetry lock`
- [ ] T039 [P] [US3] `debian/control:18` `cuems-utils (>= 0.1.0rc4)` → `cuems-utils (>= 0.1.0rc16),` + `cuems-utils (<< 0.1.1~),`; `:19` → `cuems-common (>= 1.3.0-23~),`; comment block above `Depends:` in the style of `../cuems-common/debian/control:51-56` (C7 gate; inherited `Breaks: cuems-nodeconf (<< 0.1.0-8)` because the engine reads `node_role`; no `Breaks:` of the engine's own). Do not touch `debian/changelog`
- [ ] T040 [US3] Write `$E/ci-red-by-construction.md`: CI's `poetry install --with dev` (`.github/workflows/ci.yml`) resolves the tracked lock at rc14, which lacks `NodeRole`, `CuemsScript.load` and the versioned schemas (measured) — red from Phase 2 onward, and `poetry install` refuses the stale lock after T038; rc16 unpublished (PyPI latest rc14, checked 2026-09-28); the one step that clears it is `poetry lock` once rc16 is on PyPI; **no PR from this branch until then** (FR-017a, Workflow §4)
- [ ] T041 [US3] Record in `$E/not-performed.md` unless a packaging sandbox exists (then perform and capture): `dpkg` refusal against `cuems-utils` 0.1.1 and against `cuems-nodeconf` < 0.1.0-8 via the `cuems-common` floor; the re-lock (SC-005) — reason: rc16 unpublished

---

## Phase 6: User Story 4 — Nodes upgrade before the controller; rc7 (P2)

**Goal**: FR-019, FR-019a, FR-019b, FR-019c, FR-019d, FR-020, FR-023a.

**Independent test**: `poetry run pytest tests/test_version_single_source.py` green; quickstart SC-008 row.

- [ ] T042 [P] [US4] Create `tests/test_version_single_source.py` (FR-019b): `cuemsengine.__version__` is the source; assert `pyproject.toml`'s `[tool.poetry] version` (`tomllib`) and the first `## v<version>` header of `CHANGELOG.md` equal it; messages name the stale file and the fix. Anti-vacuity: fail if the `CHANGELOG.md` header cannot be parsed. **Do not read `debian/changelog`** (FR-019a). Run now: green (all `0.1.0rc2`); capture `$E/us4-version-drift-pre.txt`
- [ ] T043 [US4] **CHANGELOG backfill (FR-019c)** — insert `v0.1.0rc6` … `v0.1.0rc3` entries directly above `## v0.1.0rc2 — 2026-05-19` (`CHANGELOG.md:3`), newest first, per `contracts/package-relations.md` §backfill: rc6 — 2026-09-28 from `git log --no-merges fc8d2bb..956a0f3` (31) and `git show 7f6e475:debian/changelog` `0.1.0rc6-1`; rc5 — 2026-08-14 from `2abf26d..fc8d2bb` (5) and `0.1.0rc5-1`; rc4 — 2026-08-03 from `v0.1.0rc2..2abf26d` (100) and `0.1.0rc4-1`; rc3 — 2026-04-16 from the `0.1.0rc3-1`/`-2` entries (lines 105–132 of that file) and the first-parent packaging commits up to `30af517`, plus one line: *cut from the packaging line before the `v0.1.0rc2` tag (2026-05-19)*. Style of the rc2 entry (summary paragraph; `### Added`/`### Changed`/`### Fixed` with `####` topic groups; ClickUp ids kept). Derive every claim from the commits or those entries — write nothing not traceable to one; list the source range under each header as an HTML comment. Leave rc2 untouched. The drift test goes red here (top header `rc6` vs `__version__` `rc2`) until T044 — the two land in **one commit**
- [ ] T044 [US4] **rc7 bump**, the last source change. Set `__version__ = "0.1.0rc7"` in `src/cuemsengine/__init__.py:5`; run T042's test and capture it **red** naming the stale copies (`$E/failing-first-fr019b-version-drift.txt`); then `pyproject.toml:11` `version = "0.1.0rc7"`, and insert `## v0.1.0rc7 — UNRELEASED` above rc6 per `contracts/package-relations.md` §rc7: summary; `### Added`/`### Changed`/`### Removed` for Groups 1–7 — `### Changed` MUST state FR-014's `fade_out` → `stop` behaviour change (a converted `fade_out` now disarms) and the identity policy; `### Upgrade notes`: upgrade every node before the controller; why (show-load deploy of v2 `script.xml`, no package manager mediates it); `script.xml` 2, `mappings.xml` 1, `settings.xml` 1; the new `Depends:` bounds; **G1 (FR-019d)**: rc7 engines and `cuems-utils` 012's node re-mint go out in the same upgrade — never run the re-mint under a pre-rc7 engine. **Do not touch `debian/changelog`**, no `debian/NEWS`. T042 green. Commit T043 + T044 together — `xml-refactor-merge-candidate` is cut on this commit
- [ ] T045 [P] [US4] Write `specs/008-cuems-utils-migration/handoff-relations-release-order.md`: draft release-procedure section for `../cuems-relations` (the three upgrade-note items; a future `project_mappings`/`project_settings` bump extends C11; **G1**: the 012 re-mint ships in the same upgrade as rc7 engines, never under older ones), and the FR-023a note on `Plans/phase2-engine-late-binding.md:198-204` (R3's guard never ran; >1 controller now logged, not refused). Header: *draft for hand-off, not committed to cuems-relations from this feature*
- [ ] T046 [US4] Record US4 scenario 2 (old-library node + new-library controller, deploy and load) in `$E/not-performed.md` unless a two-host rig is available — then perform and capture

---

## Phase 7: User Story 5 — Dead and deceptive code is removed (P3)

**Goal**: FR-012–FR-014 (fade handlers), with FR-014's corrected statement. `find_hosts` and the adoption workaround went in US1.

**Independent test**: `grep -n 'fade_in\|fade_out' src/cuemsengine/cues/ActionHandler.py` → only T049's comment; SC-004 grep empty (excluding `tests/test_public_surface.py`).

- [ ] T047 [US5] `tests/test_action_cue.py`: an in-memory `ActionCue` with `action_type="fade_in"` yields `failed`, reason `Unsupported action_type: 'fade_in'` (`ActionHandler.py:247`). Red now (handler returns `applied`); capture `$E/failing-first-fr012-fade-unsupported.txt`
- [ ] T048 [US5] Characterize FR-014 **before** T049 (requires T034): copy `../cuems-utils/tests/data/corpus/pre-008/fade_actions.xml` to `dev/test_xml_files/projects/fade_actions_v1/script.xml`, recording `git -C ../cuems-utils rev-parse HEAD` in `$E/fixture-fade-actions-v1.txt` (its uuids are already uuid4 — `b1c2d3e4-0000-4aaa-8aaa-…`, measured — so no conversion); test in `tests/test_action_cue.py`: load via `read_script`; every former `fade_in` reaches dispatch as `play` (`applied`); every former `fade_out` as `stop` — and asserts `stop`'s semantics: `ch.disarm(target)` called, a repeat gives `applied_no_change` (M17: the behaviour **change** from the old `fade_out`). Green before T049 and after T050; capture both to `$E/us5-fade-conversion-characterization.txt`
- [ ] T049 [US5] Delete from `src/cuemsengine/cues/ActionHandler.py`: `"fade_in"`, `"fade_out"` in `SUPPORTED_CUE_ACTIONS` (`:38-39`), `_handle_fade_in` (`:541-564`), `_handle_fade_out` (`:567-583`), their `_ACTION_HANDLERS` entries (`:810-811`). One comment where they were, stating corrected FR-014: convert-on-read rewrites them to `play`/`stop` before the engine sees a document; `fade_in` ≡ `play`; `fade_out` → `stop` now disarms (fixes the zombie-process bug); the `cuems-utils (>= 0.1.0rc16)` floor guarantees the conversion. **Requires T039** (floor committed first, FR-013)
- [ ] T050 [US5] Delete `TestFadeInAction` and `TestFadeOutAction` (`tests/test_action_cue.py`, the `# T011`/`# T012` blocks from `:255`); record each retired test id in `$E/test-retirements.md` (handler deleted; behaviour delivered by the library's conversion — preserved for `fade_in`, changed for `fade_out`, FR-014). T047 green
- [ ] T051 [US5] Run `tests/test_action_cue.py` and the SC-004 grep (`get_nodes_by_adoption|_adopted_uuids_from_network_map|find_hosts` over `src/ tests/`, excluding `tests/test_public_surface.py`) → zero; lint; capture `$E/us5-green.txt`

---

## Phase 8: Identity sweep — Group 7 beyond the controller's cluster paths (cross-cutting)

**Purpose**: FR-024, FR-025, FR-027, SC-012 for the sites US1 does not own.

- [ ] T052 [P] Characterization, green before T054, in `tests/test_identity_sweep.py`: `BaseEngine`'s `node_name` (`:325`) from a uuid4 own uuid equals the uuid string (`node_host` is not characterized — it is deleted in T054, M21); `NodeEngine`'s own-uuid use (`:632`); the direct-player OSC route (`ControllerEngine.py:301-310`) with a `str` uuid address; editor cue ids at `:472` and `:609` matched against `Uuid` cue ids. Capture `$E/identity-sweep-pre.txt`
- [ ] T053 [P] FR-027 (G2), same file: a config dir whose `settings.xml` own uuid is the NOT PROVISIONED sentinel (`cuemsutils.tools.identity_check.SENTINEL`, the nil uuid — FR-028's named exception) → engine config setup logs exactly one ERROR containing `NOT PROVISIONED` and `cuems-init-node` and exits (`SystemExit`) **before** `ConfigManager(load_all=True)` is constructed (assert via a spy). Red (today: the generic *"Exception while loading config: Node with uuid 00000000-… not found"*); capture `$E/failing-first-fr027-sentinel.txt`
- [ ] T054 In `BaseEngine.set_config_manager` (`:311-327`): delete `self.node_host` (`:64` initialisation and `:315`; never read in `src/` or the sibling repos — grep proves it; M21), and retire the one test that pins it, `tests/test_core_baseengine.py:30` (`assert engine.node_host == …`), recording it in `$E/test-retirements.md` (attribute deleted; its MAC-from-uuid1 meaning ends with 012); before `ConfigManager(load_all=True)`, read `ConfigManager(load_all=False).node_uuid` and, if it equals `SENTINEL`, log the FR-027 ERROR and `exit(-1)`; `:325` `node_name` via `id_str(as_id(...))`. Apply `as_id`/`id_str` at `NodeEngine.py:632`, `ControllerEngine.py:310`, `:472`, `:609`. Import `SENTINEL` from `cuemsutils.tools.identity_check` (public-surface guard updated in the same commit; UR-8 asks upstream to confirm it as public). T052 stays green, T053 green
- [ ] T055 Identity audit (SC-012): re-run research R14's scans over `src/` (`sorted(`/`min(`/`max(` over ids, `[:36]`/`[:8]`/`[-12:]`, `.split("-")`, `.join(` over ids, `isinstance(…, str)` on ids, `json.dumps` of id-carrying payloads, OSC args with ids); every hit passes through `as_id`/`id_str` or is listed as safe with the reason (e.g. `PlayerHandler.py:223/:270/:342` and `AudioPlayer.py:31` split keys populated with `str(cue.id)` at `:486`; `CueHandler.py:686`, `rc_1` `6068dd8`). **Name explicitly**: `NodeEngine.py:443` sends `self.cm.node_uuid` as gradient-motiond's OSC `node_name` (`arg_type="s"`, `GradientClient.py:51`) — `str` today, but wrap it in `id_str` so a library that types the settings uuid (UR-8's ask) cannot put a `Uuid` on the wire. Write `$E/identity-audit.md`
- [ ] T056 Run `tests/test_ids.py tests/test_identity_sweep.py tests/test_cluster_identity.py` and the full suite; lint; capture `$E/identity-green.txt`

**Checkpoint (commit)**: SC-012.

---

## Phase 9: Polish & cross-cutting

- [ ] T057 [P] `CLAUDE.md`: rewrite the field note *"A successful adoption re-reads network_map.xml in place … ⚠ Order is load-bearing: `get_nodes_by_adoption()` mutates…"* — the hazard is gone (`_adopted_node_uuids` only reads); keep the partial-success paragraph. Add one field note on ids: `Uuid` canonical as the library delivers it (uuid4 → `Uuid`, else `str`); `as_id` at ingress, `id_str` at egress; never `sorted()`/slice/split a raw id
- [ ] T058 [P] Upstream reports in `specs/008-cuems-utils-migration/upstream-reports/`: `UR-1-no-public-adoption-partition.md`, `UR-2-versioning-comment-stale.md`, `UR-4-uuid-unorderable.md`, `UR-5-validate-deprecation-advice.md`, `UR-6-no-public-id-coercion.md`, `UR-7-fade-out-conversion-not-behaviour-preserving.md`, and **UR-8** = the already-drafted `PROMPT-012-clarify.md` (verify it still matches `cuems-utils`' 012 state before handing it over) — each: observed, reproduction (research probe), expected, impact here, workaround taken. UR-3 (stale `0.1.0rc12` dist metadata): check whether `pip install -e ../cuems-utils` fixes it first; if so record as environmental in `$E/not-performed.md`, do not file
- [ ] T059 [P] `specs/008-cuems-utils-migration/upstream-reports/NOTE-012-script-filename.md`: `BaseEngine.py:505`'s hardcoded `"script.xml"` vs cuems-editor's `script_file_name` (FR-015) — a trap for cuems-utils feature 012's re-mint. No code change
- [ ] T060 FR-023 note in `handoff-relations-release-order.md` §notes: `cf5c4ad`'s socket-existence probe reports nodeconf available before it can serve an adopt; the fix belongs to nodeconf; this feature added no caller of the probe
- [ ] T061 Full suite into `$E/final-suite.txt`; before/after table against `baseline-suite-postmerge.txt` (28 F / 7 E / 831 P) with every retirement accounted for (SC-006)
- [ ] T062 Run quickstart.md §2 (SC-001…SC-012); record pass/fail per criterion in `$E/exit-criteria.md`; SC-001's exempt set by name, reason "not shipped" (FR-021): `dev/network_map.xml`, `dev/CuemsEngine_old.py`; SC-002 = the `failing-first-*` files for sites 1–4 (T011, T018)
- [ ] T063 Complete `$E/not-performed.md`: SC-007 on a rig (load + GO of v1 and v2), US3/US4 packaging and cluster items, the re-lock — each performed with output or listed with its reason (SC-009)
- [ ] T064 Run `/speckit.analyze` and resolve any CRITICAL finding. `xml-refactor-merge-candidate` is then cut — signed, annotated — on the T043+T044 commit, once every consumer flow has landed (D27); cutting it is out of this list

---

## Dependencies & execution order

```
Phase 1 (T001–T003) ─► Phase 2 (T004–T010) ─┬─► US1 (T011–T027) ─┬─► Phase 8 identity sweep (T052–T056) ─┐
                                            ├─► US2 (T028–T037) ─┘                                      │
                                            ├─► US3 (T038–T041) ────────────────────────────────────────┼─► T043+T044 (rc7) ─► Phase 9 (T057–T064)
                                            ├─► US4 T042, T045, T046 (any time)                         │
                                            └─► US5 (T047–T051; needs T034, T039) ──────────────────────┘
```

- **Phase 2 blocks everything.** T008 (uuid4 test literals) precedes any typed-map test; T010 (helpers) precedes US1's implementation.
- **US1 and US2 both edit `BaseEngine.py`** (T020/T021 vs T034) — sequence them; `tests/test_public_surface.py` goes green only after both.
- **CI is red from Phase 2 onward** (the locked rc14 lacks the post-007 surface and rejects the `node_role` fixture) — T040 records it; the no-PR rule covers it.
- **T039 → T049 (FR-013, MUST)**: the floor commit lands before the fade-handler deletion. **T034 → T048**: the characterization loads a v1 script through `read_script`.
- **T043 + T044 run after US1, US2, US3, US5 and Phase 8 are green** and land as one commit — the tag's coordination point. T042, T045, T046 run any time after Phase 2.
- Within a story: tests → capture red → implementation → capture green. Never skip the capture.

## Parallel opportunities

- Phase 1: T003 with T001/T002. Phase 2: T007, T008, T009 together after T006.
- US1: T013–T017 together after T011/T012. US2: T030, T031, T032 together after T029.
- US3: T038 ∥ T039. US4: T042, T045, T046 any time. Phase 8: T052 ∥ T053. Polish: T057 ∥ T058 ∥ T059.
- After Phase 2, US3 and the free US4 tasks run alongside US1/US2; US5 after T034 and T039.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + US1** — it removes the live `cluster_status` crash and the
`Uuid`/`str` split in the cluster sets, fixes controller lookup on converted maps, and deletes the
mutating-API machinery upstream US10 waits on. **Then US2** (the engine cannot load a v1 show
today — swap the order if a rig needs shows first; they share only `BaseEngine.py`). Then US5, US3,
the identity sweep, and last the rc7 commit. Stop at any checkpoint and the tree is consistent.
