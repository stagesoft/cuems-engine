<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Identity audit — 009 (T040, T041, SC-005)

Method of `specs/008-cuems-utils-migration/evidence/identity-audit.md`, re-run over the absorbed code
(`git diff e994a5e HEAD -- src/`) on HEAD after the A-5 conversions. 008 stays frozen (FR-015); this file is
its 009 counterpart.

**Rule**: an id enters through `as_id`, leaves through `id_str`, or the site is listed as safe with a reason.

## Scans

| Scan | Result |
|---|---|
| `git grep -n 'import.*\bUuid\b' -- src/` | empty |
| `sorted(` / `min(` / `max(` over absorbed lines | 4 hits, none over ids: `sorted(display_regions.keys())` (connector names), `sorted(self._video_outputs.items())` (output ids `"0"`, `"1"`, already text), two `max()` on retry arithmetic |
| slices `[a:b]` over absorbed lines | none |
| `.split("-")` over absorbed lines | two: both the JACK-name slug, now `id_str(cue.id).split("-")` |
| `.join(` over absorbed lines | the slugs above; one over process names (orphan-kill), not ids |
| `isinstance(…, str)` over absorbed lines | none |
| `json.dumps` over absorbed lines | none |
| `str(<id>)` over `src/` after the sweep | pre-existing only: `EngineStatus.py:184`, `ActionHandler.py:616`, `CueHandler.py:1023`, `DmxPlayer.py:44` (in `e994a5e`, not absorbed code; 008's audit already covers the first and the third as safe with an explicit `str`) |

**Findings: none open.**

## Converted sites and the green test that covers each

| Site (HEAD) | Direction | Helper | Covering test (green before and after unless marked red) |
|---|---|---|---|
| `FollowRelay._emit` `source`, `target` | out | `id_str` | `test_identity_sweep.py::test_follow_announce_emits_its_cue_ids_as_text`, `::test_follow_cancel_emits_its_cue_ids_as_text` |
| `FollowRelay._on_announce`, `_on_cancel` `source_id`/`target_id` | in | `as_id` | `::test_a_follow_announced_with_str_ids_finds_the_scripts_uuid_cues`, `tests/test_cross_node_follow_receiver.py` (56) |
| `ControllerEngine._handle_stop_project` `cue_id` and its two log lines | in / log | `as_id`, `id_str` | `tests/test_cluster_identity.py::test_stop_project_from_an_adopted_str_sender_stops_the_show` (+ refusal twin), `tests/test_controller_stop_project.py` |
| `ControllerEngine.get_project_status` `project_uuid` | out | `id_str` | `::test_project_status_reports_the_project_uuid_as_text`, `tests/test_controller_commands.py` |
| `ControllerEngine._broadcast_cue_name`, cue-name replay address | out | `id_str` | `::test_cue_name_address_carries_the_cue_id_as_text`, `tests/test_controller_cue_names.py` |
| `NodeEngine._notify_stop_project` `data["cue"]` | out | `id_str` | `::test_stop_project_status_op_carries_the_cue_as_text`, `tests/test_node_stop_project.py` |
| `NodeEngine.check_unrouted_video_outputs` `cue_id` | out | `id_str` | **red first**: `::test_unrouted_video_report_names_its_cue_as_text` (`failing-first-A-5.txt`), `tests/test_video_unrouted_output.py` |
| `ActionHandler._handle_stop_project` `origin_cue_id` | out | `id_str` | `::test_stop_project_outcome_names_its_origin_cue_as_text` |
| `PlayerHandler` (`new_audio_output` ×5 incl. the slug, kill list, `first_unrouted_report` key) | out / key | `id_str` | `::test_audio_player_jack_name_is_the_cue_id_without_hyphens`, `tests/test_player_handler_*.py`, `tests/test_video_unrouted_output.py` |
| `run_cue` JACK-name slug | out | `id_str` | covered through `tests/test_arm_*` and the slug test above (same expression) |

## Not converted, with the reason

- `communications_thread.add_cue/remove_cue/update_*` taking `cue.id` (`Uuid`) in NNG `target`/`data`: serialized by
  `HubServices.send_message`; `CTimecode` imports `json_fix`, which makes `json` honour `Uuid.__json__`
  process-wide. Safe, as 008's audit records. Unchanged, and still resting on a library-side global patch (UR-6).
- f-string interpolation of `cue.id` in log lines: `Uuid` formats as its text. No rule is broken by it
  (the rule names concatenation and joins), and converting several hundred log sites would be churn without a test.
- Dict and set keys by `cue.id` (`_armed_cues_set`, the arming registry): `Uuid` hashes and compares equal to its
  text, so a `str` lookup finds it.

## What the A-5 tests actually established

Eight of the nine new cases passed before the conversions; `id_str` is `str()` with `None` rendered as `""`, so for a
`Uuid` input the converted code emits the same text. Those eight are characterization tests, and the conversions
were the refactor step. One was red for the stated reason: the unrouted-video report carried a raw `Uuid`.
