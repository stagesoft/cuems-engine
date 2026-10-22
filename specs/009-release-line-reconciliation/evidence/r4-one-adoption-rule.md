<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# R-4: one adoption rule for the GO gate, stop_project and the follow relay (T046)

On one typed map with an adopted+online node, an adopted+offline node, a not-adopted node and a uuid the map does
not hold, `tests/test_controller_stop_project.py::test_stop_project_senders_are_the_adopted_nodes_of_the_go_gate` and
`tests/test_cross_node_follow_controller.py::test_follow_senders_are_the_adopted_nodes_of_the_go_gate` show that the set
of senders each path accepts equals `ControllerEngine._adopted_node_uuids()`, the set the GO gate starts from
(`_adopted_nodes = set(adopted)` in `_resolve_cluster_state`), and is `{controller, online, offline}`.

**Both passed first time → characterization, no production change**: `_handle_stop_project` and `_relay_follow` both test
`sender in self._adopted_nodes`, which is that set. Membership comes from the map, not from liveness, so an adopted
node that went quiet can still report (a quiet node is excluded from `required`, never from `_adopted_nodes`).
The tests use a shared helper `resolve_cluster` added to `tests/network_map_helpers.py`.
