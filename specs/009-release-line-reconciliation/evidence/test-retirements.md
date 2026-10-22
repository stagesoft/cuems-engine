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

## Uncollected `testdev_*.py` (T086, FR-048)

`python_files = ["test_*.py", "*_test.py"]` never collected the three `testdev_*.py` files. Run once on 2026-10-22 with
`pytest tests/testdev_*.py -p no:randomly -rA` (stub applied): 3 passed, 6 failed, 2 errors.

| Case | Outcome | Disposition |
|---|---|---|
| `testdev_ossia_oscquery.py::test_oscquery_server_in_separate_process` | passed | **moved** to `tests/test_ossia_oscquery.py` (no collected test starts an OSCQuery server in another process) |
| `testdev_ossia_oscquery.py::test_oscquery_context_server_in_separate_process` | passed | moved, same file |
| `testdev_ossia_oscquery.py::test_oscquery_server_clients_main_thread` | passed | moved, same file |
| `testdev_ossia_oscquery.py::test_oscquery_context_client_fails_alone`, `::test_oscquery_client_and_server_in_separate_processes`, `::test_oscquery_multiple_clients_in_separate_processes` | failed | retired with the file |
| `testdev_ossia_queue.py` (3 cases) | failed | retired with the file |
| `testdev_engines_communication.py` (2 cases) | errored | retired with the file |

The suite's outcome set changes by exactly these three added tests (`+3 PASSED`); nothing that was collected before is gone.

## Other removals of 14.4

| Item | Reason |
|---|---|
| `tests/pytest_cuems_plugin.py` and the `cuems` marker | not loaded by `addopts` any more; its fixtures `engine_cleanup` / `process_cleanup` live in `tests/conftest.py`; `cuems_cleaner` had no user |
| `specs/planning/README_CLEANUP.md` | described that plugin; the part still true is the "Test cleanup" paragraph of `CONTRIBUTORS.md` |
| `src/cuems/ComunicatorServices.py` | an orphan top-level package, imported by nothing |
| `src/cuemsengine/scripts/system_ports.py` | no console script, no importer; the `system-ports` text in `debian/control` and `debian/postinst` is removed with it |
