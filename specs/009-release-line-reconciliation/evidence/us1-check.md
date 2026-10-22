<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# US1 independent test (T027)

HEAD `ff91bd4`, after a fresh `git fetch --all --tags`.

```
$ git rev-list --count HEAD..origin/debian/bookworm
0
$ git rev-list --count HEAD..origin/rc_1
0
$ merge-base --is-ancestor 35cbe78 HEAD  -> yes
$ merge-base --is-ancestor d50ee4b HEAD  -> yes
$ merge-base --is-ancestor v0.1.0rc5-6 HEAD  -> yes
$ merge-base --is-ancestor 5a1811c HEAD  -> no (FR-007: #24 stays out)
$ merge-base --is-ancestor 3c11c60 HEAD  -> no (FR-007: #24 stays out)
```

## Proof files of #1–#13 and #25 on HEAD

| File | Result on HEAD |
|---|---|
| `tests/test_disarm_video_layers.py` | 8 passed  |
| `tests/test_video_placement_failure.py` | 6 passed  |
| `tests/test_arm_publish_gate.py` | 36 passed  |
| `tests/test_arm_inventory.py` | 19 passed  |
| `tests/test_arm_wait_messages.py` | 8 passed  |
| `tests/test_player_handler_port_wait_abort.py` | 5 passed  |
| `tests/test_cue_media_dimensions.py` | 17 passed  |
| `tests/test_own_media_sizes.py` | 11 passed  |
| `tests/test_media_duration.py` | 5 failed, 21 passed  |
| `tests/test_loop_video_wraparound.py` | 2 failed, 1 passed  |
| `tests/test_cross_node_follow_controller.py` | 14 passed  |
| `tests/test_cross_node_follow_hook.py` | 17 passed  |
| `tests/test_cross_node_follow_owner.py` | 48 passed  |
| `tests/test_cross_node_follow_receiver.py` | 56 passed  |
| `tests/test_controller_cue_names.py` | 9 passed  |
| `tests/test_node_engine_load_orphan_eperm.py` | 2 passed  |
| `tests/test_player_handler_orphan_kill.py` | 35 passed  |
| `tests/test_controller_commands.py` | 46 passed  |
| `tests/test_video_unrouted_output.py` | 26 passed  |
| `tests/test_controller_stop_project.py` | 18 passed  |
| `tests/test_node_stop_project.py` | 18 passed  |
| `tests/test_node_unload_project.py` | 8 passed  |
| `tests/test_project_load.py` | 21 passed  |
| `tests/test_action_cue.py` | 1 failed, 81 passed  |
| `tests/test_cluster_identity.py` | 1 failed, 5 passed  |
| `tests/test_identity_sweep.py` | 1 failed, 6 passed  |

The only failures are the 10 expected reds (A-1 ×1 in `test_action_cue.py`, A-2 ×5 in `test_media_duration.py`,
A-3 ×2 in `test_loop_video_wraparound.py`, A-4 ×1 in `test_cluster_identity.py`, A-6 ×1 in `test_identity_sweep.py`),
which US2 fixes (T028–T033). #22, #23 and #2 are proven by their own tests (`inventory-proofs.md`).

## Changelog assertions (C3, 1–4)

`tests/test_changelog_complete.py`: 9 passed (top entry `0.1.1-1`; every version of bookworm ∪ rc_1 ∪ the `v0.1.0*`
tags is listed; byte-identical entries; strictly descending dpkg order). Assertion 5 (`CHANGELOG.md`) arrives in T049.

## #24

`5a1811c` and `3c11c60` are **not** ancestors (T003 recorded that `rc_1` does not carry them), so no FR-016 / A-8 tasks
apply.
