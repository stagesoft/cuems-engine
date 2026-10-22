<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tasks: Release-line reconciliation before 0.1.1-1

**Input**: `specs/009-release-line-reconciliation/`: spec.md (clarified 2026-10-17), plan.md,
research.md (R0–R10), data-model.md, contracts/ (C1–C5), quickstart.md. Work order (WO):
`specs/planning/release-line-reconciliation-0.1.1.md` @ `945ccba`, deleted by T118.
**Prerequisites**: branch `009-release-line-reconciliation` at `945ccba` (= `e994a5e` + the WO).

**Tests**: MANDATORY (constitution II, non-negotiable). A test task that precedes an implementation
task MUST be run and seen **red for its stated reason** before that implementation task starts. The
run is captured as `$E/failing-first-<id>.txt`.

**Standing rules for every task** (not repeated per task):
- Run from the repo root with:
  - `export SPECIFY_FEATURE=009-release-line-reconciliation PYENV_VERSION=3.11.9`
  - `E=specs/009-release-line-reconciliation/evidence`
  - `PY=.venv-016/bin/python`, which has cuemsutils 0.1.1 editable from `../cuems-utils`
  - pytest as `$PY -m pytest -q -p no:cacheprovider …`
- **Never** run `poetry install`, `poetry lock` or `poetry add` in the working tree, and never commit
  `poetry.lock` (spec FR-037). The in-job relock exists **only** inside CI (C1).
- **Never** edit a sibling repository (`../cuems-utils`, `../cuems-nodeconf`, …). Obligations go to
  `specs/009-release-line-reconciliation/upstream-reports/`. **Never** move or create a tag.
- **Merges**: always `--no-ff`. No `-X ours`/`-X theirs` and no cherry-pick (FR-001, FR-005).
- **Commits**: GPG-signed (`-S`). On "gpg failed to sign", retry, never `--no-gpg-sign`. Use
  conventional-commit messages, one logical change each, with the evidence files of that change in
  the same commit (FR-061).
- **G6**: every captured suite run records `git -C ../cuems-utils rev-parse HEAD` and
  `$PY -c 'import cuemsutils; print(cuemsutils.__version__)'` at its top.
- **libmtc stub** (T002): if `libmtcmaster.so.0` is absent, apply `$E/libmtc-stub.patch` before a
  run (`git apply`) and revert it (`git apply -R`) **before every commit**. It is never committed;
  `git diff --quiet src/cuemsengine/core/libmtc.py` must hold at commit time.
- **Ids**: every id entering engine code goes through `as_id`, and every id leaving it goes through
  `id_str` (`src/cuemsengine/tools/ids.py`). Test uuid literals are uuid4.
- **Paths**: until T101, tests live flat in `tests/` (support files move into `tests/support/` at
  T093). From T101 on, they live under `tests/{unit,integration,contract}/`; fixtures live in
  `tests/data/` from T097.
