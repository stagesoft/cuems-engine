<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contract C5: the agreed structure of the engine's mock nodeconf (#24)

**Implements** FR-016a, and FR-016 when the safety net fires. This is the normative content of
`upstream-reports/rc_1-mock-nodeconf-structure.md`. That message adds the addressees, the context and
the timing. **009 builds none of this** unless `rc_1` has taken #24 by hand-off (FR-007).

## Placement

| Piece | Path | Why |
|---|---|---|
| Entry point | `src/cuemsengine/scripts/mock_nodeconf.py` (`python -m cuemsengine.scripts.mock_nodeconf`) | packaged mock entry point, like `mock_audioplayer.py` and the rest (FR-049); **not** a developer tool, so not in `dev/scripts/` |
| systemd drop-in | `debian/` → installed by `cuems-engine-mock` as `cuems-nodeconf.service.d/<name>.conf` | ships only on mock boxes; its exact form is agreed in cuems-nodeconf's consolidation (W6) |
| Tests | `tests/unit/test_mock_nodeconf.py` (plus `tests/integration/` only if a real IPC socket is opened) | C2 layout |

## Interface

- It listens on `/tmp/nodeconf.ipc` (the path the engine's `NODECONF_IPC_PATH` names) and answers
  `nodelist_modify` requests with the reply shape `ControllerEngine.nodelist_modify` expects.
- **Exactly one reply per request, and never an answer by raising** (the engine-side rule of
  `_nodelist_refuse`).
- An unknown `modify_action` gets a refusal reply that names it.

## Rules (0.1.1 contract)

1. Only the **public** cuemsutils 0.1.1 network-map API: the published load, validate and write path.
   No `cuemsutils.xml` import; `tests/contract/test_public_surface.py` stays green.
2. The controller is identified by `node_role` (the `NodeRole` enum), never by `node_type` or a
   `"master"` suffix.
3. `adopted` is the typed `bool`, serialized `true`/`false`, never `True`/`False`.
4. Ids enter through `as_id` and leave through `id_str`. No `sorted()`, slicing or `.split()` on a
   raw id.
5. Structured log line per request: action, node id, outcome and reason.

## Behaviour (each one is a red-first unit test)

| # | Given | When | Then |
|---|---|---|---|
| B1 | a map with a `controller`-role node | an unadopt of that node is requested | refused; the map file is byte-identical afterwards |
| B2 | a node that is not online | an adopt is requested | refused; the map is unchanged |
| B3 | a valid adopt or unadopt | it is applied | the written map validates against 0.1.1's `network_map.xsd` and round-trips through the public loader with the typed `adopted` |
| B4 | an unknown `modify_action` | the request arrives | one refusal reply; the map is unchanged |
| B5 | any refusal | — | exactly one reply; no exception escapes the handler |

## Base and timing

It is built on the post-009 `feat/xml-refactor`, or on `rc_1` once it tracks cuemsutils 0.1.1 (the
API does not exist on an rc17 base). It lands **after cuems-nodeconf's consolidation** and before
0.1.1 is published, merged by SHA. The pre-publication checklist (FR-057) checks it.
