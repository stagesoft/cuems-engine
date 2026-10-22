<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Expected merge-induced reds (T007)

Spec M5 / WO §6.1: with a mechanical FR-004 resolution, the merged tree fails 10 tests that pass on
`e994a5e`. Arm A on this host (T006) had **0** failures (885 passed + 1 xfailed, then 32 integration
passed): the 8 environmental failures of WO §6.1 do not occur here, so SC-003's bound is the empty set.

| Seam | Count | Node(s) |
|---|---|---|
| A-1 | 1 | `tests/test_action_cue.py::TestFadeActionsFromAVersion1Script::test_former_fade_out_is_stop_and_disarms_its_target` |
| A-2 | 5 | `tests/test_media_duration.py` (five tests; the player-handler mock lacks `cue_media_dimensions`) |
| A-3 | 2 | `tests/test_loop_video_wraparound.py` (two tests using `SimpleNamespace(duration=…)`) |
| A-4 | 1 | `tests/test_cluster_identity.py::test_script_finished_from_str_senders_closes_the_run` |
| A-6 | 1 | `tests/test_identity_sweep.py::test_an_editor_cue_id_as_str_matches_the_scripts_uuid_cue_id` |

Exact node ids of A-2 and A-3 are read off `suite-arm-B.txt` (T017).

## New findings (appended by T017)

*None.* Arm B (`suite-arm-B.txt`, merge commit `1c12959`) fails exactly the 10 ids above, including after
absorbing the post-spec `0.1.0rc6-6` delta. The A-2 ids are the four `test_run_sets_end_to_start_plus_converted_duration[video-…]`
cases plus `test_run_with_no_duration_is_zero_and_warned[video]`; the A-3 ids are
`test_counted_loop_wraps_then_clamps_on_its_last_pass` and `test_infinite_loop_keeps_wrapping`.
