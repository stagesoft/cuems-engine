<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UR-1 — No public, non-mutating adoption partition

**From** cuems-engine feature 008, 2026-09-29. Measured against cuems-utils `feat/xml-refactor` @
`2a88a7c` (src identical to `996617f`).

**Observed.** `NetworkMap.partition_by_adoption(network_map)` — the documented non-mutating
replacement for `get_nodes_by_adoption` (`src/cuemsutils/xml/settings.py:228`) — lives only on
`cuemsutils.xml.settings.NetworkMap`. `cuemsutils.xml` is internal (Q14); nothing under
`cuemsutils.tools` or `ConfigManager` exposes it. A consumer that needs "which nodes are adopted"
has no public call to make.

**Reproduction.**
```
grep -rn partition_by_adoption src/cuemsutils/tools src/cuemsutils/__init__.py   # no hits
grep -rn "def partition_by_adoption" src/                                       # xml/settings.py only
```

**Expected.** A public, read-only partition (or an `adopted` view) reachable from
`cuemsutils.tools` — e.g. on `NodeIndex`, or `ConfigManager.adopted_nodes()`.

**Impact here.** The engine keeps its own reader, `ControllerEngine._adopted_node_uuids`, over the
typed map (`adopted is True`, no string parsing). One reader, read-only — but it is a reader the
library could own.

**Workaround taken.** That private reader; its docstring cites this report. Replace it when a
public partition exists.
