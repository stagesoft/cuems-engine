<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Inventory and proofs (T005)

States per `data-model.md`: `pending → absorbed → adapted → proven` (`#24`: `sequenced`).
Created 2026-10-22; the table is updated by T020/T022/T026a/T048/T058/T068 and completed by T115.
Test files named here are the ones that arrive from `origin/debian/bookworm` @ `3108b4f`; the node ids
are filled in when they run on the merged tree (T027, T048).

| # | Item | Method | Seams | Proof | State |
|---|---|---|---|---|---|
| 1 | Video scale readback (float32 tolerance), placement failures at ERROR, disarm skips layers removed by `/reset` (869f8hfra, #20) | M | A-1 | `tests/test_disarm_video_layers.py`, `tests/test_video_placement_failure.py`; A-1 in `tests/test_action_cue.py` | pending |
| 2 | Dead `VideoPlayer` deleted (869f8v8yv, #21; `e890954`) | M | — | **T026a**: `tests/test_dead_videoplayer_removed.py` (no test came with it) | pending |
| 3 | Pre-arm of the next segment; one arm per cue; arm epochs; JACK wait ends on a dead player; unarmable GO skips (869f9wqpn, #22) | M | — | `tests/test_arm_publish_gate.py`, `tests/test_arm_wait_messages.py`, `tests/test_player_handler_port_wait_abort.py` | pending |
| 4 | Pre-arm measurement log lines (#22) | M | — | `tests/test_arm_inventory.py` | pending |
| 5 | Video pixel size from the project; nodes report their own differing media (869fat84r, #22) | M | A-2, R-1 | `tests/test_cue_media_dimensions.py`, `tests/test_own_media_sizes.py`, `tests/test_media_duration.py` (A-2); R-1 test (T043) | pending |
| 6 | Video wraparound only for repeating cues (869fa89uh, #23) | M | A-3 | `tests/test_loop_video_wraparound.py` | pending |
| 7 | Cross-node Auto follow relay, `run_seq`, `FollowRelay` (869fc8ytz, #25) | M | A-5 | `tests/test_cross_node_follow_controller.py`, `_hook.py`, `_owner.py`, `_receiver.py`; wire-site tests (T034) | pending |
| 8 | Audio ready gate: wire on RUNNING, edge-by-edge repair at GO (869fbyjzx/869fcvz85, #27, #30) | M | — | `tests/test_arm_wait_messages.py`, `tests/test_player_handler_port_wait_abort.py` | pending |
| 9 | Cue names on the `:9190` channel (869fedahu, #28) | M | A-5, R-2 | `tests/test_controller_cue_names.py`; R-2 test (T044) | pending |
| 10 | Orphan-kill sweeps never abort a load; own-user players only (869evtdf7, #29) | M | — | `tests/test_node_engine_load_orphan_eperm.py`, `tests/test_player_handler_orphan_kill.py` | pending |
| 11 | `project_status` with three states; a failed load clears `load` (869dr2kzh/869dr2k2h, #32) | M + R | A-5 | `tests/test_controller_commands.py` (resolved per T010), wire-site test 4 (T034) | pending |
| 12 | Unrouted video outputs stay dark; `display.conf` `enabled=` (869fgq3xv, #33) | M | A-5 | `tests/test_video_unrouted_output.py`, wire-site test 6 (T034) | pending |
| 13 | `stop_project` ActionCue; ADD/UPDATE ignored while not running; arm watchdog restarts after STOP; `script_finished` removed (869fhjdq5/869fhjdp8, #35/#36) | M + R | A-4, A-6, R-3, R-4, X-1 | `tests/test_controller_stop_project.py`, `tests/test_node_stop_project.py`, A-4 replacement (T033), A-6 (T031), R-3/R-4 (T045/T046) | pending |
| 14 | Isolated build venv; build fails if rtmidi is not vendored (869f79ecc) | M | — | recorded check: `evidence/debian-rules-audit.md` (T055), `evidence/bookworm-build.md` (T056) | pending |
| 15 | `cffi-gen-src` no longer shipped | M | X-2 | recorded check: T055, T056 | pending |
| 16 | Mock wrappers renamed; mock `Conflicts:`; postinst path text | M + R | — | recorded check: T055, T056 (`dpkg -I`) | pending |
| 17 | SPDX headers on `debian/control`, `debian/rules` | M + R | — | recorded check: T055 | pending |
| 18 | Changelog entries `rc3-1…rc6-6` | M + R | FR-030 | `tests/test_changelog_complete.py` (T024, T049) | pending |
| 19 | `docs/unattended-playback.md`, `docs/index.md`, CLAUDE.md additions | M | FR-040, FR-041 | recorded check: T067/T068 | pending |
| 20 | `cuemsutils >= 0.1.0rc17` | R → ours | subsumed only if X-1 holds | T058 relation verdicts; X-1 xfails (T060) | pending |
| 21 | Hotfix line `rc5-2…rc5-6` | D + `-s ours` | FR-008 | `evidence/hotfix-rc5-equivalence.md` (T023), changelog test (T024–T026) | pending |
| 22 | `35cbe78`: output maps ignore inputs (silent-audio bug) | M by SHA | A-7 | `tests/test_node_output_maps.py::test_audio_output_zero_resolves_to_the_output_not_the_input`, `::test_video_output_zero_resolves_to_the_output_not_the_input` (red `failing-first-A-7.txt`; mutation check: reading inputs gives `system:capture_1`) | proven |
| 23 | `d50ee4b`: mock players report JACK ready | M by SHA | — | `tests/test_mock_players_jack_ready.py` (4 tests; red `failing-first-23.txt`) | proven |
| 24 | `5a1811c` + `3c11c60`: mock nodeconf and its drop-in | not in 009 | FR-016a | `upstream-reports/rc_1-mock-nodeconf-structure.md` (T065) | sequenced (pending T065) |
| **25** | **New 2026-10-19, not in the spec:** project unload reaches nodes as an unload; `_teardown_project`; docs on the A/V loop guarantee (869fh8kef, #41; released in `0.1.0rc6-6`) | M | A-5 (ids in the new unload path), changelog | `tests/test_node_unload_project.py`, `tests/test_cross_node_follow_controller.py` (unload forwards `/engine/command/unload`, `run_seq` bumped first), `tests/test_project_load.py` | pending |

`NO PROOF` flags: none beyond #2 (T026a). Every other item has a bookworm test file or a recorded check.