- Every **new** file carries the SPDX header in the style of the existing `tests/*.py`.
- Lint changed files: `$PY -m black --check`, `$PY -m isort --check`, and `$PY -m flake8` on `src/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1…US6 from spec.md. Setup, Foundational, Docs/verify and Polish carry no label.

---

## Phase 1: Setup

**Purpose**: a recorded, reproducible environment and a fresh measurement of the line.

- [X] T001 Write `specs/009-release-line-reconciliation/evidence/environment.md` with:
  - the Python version, the `.venv-016` path and Poetry `2.4.1`
  - `git -C ../cuems-utils rev-parse HEAD`, and the candidate tag commit (`4b336cd`) to show the drift
  - whether `libmtcmaster.so.0` is present (`ldconfig -p | grep libmtcmaster`)
  - whether `gh` is available
  - the null-keyring note (research R1)
- [X] T002 If `libmtcmaster.so.0` is absent, create `specs/009-release-line-reconciliation/evidence/libmtc-stub.patch`, which replaces the import-time raise in `src/cuemsengine/core/libmtc.py` with a `unittest.mock.MagicMock` (WO §6.1). Then verify that `git apply` and `git apply -R` round-trip cleanly. Record in `environment.md` that both arms use it.
- [X] T003 Re-measure the line per quickstart §1:
  - `git fetch --all --tags`
  - the behind-counts for `origin/debian/bookworm` and `origin/rc_1`
  - the ancestry of `35cbe78`, `d50ee4b`, `5a1811c` and `3c11c60` against `origin/rc_1`
  - their PR state, via `gh pr list --state all` if available, otherwise "unchecked: no gh"
  - any changelog header on bookworm, `rc_1` or a `v0.1.0*` tag that is newer than `0.1.0rc6-5`

  Write it all to `specs/009-release-line-reconciliation/evidence/remeasure-start.md`. **If the line
  moved** past spec M1/M7, append the new commits to the inventory table in `evidence/inventory-proofs.md`
  (T005) before Phase 3.

  **Two branches to settle here and record in `remeasure-start.md`:**
  - **#24 on `rc_1`**: if `5a1811c` or `3c11c60` is already an ancestor of `origin/rc_1`, FR-007's
    safety net fires at the start. T018 will absorb #24, T027 asserts that it **is** an ancestor,
    and the FR-016 adaptation (A-8: red tests B1–B3 of C5, then the conversion) is added as tasks
    right after T018. Otherwise #24 stays out and T027 asserts that it is not an ancestor.
  - **#22/#23 on `rc_1`**: if `35cbe78` or `d50ee4b` is already an ancestor of `origin/rc_1`, T018
    absorbs it. Its red test (T019/T021) is then shown red against the head's parent instead of HEAD
    (see those tasks), and T020/T022 have nothing left to merge.
- [X] T004 [P] Run the stray-head sweep (quickstart §1 loop over `refs/remotes/origin` and `refs/tags`) and write `specs/009-release-line-reconciliation/evidence/stray-head-sweep.md`. It has one row per ref with unabsorbed commits, and each row gets exactly one verdict (`data-model.md` "Stray head"):
  - #22 and #23: `merge-by-sha`
  - #24: `sequenced-after-nodeconf`, citing FR-007 and C5
  - `v0.1.0rc5-6`: `ancestry-only`
  - `integ/rc6-3-node-adoption` (`363b92a`), `gh-pages`, `archive/*`, `docker`, `nodeconf`, `server`, `engine-server`, `2ppo` and `osc_no_bool`: `excluded`, with a reason each (FR-009)
  - `origin/release/0.1.0rc6-*` and `origin/feat/stop-project-actioncue`: verify that each is an ancestor of bookworm, and record that
- [X] T005 [P] Create `specs/009-release-line-reconciliation/evidence/inventory-proofs.md` from the spec's inventory table (#1–#24), with these columns: `#`, item, method, seams, **proof** (test node id or recorded check), state (`data-model.md` state machine). Pre-fill the proof for #1–#13 with the rc_1 test file that came with each item: `tests/test_disarm_video_layers.py`, `test_video_placement_failure.py`, `test_arm_*`, `test_arm_inventory.py` (#4, pre-arm measurement lines), `test_cue_media_dimensions.py`, `test_own_media_sizes.py`, `test_loop_video_wraparound.py`, `test_cross_node_follow_*`, `test_arm_wait_messages.py`, `test_player_handler_port_wait_abort.py`, `test_controller_cue_names.py`, `test_node_engine_load_orphan_eperm.py`, `test_player_handler_orphan_kill.py`, `test_controller_commands.py`, `test_video_unrouted_output.py`, `test_controller_stop_project.py` and `test_node_stop_project.py`. Map each file to its item by reading its docstring and ClickUp id. #2 (dead `VideoPlayer` deleted, `e890954`) came with no test; its proof is T026a. Any other item left without a file is flagged `NO PROOF` in the table and gets a test task before T048.

---

## Phase 2: Foundational (blocking)

**Purpose**: arm A, the baseline that every later comparison uses. **No merge may start before this
phase completes.**

- [X] T006 Run arm A on the unmodified branch, with the stub applied if T002 created one: `$PY -m pytest tests -m "not integration" -n auto -rfE` and then `$PY -m pytest tests -m "integration and not slow" -rfE`. Write both outputs, with the G6 header, to `specs/009-release-line-reconciliation/evidence/suite-arm-A.txt`. Extract the failing node ids into `specs/009-release-line-reconciliation/evidence/arm-A-failures.txt`, one id per line, sorted. These are expected to be the 8 environmental failures of WO §6.1, or fewer on a real host.
- [X] T007 Write `specs/009-release-line-reconciliation/evidence/expected-reds.md` listing the 10 merge-induced failures by node id (spec M5, WO §6.1): A-1 ×1 in `tests/test_action_cue.py`, A-2 ×5 in `tests/test_media_duration.py`, A-3 ×2 in `tests/test_loop_video_wraparound.py`, A-4 ×1 in `tests/test_cluster_identity.py`, A-6 ×1 in `tests/test_identity_sweep.py`.

**Checkpoint**: arm A recorded. Phase 3 can start.

---

## Phase 3: User Story 1 — Nothing shipped is lost on upgrade (Priority: P1) 🎯 MVP

**Goal**: every commit of `origin/debian/bookworm` and `origin/rc_1` is an ancestor of HEAD; #22 and
#23 are merged by SHA; the `rc5-2…rc5-6` entries are present and the hotfix tag is an ancestor.

**Independent test**: `git rev-list --count HEAD..origin/debian/bookworm` and `..origin/rc_1` both
print 0. `git merge-base --is-ancestor` succeeds for `35cbe78`, `d50ee4b` and `v0.1.0rc5-6`. The
changelog test (T024) passes its `debian/changelog` assertions. Every #1–#13, #22 and #23 proof in
`inventory-proofs.md` passes.

### The bookworm merge (one commit: resolutions only, FR-004)

- [X] T008 [US1] `git merge --no-ff --no-commit origin/debian/bookworm`. Confirm that `git diff --name-only --diff-filter=U` lists exactly the 7 files of spec M4, and record the list in `specs/009-release-line-reconciliation/evidence/merge-bookworm.md`. If the list differs, stop and record the difference before resolving.
- [X] T009 [US1] Resolve `src/cuemsengine/ControllerEngine.py`, both hunks, per FR-004:
  - Hunk 1 (`status_operation_callback`): **take theirs**, deleting the `script_finished` branch and keeping the `stop_project` branch.
  - Hunk 2 (arm watchdog message): **combine** theirs' `f"{what} stalled…"` text with ours' `self._sorted_ids(pending)`. Never use `sorted(pending)`.

  Then `$PY -c "import ast,sys; ast.parse(open('src/cuemsengine/ControllerEngine.py').read())"`.
- [X] T010 [P] [US1] Resolve `tests/test_controller_commands.py` (2 hunks): **take theirs** (`_loaded_script()`, `project_unix_name`, `set_status("load", …)`). Keep 008's uuid literal, and check that `UUID_A` is a valid uuid4 (`uuid.UUID(UUID_A).version == 4`); record the result in `merge-bookworm.md`.
- [X] T011 [P] [US1] Resolve `tests/test_nodelist_modify.py` (1 hunk): **take ours**, the typed `adopted_network_map(...)` fixture, since `_adopted_uuids_from_network_map` no longer exists.
- [X] T012 [P] [US1] Resolve `pyproject.toml` (2 hunks): **take ours** (`version = "0.1.1"`, `cuemsutils = ">=0.1.1,<0.1.2"` with its comment, and the pyossia dev wheel). Add one comment line above the `cuemsutils` constraint: `# 0.1.1 must contain rc17's stop_project (X-1, specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md)`. That report is only written in T059, so the path dangles until then. This is accepted: nothing is published in between, and T066 checks that the path resolves.
- [X] T013 [P] [US1] Resolve `src/cuemsengine/__init__.py`: **ours** for `__version__ = "0.1.1"`, **plus** theirs' added `SPDX-FileContributor: Ion Reguera …` line.
- [X] T014 [P] [US1] Resolve `debian/control` (2 hunks):
  - **Ours** for every versioned `Depends` and the explanatory comment.
  - **Theirs** for the SPDX header, the mock package's `Conflicts: cuems-audioplayer, cuems-dmxplayer`, and the renamed mock binaries in the mock description.
  - Then check that `cuems-utils (>= 0.1.0rc17)`, `cuems-common (>= 1.0.0)` and `cuems-engine (>= 0.1.0rc2)` do **not** appear: `grep -nE "0\.1\.0rc17|>= 1\.0\.0\)|0\.1\.0rc2\)" debian/control` must be empty.
- [X] T015 [P] [US1] Resolve `debian/changelog`. Keep **ours'** `cuems-engine (0.1.1-1) UNRELEASED` entry unchanged on top. Below it, insert bookworm's entries `0.1.0rc6-5` down to `0.1.0rc3-1` **verbatim**, taken from `git show origin/debian/bookworm:debian/changelog`, in their dpkg order. Keep ours' `rc2-3…rc1-1` below them. No other text changes; the hotfix entries come in T025 and the body in T054.
- [X] T016 [US1] Check that no conflict markers remain (`git diff --check`; `git grep -nE '^(<<<<<<<|>>>>>>>|=======)$' -- src tests debian pyproject.toml` empty). Revert the libmtc stub if applied, then `git commit -S`. Message: `merge(009): absorb origin/debian/bookworm (0.1.0rc6-5) into 0.1.1-1`, listing the FR-004 resolution of each file. **The commit contains the resolutions and nothing else.**
- [X] T017 [US1] Run arm B (both passes, as in T006) on the merge commit, and write `specs/009-release-line-reconciliation/evidence/suite-arm-B.txt` plus `arm-B-failures.txt`. Compute `comm -13 arm-A-failures.txt arm-B-failures.txt` and compare the result with `expected-reds.md`. Any id outside the 10 is a **new finding**: append it to `expected-reds.md` with a classification (environmental, cuems-utils drift past its tag, or a new seam needing an adaptation task) before continuing.

### The rc_1 merge and the stray heads #22 and #23

- [X] T018 [US1] `git merge --no-ff -S origin/rc_1`. Resolve every conflict to **ours** (its `0.1.0rc2` version sites and its `debian/`), per FR-004's last row, and check `git diff HEAD^1 --stat -- src tests` is empty. Commit message: `merge(009): record origin/rc_1 ancestry (698e777)`.
- [X] T019 [US1] Write a red test for #22 in `tests/test_node_output_maps.py`: given project mappings whose node lists both `inputs` and `outputs` (input 0 → `system:capture_1`, output 0 → `system:playback_1`), NodeEngine's output→JACK-port and output→display lookups for `<node>_0` resolve to the **output**. Load the mappings through the same typed project-mappings path 008 uses (A-7), not a dict. Run it on HEAD (before `35cbe78`) and capture the red to `specs/009-release-line-reconciliation/evidence/failing-first-A-7.txt`. It must fail on resolving to `system:capture_1`. If T003 found `35cbe78` already absorbed via `rc_1` (so HEAD is already green), show the red on a temporary worktree at `35cbe78^` and record that in the same file.
- [X] T020 [US1] `git merge --no-ff -S 35cbe78`. Resolve the shared test-file conflicts by the T010/T011 rules. Run `tests/test_node_output_maps.py` (green) and `tests/test_default_mappings_valid.py`. Commit the T019 test in the same merge commit, or as the commit right before it, with the red evidence. Mark #22 `proven` in `inventory-proofs.md`.
- [X] T021 [US1] Write a red test for #23 in `tests/test_mock_players_jack_ready.py`: run the mock audioplayer's and the mock jack-volume's startup path (`src/cuemsengine/scripts/mock_audioplayer.py`, `mock_jack_volume.py`) with the JACK client mocked. Assert that each registers its output ports and prints the `[OK] RUNNING!` readiness line the ready gate waits for (item 8). Capture the red on HEAD to `specs/009-release-line-reconciliation/evidence/failing-first-23.txt`. If T003 found `d50ee4b` already absorbed via `rc_1`, show the red on a temporary worktree at `d50ee4b^` instead and record that.
- [X] T022 [US1] `git merge --no-ff -S d50ee4b`, resolving the shared test conflicts the same way. Run the T021 test (green), and mark #23 `proven`.

### Hotfix line rc5-2…rc5-6 (FR-008)

- [X] T023 [US1] Write `specs/009-release-line-reconciliation/evidence/hotfix-rc5-equivalence.md`:
  - The WO §4.1 row 21 table, one row per hotfix code commit → its `rc_1` commit. The mappings are `951503d→7b35ccf`, `7bccee8→8803dfe`, `cf5421f→f391675`, `68b09a0→4fc6d08`, `5509d87→0f7fb17`, `6eb827f→2e96b1c`, `092d99f→ecafa23`, `2d8facc→58869e6`, `24e8054→ee3b060`, `929fdc0→674aefb` and `47b06b5→32dae0d`; the rest are patch-equivalent.
  - The verbatim output of `git cherry -v HEAD v0.1.0rc5-6`, with each `+` line accounted for.

  **If any `+` commit has no equivalent, stop**: FR-008 blocks the `-s ours` merge, so record the
  missing commit as a new inventory item.
- [X] T024 [US1] Write `tests/test_changelog_complete.py` per contract C3, **assertions 1–4 only** (the `debian/changelog` side). It resolves the sources with `git rev-parse --verify` and skips with `missing refs: …` when one is absent. Run it with fresh refs: it must run (not skip) and fail on assertion 2, listing exactly `0.1.0rc5-2 … 0.1.0rc5-6`. Capture the output to `specs/009-release-line-reconciliation/evidence/failing-first-changelog-hotfix.txt`.
- [X] T025 [US1] Copy the five entries `0.1.0rc5-6 … 0.1.0rc5-2` verbatim from `git show v0.1.0rc5-6:debian/changelog` into `debian/changelog`, between `0.1.0rc6-1` and `0.1.0rc5-1`. Run T024's test: assertions 1–4 green. Commit test and entries together: `docs(changelog): absorb released 0.1.0rc5-2…rc5-6 hotfix entries`.
- [X] T026 [US1] `git merge -S -s ours v0.1.0rc5-6`, with the message `merge(009): record v0.1.0rc5-6 hotfix ancestry (content already absorbed; see specs/009-release-line-reconciliation/evidence/hotfix-rc5-equivalence.md)`. Check `git diff HEAD^1 HEAD --stat` is empty.
- [X] T026a [US1] **#2 proof**: write `tests/test_dead_videoplayer_removed.py`, asserting that `cuemsengine.players` exports no `VideoPlayer`, that `src/cuemsengine/players/VideoPlayer.py` defines no `VideoPlayer` class (`VideoClient` and `VideoOutput` stay), and that `CueHandler` declares no `_front_video_player`. Show it red on a temporary worktree at `e994a5e` (`git worktree add ../009-red-2 e994a5e`, removed afterwards) and capture that to `specs/009-release-line-reconciliation/evidence/failing-first-2.txt`. Run it green on HEAD, mark #2 `proven` in `inventory-proofs.md`, and commit `test(009/#2): the dead VideoPlayer stays deleted (869f8v8yv)`.
- [X] T027 [US1] Verify US1's independent test, and record the commands and outputs in `specs/009-release-line-reconciliation/evidence/us1-check.md`:
  - both behind-counts are 0
  - `35cbe78`, `d50ee4b` and `v0.1.0rc5-6` are ancestors of HEAD
  - `5a1811c` and `3c11c60` are **not** ancestors (FR-007), unless T003 recorded #24 on `rc_1`: then they **are** ancestors and the FR-016 tasks are listed as done
  - the rc_1 proofs for #1–#13 are listed with their pass/fail on HEAD. Any failure must be one of the 10 expected reds, which US2 fixes.

**Checkpoint**: US1 delivered. Nothing shipped is missing from history or from `debian/changelog`.

---

## Phase 4: User Story 2 — Absorbed code obeys the 0.1.1 contract (Priority: P1)

**Goal**: the 10 merge-induced reds are green; the absorbed code follows the 008 identity and
typed-map rules; R-1…R-4 are proven.

**Independent test**: the suite shows no failure outside `arm-A-failures.txt`, and
`identity-audit-009.md` is clean (SC-003, SC-005).

### The red-on-merge adaptations (red evidence = arm B)

- [X] T028 [P] [US2] **A-1**: extract the A-1 failure from `suite-arm-B.txt` into `specs/009-release-line-reconciliation/evidence/failing-first-A-1.txt`. In `tests/test_action_cue.py::TestFadeActionsFromAVersion1Script::test_former_fade_out_is_stop_and_disarms_its_target`, change the expected disarm call to `disarm(..., reason="stop_action")`, keeping the assertion that a version-1 `fade_out` becomes `stop`. Run it green and commit: `test(009/A-1): expect the disarm reason introduced by 869f8hfra`.
- [X] T029 [P] [US2] **A-2**: extract the 5 A-2 failures into `specs/009-release-line-reconciliation/evidence/failing-first-A-2.txt`. In `tests/test_media_duration.py`, give the player-handler mock `cue_media_dimensions.return_value = (1920, 1080)`, leaving every duration assertion untouched. Run the file green and commit `test(009/A-2): …`.
- [X] T030 [P] [US2] **A-3**: extract the 2 A-3 failures into `specs/009-release-line-reconciliation/evidence/failing-first-A-3.txt`. In `tests/test_loop_video_wraparound.py`, replace `SimpleNamespace(duration="00:00:10.000")` with a `CTimecode` duration built the way `tests/test_media_duration.py` builds it. **Do not** change `media_duration()` in `src/`. Run it green and commit `test(009/A-3): …`.
- [X] T031 [P] [US2] **A-6**: extract the A-6 failure into `specs/009-release-line-reconciliation/evidence/failing-first-A-6.txt`. In `tests/test_identity_sweep.py::test_an_editor_cue_id_as_str_matches_the_scripts_uuid_cue_id`, set the engine's `running` status to `"yes"` in the arrangement. Add the negative twin `test_an_editor_cue_add_is_ignored_while_not_running`: `running="no"`, a `str` id, and assert that the ADD is ignored with its log line. Run both green and commit `test(009/A-6): …`.
- [X] T032 [US2] **A-4, retirement**: extract the A-4 failure into `specs/009-release-line-reconciliation/evidence/failing-first-A-4.txt`. Delete `test_script_finished_from_str_senders_closes_the_run` from `tests/test_cluster_identity.py`. Create `specs/009-release-line-reconciliation/evidence/test-retirements.md`, with a row for this test giving its reason (869fhjdp8 deleted the `script_finished` aggregator; 008 frozen per FR-015) and its replacement (T033).
- [X] T033 [US2] **A-4, replacement**: in `tests/test_cluster_identity.py`, add four cases. A `stop_project` status op and a `follow` status op whose `sender` is a **`str`** uuid are each (a) accepted when the sender is an adopted node whose map id is a `Uuid` (typed map via `tests/network_map_helpers.py`), and (b) refused when the sender is not adopted. Run them. If any fails, capture it to `failing-first-A-4-replacement.txt` and fix the comparison in `src/cuemsengine/ControllerEngine.py` with `as_id`. If all pass first time, record "characterization, no production change" in `test-retirements.md`. Commit `test(009/A-4): …`.

### A-5: identity conformance of absorbed code (FR-017)

- [X] T034 [US2] Add one test per **wire-leaving** id site to `tests/test_identity_sweep.py`. Each feeds a `Uuid` id (uuid4) and asserts that the emitted value is `id_str(...)` text and that no `TypeError` is raised:
  1. the `FollowRelay` announce payload `source`
  2. the `FollowRelay` cancel payload
  3. the `stop_project` status op `cue`
  4. `get_project_status()["project_uuid"]`
  5. the cue-name OSC address `/engine/status/cue_name/<id>`
  6. the `check_unrouted_video_outputs` report `cue_id`
  7. the NodeEngine stop-project notify
  8. the `PlayerHandler` hyphen-stripped slug

  Add one **incoming** case too: a `follow` op whose `source`/`target` arrive as `str` matches the project's `Uuid` cue ids. Run them, and capture every red to `specs/009-release-line-reconciliation/evidence/failing-first-A-5.txt`.
- [X] T035 [P] [US2] Convert `src/cuemsengine/cues/FollowRelay.py`: outgoing `str(cue.id)` and the payload ids become `id_str(...)`; incoming `data.get("source")`/`data.get("target")` go through `as_id(...)` before comparison. Import from `cuemsengine.tools.ids`.
- [X] T036 [P] [US2] Convert `src/cuemsengine/ControllerEngine.py`: `_handle_stop_project` gets `as_id(data.get("cue", ""))` for comparisons and `id_str` for anything emitted; `get_project_status` gets `"project_uuid": id_str(self.script.id)`; the cue-name OSC address and any `str(item.id)` in `_collect_cue_names` become `id_str(...)`.
- [X] T037 [P] [US2] Convert `src/cuemsengine/NodeEngine.py`: `check_unrouted_video_outputs` emits `"cue_id": id_str(cue.id)`; the stop-project notify's `str(cue_id)` becomes `id_str(cue_id)`.
- [X] T038 [P] [US2] Convert `src/cuemsengine/players/PlayerHandler.py`: all five `str(cue.id)` become `id_str(cue.id)`, and the slug becomes `"".join(id_str(cue.id).split("-"))`.
- [X] T039 [P] [US2] Convert `src/cuemsengine/cues/run_cue.py`: the slug near the WO's `:235` becomes `"".join(id_str(cue.id).split("-"))`.
- [X] T040 [US2] Run T034's tests green. Then sweep **every remaining** `str(<id>)` and raw-id use in code absorbed from the release line (clarified Q5 → A): `git diff e994a5e HEAD -- src/ | grep -nE 'str\([^)]*(\.id|_id|uuid|sender)\b'` plus `git grep -nE 'sorted\(|\.split\(|\[[0-9]*:[0-9]*\]' -- src/` restricted to the absorbed files. Convert each to `id_str`/`as_id`, including dict keys and log joins. **TDD framing**: these non-wire conversions are the *refactor* step (constitution II.4). Before converting, confirm that a currently green test exercises each touched function, and list it. If none exists, write a characterization test first. Re-run those tests after converting. A conversion that changes observable behaviour (for example a dict lookup that now matches a key it missed before) is not a refactor: stop and give it its own red test. Commit `fix(009/A-5): ids leave through id_str and enter through as_id in absorbed code`.
- [X] T041 [US2] Re-run 008's identity audit method (`specs/008-cuems-utils-migration/evidence/identity-audit.md`) over the merged `src/`, including `git grep -n 'import.*\bUuid\b' -- src/`, which must be empty. Write `specs/009-release-line-reconciliation/evidence/identity-audit-009.md` with zero findings (SC-005), plus T040's table: converted site → the green test that covers it.

### Risks R-1…R-4 (red first, or characterization)

- [X] T042 [US2] **R-1 fixture**: create `dev/test_xml_files/projects/video_no_pixels_v2/script.xml`, a minimal **version-2** script with one VideoCue whose `<media>` has a `file_name` and a `duration` but no `pixel_width`, `pixel_height` or `file_size`. Copy the header and namespaces from `dev/test_xml_files/projects/complex_test_v2/script.xml`. It moves to `tests/data/` in T097. Validate it by loading it with `CuemsScript.load`.
- [X] T043 [US2] **R-1 test**: in `tests/test_cue_media_dimensions.py`, add a test that loads T042's script through `CuemsScript.load`, takes its VideoCue, and asserts that `PlayerHandler.cue_media_dimensions(cue)` takes the **probe** path (mock the probe and assert it was called), and that the own-media check treats `file_size` as missing. Also assert `media.get("pixel_width") is None` (research R3).
  - If it passes first time: record "R-1: characterization; `Unset` is key-absent on 0.1.1" in `specs/009-release-line-reconciliation/evidence/r1-media-unset.md`.
  - If it fails: capture `failing-first-R-1.txt`, and fix in `src/cuemsengine/players/PlayerHandler.py` by treating the published `cuemsutils.helpers.Unset` as missing.
- [X] T044 [P] [US2] **R-2**: in `tests/test_controller_cue_names.py`, add a test over a real version-2 script (T042's script, extended, or `complex_test_v2`) with one cue whose name is empty (`<name/>`) and one CueList child. Assert that the cue-name walk yields `""` for the empty name, descends into the CueList's children, and raises nothing. Red → `failing-first-R-2.txt` plus a fix in `ControllerEngine._collect_cue_names`; otherwise record a characterization.
- [X] T045 [P] [US2] **R-3**: in `tests/test_controller_stop_project.py`, add a test that an ActionCue with `action_type="stop_project"` and no target, built in code, is dispatched and **not** rejected by any unknown-action guard in `src/cuemsengine/cues/ActionHandler.py`. Keep the rc_1 "other project actions still rejected" test green. Red → `failing-first-R-3.txt` plus a fix; otherwise record a characterization.
- [X] T046 [P] [US2] **R-4**: add a test to `tests/test_controller_stop_project.py` and `tests/test_cross_node_follow_controller.py` that, on one typed map with adopted, non-adopted and offline nodes, the set accepted by the `stop_project` sender check and by the follow relay equals `ControllerEngine._adopted_node_uuids()` as the GO gate uses it. Red → `failing-first-R-4.txt` plus a fix that routes both through `_adopted_node_uuids`; otherwise record a characterization.
- [X] T047 [US2] Commit T042–T046 as one commit per risk id (`test(009/R-n): …` / `fix(009/R-n): …`), each with its evidence file.

### US2 checkpoint

- [X] T048 [US2] Run both suite passes, and write `specs/009-release-line-reconciliation/evidence/suite-after-adapt.txt` and `after-adapt-failures.txt`. `comm -13 arm-A-failures.txt after-adapt-failures.txt` must be **empty** (SC-003, first pass). Lint every file changed since T016. Update `inventory-proofs.md`: #1–#13 `proven`.

**Checkpoint**: US1 + US2 make a releasable code state. The rest is record-keeping, obligations,
cleanup and the gate.

---

## Phase 5: User Story 3 — The stable changelog lists every build that ever shipped (Priority: P2)

**Goal**: `debian/changelog` and `CHANGELOG.md` both cover `rc1-1…rc6-5` plus `0.1.1-1`; the packages
build at `0.1.1-1` with their 016 relation values.

**Independent test**: `tests/test_changelog_complete.py` (all 5 assertions of C3) runs and passes;
verdicts are 27/27; both debs are built and inspected.

- [X] T049 [US3] Extend `tests/test_changelog_complete.py` with C3 **assertion 5**: every version from assertion 2 is named in `CHANGELOG.md` by a `<!-- source: … -->` comment or an inline `(<version>, YYYY-MM-DD)`; the first `## v` header is `v0.1.1`; and the `v0.1.1` section does not contain "not reconciled". Run it and capture the red, listing the missing versions (at least `rc6-2…rc6-5` and `rc5-2…rc5-6`), to `specs/009-release-line-reconciliation/evidence/failing-first-changelog-md.txt`.
- [X] T050 [US3] In `CHANGELOG.md`, extend `## v0.1.0rc6`:
  - add one `<!-- source: debian/bookworm 0.1.0rc6-N (<sha>) -->` comment per build, for N = 2…5 (shas from `git log --format=%h -1 v0.1.0rc6-N`)
  - add each build's content (items #1–#13 and #15, as worded in that build's Debian entry) under the existing `Added`/`Changed`/`Fixed` sub-headers, with an inline `(0.1.0rc6-N, YYYY-MM-DD)`

  No new top-level header (FR-032).
- [X] T051 [US3] In `CHANGELOG.md`, extend `## v0.1.0rc5` with `rc5-2…rc5-6` the same way. Source comment: `<!-- source: tag v0.1.0rc5-6 (69e91e4), hotfix line -->`. Content from those five Debian entries.
- [X] T052 [US3] Audit every older `CHANGELOG.md` section (`v0.1.0rc4`, `rc3`, `rc2`, `v0.1.0`) against the merged `debian/changelog`, one build at a time. Add a source comment or inline revision for any missing build; `rc2-3` (the mock rsync shim) and `rc1-1` are the known unverified rows. Record the audit table in `specs/009-release-line-reconciliation/evidence/changelog-md-audit.md`.
- [X] T053 [US3] Rewrite the `## v0.1.1 — UNRELEASED` lead paragraph of `CHANGELOG.md`:
  1. "Contains every change released in 0.1.0rc3-1 … 0.1.0rc6-5 (including the 0.1.0rc5-2…rc5-6 hotfix builds), absorbed from debian/bookworm at `<sha of T016>`."
  2. The X-1 condition: "`stop_project` requires cuems-utils 0.1.1 to carry rc17's value; see specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md". If US4 has not run yet, the path dangles until T059 (accepted; T066 checks it).
  3. The FR-038 line: "Every host in a cluster must be upgraded together: the GO payload carries `run_seq` (not wire-compatible with engines before 0.1.0rc6-3)".

  Run `tests/test_changelog_complete.py` (all assertions green) and `tests/test_version_single_source.py`. Commit `docs(changelog): CHANGELOG.md covers every released build`.
- [X] T054 [US3] Rewrite the `0.1.1-1` entry body in `debian/changelog` (FR-031):
  - replace the "NOT YET RECONCILED" bullet with "Reconciled with debian/bookworm at `<T016 sha>` (0.1.0rc6-5): absorbs 0.1.0rc6-2..rc6-5", followed by one line per item #1–#13
  - add the X-1 condition bullet and the FR-038 "upgrade every host together" bullet
  - keep the `poetry.lock` bullet

  Check `dpkg-parsechangelog -l debian/changelog -S Version` prints `0.1.1-1`, if `dpkg-dev` is
  installed; otherwise the T024 assertion 1. Run the changelog test (green) and commit.
- [X] T055 [US3] Audit `debian/rules` after the merge, and write `specs/009-release-line-reconciliation/evidence/debian-rules-audit.md` quoting the line for each of:
  - `PIP_IGNORE_INSTALLED=1`, `PYTHONNOUSERSITE=1` and the rtmidi vendoring check (#14)
  - the `cffi-gen-src` strip (#15)
  - the renamed mock wrappers `cuems-audioplayer`/`cuems-dmxplayer` (#16)
  - 016's venv `home = /usr/bin`
  - the SPDX header lines of `debian/control` and `debian/rules` (#17)

  If one is missing, stop and record it as a merge defect.
- [X] T056 [US3] Build both debs in a bookworm chroot with `../cuems-utils/specs/016-coordinated-minor-bump/tools/bookworm-build.sh`, adapted only by arguments. **Do not publish.** Write `specs/009-release-line-reconciliation/evidence/bookworm-build.md` with `dpkg -I` showing `Version: 0.1.1-1` for `cuems-engine`; for `cuems-engine-mock`, its `Depends: cuems-engine (>= 0.1.1)` and its `Conflicts:` naming both `cuems-audioplayer` and `cuems-dmxplayer`; and the output of `dpkg -c <cuems-engine deb> | grep CACHEDIR || echo absent`.
- [X] T057 [US3] If T056 found `/usr/lib/cuems/CACHEDIR.TAG`: write a check in `tests/test_debian_rules.py` that asserts `debian/rules` removes it, and capture the red to `failing-first-cachedir.txt`. Add the strip to `debian/rules` the way cuems-utils does (read `../cuems-utils/debian/rules` for the exact line), rebuild, re-check, and commit. If it is absent, record "absent; nothing to strip" in `bookworm-build.md` (FR-034, accepted default Q2).
- [X] T058 [US3] Run `../cuems-utils/specs/016-coordinated-minor-bump/tools/verdicts.sh` for the engine rows, and write `specs/009-release-line-reconciliation/evidence/relation-verdicts-009.txt`. It must show **27/27**; never write into 016's evidence. Mark #14–#18 and #20 `proven` in `inventory-proofs.md`, pointing at T055/T056/T058. #21's proof is T024–T026.

**Checkpoint**: US3 delivered. SC-007 and SC-008 hold, apart from lint, which is re-checked in T071.

---

## Phase 6: User Story 4 — Siblings know what they owe; `stop_project` cannot be forgotten (Priority: P2)

**Goal**: X-1 strict xfails exist; the cuems-utils report, the four sibling notes and the #24
structure message are written.

**Independent test**: `pytest -rxX` lists exactly `test_lock_is_current.py::test_poetry_lock_is_current` plus the X-1 tests as
xfailed, each with a reason naming its report; the six documents exist under `upstream-reports/`
(SC-004, SC-006).

- [X] T059 [US4] Write `specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md`:
  - **X-1**: `stop_project` in the version-2 `script.xsd` `ActionType` and in the ActionCue docs, **targetless** (the engine's evidence for utils 017's S-1 and D5; research R4).
  - **X-2**: keep `Replaces: cuems-engine (<< 0.1.0rc6-2~)` and add it to 016's relation matrix.
  - **X-3**: CACHEDIR.TAG, with T056/T057's result.
  - **X-4**: the `Media` `Unset` stays key-absent, with T043's result.
  - The successor path `specs/009-release-line-reconciliation/`, replacing the WO that utils 017 cites at `945ccba`.
  - The request that the utils maintainer link this report from cuems-utils' "still owed" list. That is their edit, not ours.
- [X] T060 [US4] Write `tests/test_stop_project_xsd.py` with the X-1 tests. Each is marked `@pytest.mark.xfail(strict=True, reason="cuems-utils 0.1.1 lacks rc17 stop_project — specs/009-release-line-reconciliation/upstream-reports/cuems-utils-x1-x4.md")`:
  - (a) `CuemsScript.load` of a version-2 script containing one ActionCue with `<action_type>stop_project</action_type>` and **no target** (fixture `dev/test_xml_files/projects/stop_project_v2/script.xml`, created here; it moves in T097) loads and yields that ActionCue
  - (b) saving that loaded script back through the published write path validates

  Run them: they must report `xfailed` (not error, not pass). If either passes, follow FR-021 instead: remove the marker and record it.
- [X] T061 [P] [US4] Write `specs/009-release-line-reconciliation/upstream-reports/cuems-frontend-engine-contracts.md`, naming the C4 rows W3 and W4, plus W1's "every host together" for awareness.
- [X] T062 [P] [US4] Write `specs/009-release-line-reconciliation/upstream-reports/cuems-editor-engine-contracts.md`, naming the C4 rows W2 and W4 (the save path through utils' XSD).
- [X] T063 [P] [US4] Write `specs/009-release-line-reconciliation/upstream-reports/cuems-power-bridge-engine-contracts.md`, naming the C4 rows W2 and W4 (their `0.3.1-2` half, absorbed in their 0.4.0-1 reconciliation).
- [X] T064 [P] [US4] Write `specs/009-release-line-reconciliation/upstream-reports/cuems-nodeconf-engine-contracts.md`, naming the C4 row W6: the planned `cuems-nodeconf.service.d` drop-in from `cuems-engine-mock`, whose shape is to be agreed in cuems-nodeconf's consolidation. Link the C5 structure.
- [X] T065 [P] [US4] Write `specs/009-release-line-reconciliation/upstream-reports/rc_1-mock-nodeconf-structure.md`, addressed to #24's author (Ion) and the `rc_1` maintainer. Carry contract C5 in full: placement, interface, rules 1–5, behaviours B1–B5 as the red-first test list, base, timing (after cuems-nodeconf's consolidation, before 0.1.1 is published) and the merge-by-SHA route. List the three defects of `5a1811c` (WO §4.1 row 24 (a)–(c)) so the author knows what to change.
- [X] T066 [US4] Run `$PY -m pytest tests -rxX -q | grep -E "XFAIL|XPASS"` and write `specs/009-release-line-reconciliation/evidence/strict-xfails.md`. The set must equal {`test_lock_is_current.py::test_poetry_lock_is_current`} ∪ {T060's tests}, each reason containing its report path (SC-004). Also check that every path cited in `pyproject.toml`, `CHANGELOG.md` and the xfail reasons under `upstream-reports/` now exists (I6). Commit T059–T066 as `docs(009): upstream reports and X-1 strict xfails`.

**Checkpoint**: US4 delivered.

---

## Phase 7: Docs and pre-cleanup verification (cross-cutting)

**Purpose**: FR-040 and FR-041; the hand-off re-measurement; the three interleaved arms. This
**must** complete before Phase 8, because moves before the final merge would turn clean merges into
rename conflicts.

- [X] T067 [P] Edit `CLAUDE.md`:
  - Any "needs cuems-utils ≥ rc17" for `stop_project` becomes "needs cuems-utils ≥ 0.1.1, which must absorb rc17's value (cuems-utils reconciliation)".
  - Remove leftover `script_finished` wording (`grep -n script_finished CLAUDE.md` must be empty).
  - Merge any section duplicated between 008's rc7 notes and rc_1's notes.
  - Leave the `<!-- SPECKIT START -->` block alone.
- [X] T068 [P] Edit `docs/unattended-playback.md`: `cuems-utils ≥ 0.1.0rc17` (about `:77`) → `cuems-utils ≥ 0.1.1`, and `engine 0.1.0rc6-3 or later` (about `:95`) → `cuems-engine 0.1.1-1 or later`. Add no dev-planning prose. Check `docs/index.md` for the same version claims. Commit T067 and T068: `docs(009): version claims after reconciliation`. Mark #19 `proven` (a recorded check).
- [X] T069 Re-fetch and re-measure exactly as T003 and T004, and write `specs/009-release-line-reconciliation/evidence/remeasure-handoff.md` plus an updated `stray-head-sweep.md`. **If anything moved**: merge the delta by the same rules (T008–T018 for line commits; merge-by-SHA for new heads), add the adaptation tasks it needs, and repeat T048 before continuing. Record the loop.
- [X] T070 Run the CI-equivalent suite **three times, interleaved**: arm A, which is `git worktree add ../009-armA e994a5e` plus the same stub, then the 009 HEAD, ×3. Write `specs/009-release-line-reconciliation/evidence/suite-final.md` with per-run counts and the failing-id sets. HEAD's failures must be ⊆ arm A's in every run (SC-003). Remove the worktree afterwards.
- [X] T071 Run lint on the whole tree as CI does (`black --check src/ tests/`, `isort --check src/ tests/`, `flake8 src/`), and fix any issues in a `style(009): …` commit. Record the result in `suite-final.md`.

**Checkpoint**: the code and record state is final. Only pure moves (Phase 8) and CI (Phase 9) follow.

---

## Phase 8: User Story 5 — A contributor can tell what is live (Priority: P3)

**Goal**: `dev/` holds only `scripts/` and `README.md`; strays are gone; `tests/` follows contract C2;
docs name real paths. **Pure moves and deletes: the pass set does not change.**

**Independent test**: SC-009. The forbidden-path greps are empty; `tests/` has no root `test_*.py`;
the contract layout test passes; unit+contract tests pass without network; the collected-id diff is
the path prefix plus the listed retirements only.

**Ordering note**: §14.4 (strays) runs before §14.3 (re-layout), so retired files are not moved
first. Each sub-section is one commit.

- [X] T072 [US5] Snapshot before the cleanup: `$PY -m pytest --collect-only -q > specs/009-release-line-reconciliation/evidence/collect-before.txt`, plus a full run's pass/fail per node id into `outcome-before.txt` (`-rA`).

### §14.1 `dev/` deletions (one commit)

- [X] T073 [US5] `git rm` the superseded and stale files under `dev/`: `CuemsEngine.py`, `CuemsEngine_old.py`, `AudioPlayerRemote.py`, `VideoPlayerRemote.py`, `NodeAudioPlayers.py`, `NodeVideoPlayers.py`, `NodeControl.score`, `cuems-engine.service`, `network_map.xsd`, `display.py`, `editor-engine-commands.txt`, `diagnose_env_output.txt`, `test_cleanup_demo.py`, `test_pyossia_gmq.py`, `test_pyossia_midi.py`, `test_pyossia_without_daemon.py`, `test_json_files/`, and `test_xml_files/test_jsons.txt`. First note the last commit of the pyossia scripts with `git log -1 --format=%h -- dev/test_pyossia_*.py`.
- [X] T074 [US5] Append one line to `specs/planning/PYOSSIA_EVALUATION_RESULTS.md`: "The investigation scripts `dev/test_pyossia_{gmq,midi,without_daemon}.py` were deleted in 009; last commit `<sha from T073>`."
- [X] T075 [US5] `git rm dev/scripts/change_to_firstrun.sh dev/scripts/change_to_master.sh dev/scripts/change_to_slave.sh dev/scripts/diagnose_env.py dev/scripts/run_cpu_tests.py`.
- [X] T076 [US5] Compare the process names matched by `dev/scripts/kill_cuems_processes.py` and `dev/scripts/kill_cuems.sh` against 869evtdf7's binary names (`cuems-audioplayer`, `cuems-dmxplayer`, `cuems-videocomposer`, own-user only). Update `dev/scripts/kill_cuems.sh` if it matches stale names, then `git rm dev/scripts/kill_cuems_processes.py`. Record the comparison in `specs/009-release-line-reconciliation/evidence/kill-cuems-check.md` (accepted default Q9).
- [X] T077 [US5] Rewrite `specs/planning/README_CPU_TESTS.md`: replace every `run_cpu_tests.py` invocation with `pytest tests/integration/test_cpu_usage.py -m slow`, the path after T101.
- [X] T078 [US5] Remove the `dev/local/` rule from `.gitignore` (the media rule is re-pointed in T098). Run the suite (unchanged pass set versus `outcome-before.txt`, since the fixtures are not moved yet) and commit `chore(009/14.1): delete superseded dev/ content`.

### §14.2 developer tools (one commit)

- [X] T079 [US5] `git mv scripts/osc_send.py dev/scripts/osc_send.py`. Confirm the top-level `scripts/` is now empty and gone.
- [X] T080 [US5] Create `dev/README.md`: one line each for `scripts/link-dev.sh` (the editable `cuemsengine.pth` overlay over `/usr/lib/cuems`), `scripts/kill_cuems.sh` and `scripts/osc_send.py`, plus "Nothing under `dev/` is packaged or run by CI." Also fix the usage comments inside `dev/scripts/link-dev.sh` (lines 7–8) to say `./dev/scripts/link-dev.sh`.
- [X] T081 [US5] Fix `README.md:243` and `CONTRIBUTORS.md:69` to `dev/scripts/link-dev.sh`. Then `git grep -nE "(^|[^/])scripts/link-dev\.sh" -- . ':!specs' ':!.specify'` must be empty.
- [X] T082 [US5] Run `/speckit-constitution` for a **MINOR 1.1.0 → 1.2.0** amendment of `.specify/memory/constitution.md` (FR-046, research R8):
  - lines 122 and 139: `scripts/link-dev.sh` → `dev/scripts/link-dev.sh`
  - lines 117–118: test files live under `tests/` at the repository root, split by kind into `tests/unit/`, `tests/integration/` and `tests/contract/`, with helpers in `tests/support/` and fixtures in `tests/data/`. The directory decides the marker, and each module is named after the source module it covers (`test_<module>.py`). C2's classification rule is the reference.
  - update the Sync Impact Report and `Last Amended`; no other text changes

  The layout itself arrives in the 14.3 commit, a few commits later in the same unpushed phase. Run the suite and commit T079–T082: `chore(009/14.2): developer tools in dev/scripts`.

### §14.4 strays (one commit)

- [X] T083 [P] [US5] `git rm -r src/cuems/`, after confirming `git grep -n "from cuems\b\|import cuems\b" -- src tests debian` has no hit.
- [X] T084 [P] [US5] `git rm src/cuemsengine/scripts/system_ports.py`, after confirming `git grep -n "scripts.system_ports\|scripts/system_ports" -- src tests debian pyproject.toml` has no hit.
- [X] T085 [US5] Fold whatever is still true in `specs/planning/README_CLEANUP.md` (the `engine_cleanup` fixture in `tests/conftest.py`) into a "Test cleanup" paragraph of `CONTRIBUTORS.md`'s testing section. Then `git rm tests/pytest_cuems_plugin.py specs/planning/README_CLEANUP.md`, and remove the `cuems` marker from `pyproject.toml`.
- [X] T086 [US5] For `tests/testdev_engines_communication.py`, `testdev_ossia_oscquery.py` and `testdev_ossia_queue.py`: run each once (`$PY -m pytest tests/testdev_*.py -p no:randomly -rA`) and record the outcomes. For each of the 3 passing cases, find a collected test that covers the same behaviour. If none exists, `git mv` that case into a new `tests/test_<topic>.py`, to be classified in T101. Then `git rm` the three files, and add rows to `evidence/test-retirements.md` (FR-048).
- [X] T087 [US5] `git rm --cached .venv/pyvenv.cfg`; remove the `!.venv/pyvenv.cfg` un-ignore line from `.gitignore`, keeping the ignore; add `.venv-*/`, `.ruff_cache/`, `.016-native/` and `/__pycache__` to `.gitignore`.
- [X] T088 [US5] `git grep -n "\bVideoPlayer\b" -- . ':!specs'` must find no reference to the deleted `VideoPlayer` **class** in docs (the module `players/VideoPlayer.py` survives with `VideoClient`/`VideoOutput`; only the class went in `e890954`); fix any doc hit. Run the suite and compare with `outcome-before.txt`: the differences must be only T086's retirements. Commit T083–T088: `chore(009/14.4): delete stray packages, plugin and uncollected tests`.

### §14.3 `tests/` re-layout (one commit)

- [ ] T089 [US5] Write `tests/test_layout.py`. It moves to `tests/contract/` in T101, and is written at the root first so that it can run red. It asserts the three C2 invariants: no `tests/test_*.py` or `testdev_*.py` at the root, other than itself, which the check exempts while it sits at the root; every collected item has exactly one of `unit`/`integration`/`contract`, matching its directory; and no file under `tests/` other than `tests/support/paths.py` spells `test_xml_files` or `tests/data`. Run it and capture the red to `specs/009-release-line-reconciliation/evidence/failing-first-layout.txt`.
- [ ] T090 [US5] In `pyproject.toml` `[tool.pytest.ini_options]`, register the `contract` marker next to `unit`, `integration` and `slow`, and keep `--strict-markers`. In `[tool.coverage.run]`, add `relative_files = true` (research R6).
- [ ] T091 [US5] Add the directory-marker hook to `tests/conftest.py` (C2 "Hook semantics"): `pytest_collection_modifyitems` adds `unit`/`integration`/`contract` from the first path segment under `tests/`, and raises `pytest.UsageError` naming the file for any item outside them.
- [ ] T092 [US5] Create `tests/support/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` and `tests/contract/__init__.py`, each with an SPDX header.
- [ ] T093 [US5] `git mv tests/helpers.py tests/fixtures.py tests/network_map_helpers.py tests/reader.py tests/support/`. Rewrite every import across `tests/` (`from .fixtures` / `from tests.fixtures` → `from tests.support.fixtures`, and so on): `git grep -nE "(from|import) (\.|tests\.)?(helpers|fixtures|network_map_helpers|reader)\b" -- tests` must show only the new form.
- [ ] T094 [US5] Create `tests/support/paths.py` with `DATA_DIR = Path(__file__).resolve().parent.parent / "data"`. Find every hand-built data path with `git grep -nE '"dev"\s*/\s*"test_xml_files"|dev/test_xml_files' -- tests` (at analysis time: three in `fixtures.py`, one in `network_map_helpers.py`, one in `test_action_cue.py`, but the line numbers move with the merges) and replace each with `DATA_DIR`. Delete the commented-out copies the same grep finds in `fixtures.py`.
- [ ] T095 [US5] In `tests/test_project_go.py`, remove `from .conftest import engine_cleanup`. Fixtures resolve by name, so check that the fixture is still requested as a parameter.
- [ ] T096 [US5] Delete every hand-written `@pytest.mark.unit` and `@pytest.mark.integration` decorator under `tests/`. Keep `@pytest.mark.slow`. `git grep -nE "mark\.(unit|integration)\b" -- tests` must be empty.
- [ ] T097 [US5] `git mv dev/test_xml_files/* tests/data/`: settings, network_map, default_mappings, project_mappings, project_settings and `projects/` (including T042's and T060's fixtures). Then `rmdir dev/test_xml_files`.
- [ ] T098 [US5] Re-point `.gitignore` `dev/test_xml_files/media/` → `tests/data/media/`. Confirm that `dev/` now contains only `README.md` and `scripts/` (`find dev -maxdepth 1`).
- [ ] T099 [US5] Fix every remaining reference to the old fixture path outside `specs/`: `git grep -n "dev/test_xml_files" -- . ':!specs'` must be empty. That covers README, CONTRIBUTORS and CLAUDE.md as well as code.
- [ ] T100 [US5] Classify every `tests/test_*.py` by C2's rule. Start from the WO §14.3 split:
  - **integration**: `test_comms_nodehub`, `test_ossia`, `test_ossia_bundle_support`, `test_pyossia_osc`, `test_pythonosc`, `test_project_load`, `test_project_go`, `test_cpu_usage`, `test_core_baseengine`, `test_cuems_deploy_integration`, and `test_gradient_client` (check whether its UDP is real)
  - **contract**: `test_public_surface`, `test_version`, `test_version_single_source`, `test_lock_is_current`, `test_default_mappings_valid`, `test_changelog_complete`, `test_layout`, `test_stop_project_xsd`, and `test_debian_rules` if T057 created it
  - **unit**: everything else

  Grep each candidate unit file for unpatched `pynng`, `socket`, `SimpleUDPClient`, `subprocess`,
  `jack` or `sleep(` of ≥ 0.5, and confirm the patching for `test_cuems_deploy`,
  `test_players_audiomixer`, `test_node_engine_load_orphan_eperm` and
  `test_player_handler_orphan_kill`. Write `specs/009-release-line-reconciliation/evidence/test-layout-moves.md`
  with one row per file: file → directory → signal.
- [ ] T101 [US5] Split `tests/test_port_handler.py`: move `test_concurrent_draws_are_distinct` into `tests/integration/test_port_handler_concurrency.py`, and `git mv` the rest to `tests/unit/test_port_handler.py` (accepted default Q10). Then `git mv` every other file per T100's table. `ls tests/test_*.py` must print nothing.
- [ ] T102 [US5] Run `tests/contract/test_layout.py` (green). Then collect again into `specs/009-release-line-reconciliation/evidence/collect-after.txt`, and record in `test-layout-moves.md` that the diff of node ids with the directory prefix stripped is **only** the T086 retirements. Do a full run into `outcome-after.txt`: per-id outcomes must equal `outcome-before.txt` (SC-009).
- [ ] T103 [US5] Run `unshare -rn $PY -m pytest tests/unit tests/contract -n auto -q`, or another no-network sandbox, and record in `specs/009-release-line-reconciliation/evidence/cleanup-check.txt` that it passes with **0** of the WO §6.1 environmental failures.
- [ ] T104 [US5] Write `tests/README.md` with C2's classification rule and selection table. Add the same rule to `CONTRIBUTORS.md`'s testing section, with a note for `rc_1` developers that new tests go into `tests/unit/`, `integration/` or `contract/`, never the root (FR-059). Write `specs/009-release-line-reconciliation/upstream-reports/rc_1-test-layout.md`, addressed to the `rc_1` maintainer: the layout, the classification rule, the marker hook, and how a test file written on `rc_1` at the root is placed when it merges (SC-006). Check that README, CONTRIBUTORS and CLAUDE.md name `tests/{unit,integration,contract}` wherever they describe running tests.
- [ ] T105 [US5] Run the full SC-009 check into `cleanup-check.txt`:
  - `git grep -nE "dev/test_xml_files|test_json_files|pytest_cuems_plugin|CuemsEngine_old" -- . ':!specs'` is empty
  - the stale-path grep from T081 is empty
  - `find dev -maxdepth 2` shows only `dev/README.md`, `dev/scripts/` and its three tools
  - `ls tests/test_*.py` prints nothing
  - lint is clean on the moved paths

  Commit T089–T105: `refactor(009/14.3): tests by kind — unit, integration, contract`.

**Checkpoint**: US5 delivered.

---

## Phase 9: User Story 6 — The maintainer can gate publication with one cloud run (Priority: P2)

**Goal**: `.github/workflows/ci.yml` follows contract C1, with one green dispatched run on the 009
head recorded.

**Independent test**: SC-010. The dispatched run is green; its summary carries the engine SHA, the
cuemsutils ref and commit, the counts and the xfail list; the badge step is skipped.

**Priority note**: US6 (P2) is implemented after US5 (P3) because its jobs select tests **by
directory** (C1/C2).

- [ ] T106 [US6] In `.github/workflows/ci.yml`:
  - set the `on:` block per C1: `push` and `pull_request` on `[main, rc_1, feat/xml-refactor]`, and `workflow_dispatch` with the `cuemsutils_ref` input defaulting to `xml-refactor-merge-candidate`
  - add a top-level `env: CUEMSUTILS_REF: ${{ inputs.cuemsutils_ref || 'xml-refactor-merge-candidate' }}` and `PYTHON_KEYRING_BACKEND: keyring.backends.null.Keyring`
  - set the default `permissions: contents: read`
- [ ] T107 [US6] Replace the `test` job with a **`unit`** job (`needs: lint`, `debian:bookworm`), keeping the current system-package, native-library and Poetry 2.4.1 steps verbatim. Change these:
  - `actions/checkout@v4` with `fetch-depth: 0`, then the R2 fetch of `debian/bookworm`, `rc_1` and `--tags`
  - the C1 install sequence: `poetry add --lock …#${CUEMSUTILS_REF}`; a cache key from `hashFiles('poetry.lock')` computed **after** that step, plus the ref; `poetry install --with dev`; `systemd-python==235`; log the `resolved_reference` and `cuemsutils.__version__` to `$GITHUB_STEP_SUMMARY`; `git checkout -- pyproject.toml poetry.lock && git diff --exit-code`
  - `COVERAGE_FILE=.coverage.unit poetry run pytest tests/unit tests/contract -n auto --cov=src --cov-report= --junitxml=junit-unit.xml`
  - upload `.coverage.unit` and `junit-unit.xml`
- [ ] T108 [US6] Add the **`integration`** job (`needs: lint`, same container and install sequence; the default checkout depth is enough): `COVERAGE_FILE=.coverage.integration poetry run pytest tests/integration -m "not slow" --cov=src --cov-report= --junitxml=junit-integration.xml`, then upload both files. Keep the comment explaining why `slow` tests are not run here (FR-055).
- [ ] T109 [US6] Add the **`coverage`** job (`needs: [unit, integration]`, `permissions: contents: write`): download both artifacts, `coverage combine`, `coverage report --fail-under=45`, `coverage xml`. Move the badge generation and the `github-pages-deploy-action` steps here under `if: github.event_name == 'push' && (github.ref == 'refs/heads/main' || github.ref == 'refs/heads/rc_1')`. Upload `coverage.xml`.
- [ ] T110 [US6] Add the **`gate-summary`** job (`needs: [lint, unit, integration, coverage]`, `if: always()`). It downloads the JUnit XMLs and writes to `$GITHUB_STEP_SUMMARY`:
  - the engine ref and `github.sha`
  - `CUEMSUTILS_REF`, the resolved commit and the version (passed as job outputs from `unit`)
  - per-job passed/failed/skipped/xfailed/xpassed counts, parsed with a short inline `python3 -c` over the JUnit XML
  - the xfail node ids with reasons, and the skip list with reasons
  - the combined coverage %
- [ ] T111 [US6] Validate locally: `$PY -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"`, plus `actionlint` if available. Diff against the C1 table, and check that no job other than `coverage` has `contents: write`. Commit `ci(009): pre-publication gate — parallel unit/integration, combined coverage, cuemsutils_ref`.
- [ ] T112 [US6] Add the pre-publication checklist to `CONTRIBUTORS.md`'s release section (FR-057): "(1) #24 has landed on the C5 structure after cuems-nodeconf's consolidation; (2) dispatch `ci.yml` on the post-merge `feat/xml-refactor` head with `cuemsutils_ref` = cuems-utils' reconciled tag and confirm green; (3) only then publish to PyPI and upload the `.deb`." Commit.
- [ ] T113 [US6] **Ask the maintainer before pushing**: pushing the branch is an outward act. Once approved, push `009-release-line-reconciliation` and dispatch, with `gh workflow run ci.yml --ref 009-release-line-reconciliation -f cuemsutils_ref=xml-refactor-merge-candidate` or the Actions UI. Wait for the run.
- [ ] T114 [US6] Write `specs/009-release-line-reconciliation/evidence/ci-gate.md`: the run URL, the engine SHA, which must equal the local HEAD, the cuemsutils ref, resolved commit and version, each job's conclusion and counts, the strict-xfail list (must equal `strict-xfails.md`), whether the changelog test ran or skipped, the combined coverage, and the line showing the badge step **skipped**. If the run is red, fix it on the branch (new commit), re-dispatch, and record every attempt.

**Checkpoint**: US6 delivered.

---

## Phase 10: Polish and hand-off

- [ ] T115 Complete `specs/009-release-line-reconciliation/evidence/inventory-proofs.md`: every item #1–#23 `proven`, with its proof id and a pass on HEAD; #24 `sequenced` (or `proven` if FR-007's safety net fired). This is SC-002.
- [ ] T116 Rewrite `../.xml-refactor-tag-messages/cuems-engine.txt` (FR-058). This is the planning artefact outside the repository that the spec names, not a sibling's source.
  - `Tag:` → "the post-merge `feat/xml-refactor` head (maintainer fills in after the `--no-ff` merge)".
  - Replace "NOT YET RECONCILED" with "Reconciled with origin/debian/bookworm at `<T016 sha>` (0.1.0rc6-5)" plus the X-1 condition.
  - Add items #1–#13 to "Carries".
  - Leave "Pairs with" unchanged.
  - Add the pre-publication checklist line from T112 and the FR-038 note.
- [ ] T117 Write `specs/009-release-line-reconciliation/evidence/wo-traceability.md`: for each WO section 0–14 and Appendix A, the 009 artefact that carries it (spec FR/SC, research R#, contract C#, or evidence file), following the spec's traceability table. Every row must point at an existing file and anchor.
- [ ] T118 **Final task: delete the work order** (FR-060).
  1. Record `git log -1 --format=%H -- specs/planning/release-line-reconciliation-0.1.1.md` in `spec.md`'s header as "Work order last commit: `<sha>`".
  2. Run `git grep -n release-line-reconciliation-0.1.1 -- . ':!specs/009-*'`. It must be empty; re-point any hit (for example in `specs/planning/`) to `specs/009-release-line-reconciliation/spec.md` first.
  3. `git rm specs/planning/release-line-reconciliation-0.1.1.md`.
  4. Commit `docs(009): retire the work order; 009 artefacts carry it`.
  5. Report the hand-off: the branch head SHA, and that the `--no-ff` merge into `feat/xml-refactor` and the tag re-cut are the maintainer's.

---

## Dependencies and execution order

### Phases

```
P1 Setup ─▶ P2 Foundational ─▶ P3 US1 ─▶ P4 US2 ─┬─▶ P5 US3 ─┐
                                                 └─▶ P6 US4 ─┴─▶ P7 Docs+verify ─▶ P8 US5 ─▶ P9 US6 ─▶ P10
```

- **US1 → US2**: the adaptations fix reds that only exist after the merge (T017).
- **US3 and US4** both depend on US2's checkpoint (T048), and are independent of each other.
  US3's T049 extends T024's changelog test; US4's T059 reuses the T043 and T056/T057 results, so
  T059 waits for T057. Otherwise they can run in either order.
- **P7** depends on US3 and US4. Its re-fetch may loop back to P3.
- **US5** depends on P7. Moving files earlier would turn the clean merges into rename conflicts.
- **US6** depends on US5, because its jobs select tests by directory.
- **P10** depends on everything; T118 is last.

### Inside each story

- The red evidence is captured before its fix: T019→T020, T021→T022, T024→T025, T026a, T028–T033, T034→T035–T040, T043–T046, T049→T050–T053, T057, T089→T090–T105.
- A merge commit holds its own resolutions only (T016).

### Parallel opportunities

- **Setup**: T004 ∥ T005.
- **US1**: T010–T015 resolve different files and can be done in parallel inside the open merge, before T016.
- **US2**:
  - T028 ∥ T029 ∥ T030 ∥ T031 (different test files)
  - T035 ∥ T036 ∥ T037 ∥ T038 ∥ T039 (different source files), after T034
  - T044 ∥ T045 ∥ T046, after T042
- **US4**: T061 ∥ T062 ∥ T063 ∥ T064 ∥ T065.
- **P7**: T067 ∥ T068.
- **US5**: T083 ∥ T084.

## Parallel example: US2 identity conversion

```text
# after T034 has captured failing-first-A-5.txt:
T035  src/cuemsengine/cues/FollowRelay.py
T036  src/cuemsengine/ControllerEngine.py
T037  src/cuemsengine/NodeEngine.py
T038  src/cuemsengine/players/PlayerHandler.py
T039  src/cuemsengine/cues/run_cue.py
# then T040 (sweep the remainder) → T041 (audit)
```

## Implementation strategy

- **MVP = US1 + US2** (Phases 1–4). History is complete, the 10 reds are fixed, and the identity
  contract holds. That is the minimum state in which `0.1.1-1` no longer regresses the fleet.
- **Then the record and the obligations**: US3 and US4. With these, publishing can be gated
  honestly: the changelogs are complete and the X-1 condition is impossible to forget.
- **Then P7**: a stable, re-measured base.
- **Then the cleanup** (US5) and **the gate** (US6), last, as pure moves plus CI.
- At each checkpoint, commit the phase's evidence. To roll a phase back, reset to the previous
  checkpoint's commit, which is recorded in that phase's evidence. Nothing outside the branch moves.

## Notes

- Total: **119 tasks** (T001–T118 plus T026a, added by the 2026-10-18 analysis remediation).
- There is no `[US*]` task for #24's implementation: by clarification it lands after cuems-nodeconf's
  consolidation (FR-007). Its only 009 deliverable is T065. The FR-016 safety-net work becomes tasks
  only if T069 finds #24 on `rc_1`.
- The CI change cannot be proven by pytest. Its proof is T114's dispatched run (plan, Constitution
  Check II boundary).
