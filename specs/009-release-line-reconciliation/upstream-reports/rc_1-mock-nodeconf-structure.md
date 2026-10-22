<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# For the rc_1 maintainer and #24's author (Ion): the structure the engine's mock nodeconf has to take

From cuems-engine feature 009, 2026-10-22. This is contract C5 in full, plus the addressees, context and timing.
**009 builds none of it**: `5a1811c` and `3c11c60` are not ancestors of `rc_1`, so FR-007's safety net did not fire.

## Why `5a1811c` cannot merge as written

It breaks three rules of 0.1.1:

(a) it imports `cuemsutils.xml.XmlReaderWriter`, deprecated (removed in 0.1.2) and forbidden by `tests/contract/test_public_surface.py` (`tests/test_public_surface.py` today);
(b) it detects the controller with `node_type … endswith("master")`: the retired vocabulary, which 0.1.1 refuses at load;
(c) it writes `<adopted>True</adopted>`, which is not a valid `xs:boolean` after cuems-utils 014 (`true` / `false`).

## Placement

| Piece | Path | Why |
|---|---|---|
| Entry point | `src/cuemsengine/scripts/mock_nodeconf.py` (`python -m cuemsengine.scripts.mock_nodeconf`) | packaged mock entry point, like `mock_audioplayer.py` and the rest; **not** a developer tool, so not in `dev/scripts/` |
| systemd drop-in | `debian/`, installed by `cuems-engine-mock` as `cuems-nodeconf.service.d/<name>.conf` | ships only on mock boxes; its exact form is agreed in cuems-nodeconf's consolidation (`cuems-nodeconf-engine-contracts.md`) |
| Tests | `tests/unit/test_mock_nodeconf.py` (plus `tests/integration/` only if a real IPC socket is opened) | the test layout of `rc_1-test-layout.md` |

## Interface

- It listens on `/tmp/nodeconf.ipc` (the path the engine's `NODECONF_IPC_PATH` names) and answers `nodelist_modify` requests with the reply
  shape `ControllerEngine.nodelist_modify` expects.
- **Exactly one reply per request, and never an answer by raising** (the engine-side rule of `_nodelist_refuse`).
- An unknown `modify_action` gets a refusal reply that names it.

## Rules (the 0.1.1 contract)

1. Only the **public** cuemsutils 0.1.1 network-map API: the published load, validate and write path. No `cuemsutils.xml` import.
2. The controller is identified by `node_role` (the `NodeRole` enum), never by `node_type` or a `"master"` suffix.
3. `adopted` is the typed `bool`, serialized `true` / `false`, never `True` / `False`.
4. Ids enter through `as_id` and leave through `id_str` (`cuemsengine.tools.ids`). No `sorted()`, slicing or `.split()` on a raw id.
5. A structured log line per request: action, node id, outcome and reason.

## Behaviours: the red-first test list

| # | Given | When | Then |
|---|---|---|---|
| B1 | a map with a `controller`-role node | an unadopt of that node is requested | refused; the map file is byte-identical afterwards |
| B2 | a node that is not online | an adopt is requested | refused; the map is unchanged |
| B3 | a valid adopt or unadopt | it is applied | the written map validates against 0.1.1's `network_map.xsd` and round-trips through the public loader with the typed `adopted` |
| B4 | an unknown `modify_action` | the request arrives | one refusal reply; the map is unchanged |
| B5 | any refusal | — | exactly one reply; no exception escapes the handler |

Write each as a failing test first, see it fail for its stated reason, then implement.

## Base, timing and route

Built on the post-009 `feat/xml-refactor`, or on `rc_1` once it tracks cuemsutils 0.1.1 (the API does not exist on an rc17 base). It lands
**after cuems-nodeconf's consolidation** and **before 0.1.1 is published**, and is brought in **by SHA merge** (`--no-ff`, no
cherry-pick). The pre-publication checklist in CONTRIBUTORS.md (T112) asks for it.
