<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Test retirements (T032, FR-015, FR-048)

| Test | Retired in | Reason | Replacement |
|---|---|---|---|
| `tests/test_cluster_identity.py::test_script_finished_from_str_senders_closes_the_run` | T032 | 869fhjdp8 deleted the controller's `script_finished` aggregator (`_finished_nodes`); the test exercised only that aggregator. 008 is frozen (FR-015), so the test is retired rather than adapted. | T033: four cases in the same file that keep the identity coverage the retired test gave for `str` senders on the paths that replaced it |

## A-4 replacement (T033)

`test_stop_project_from_an_adopted_str_sender_stops_the_show`,
`test_stop_project_from_a_node_that_is_not_adopted_is_refused`,
`test_follow_from_an_adopted_str_sender_is_relayed`,
`test_follow_from_a_node_that_is_not_adopted_is_refused`, over the typed network map of the file's own
`controller` fixture (map ids are `Uuid`, senders arrive as `str`).

All four **passed first time** → *characterization, no production change*: `_adopted_nodes` is filled from the
typed map through `as_id` (`_resolve_cluster_state`), and `Uuid` compares and hashes equal to its text, so the
`sender not in self._adopted_nodes` checks of `_handle_stop_project` and `_relay_follow` already accept a `str`
sender of an adopted node and refuse an unadopted one. No `failing-first-A-4-replacement.txt` exists for that reason.
