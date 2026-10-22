<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# For cuems-nodeconf: the mock's planned drop-in over your unit (C4 row W6)

From cuems-engine feature 009, 2026-10-22. No file of cuems-nodeconf was changed.

**What is planned.** `cuems-engine-mock` (#24, `feat/mock-nodeconf` `5a1811c` + `debian/mock-nodeconf-dropin` `3c11c60`) is meant to ship a
`cuems-nodeconf.service.d/<name>.conf` drop-in on mock boxes, replacing the real nodeconf with a mock that answers
`nodelist_modify` on `/tmp/nodeconf.ipc`. That is a **cross-package edge**: the mock package overrides a unit that
cuems-nodeconf owns.

**Why this is not built in 009.** #24 lands after cuems-nodeconf's consolidation, because the drop-in's exact shape (what it
overrides: `ExecStart`, `ConditionPathExists`, `Conflicts`) has to be agreed there. The engine's side of the structure, the
mock's placement, interface, rules and the five behaviours it must satisfy, is written down in `rc_1-mock-nodeconf-structure.md`
(contract C5).

**What the engine asks of cuems-nodeconf:**

1. Tell us the unit name and the override form you accept (drop-in vs. a `Conflicts=`/`Alias` arrangement).
2. Confirm that a mock answering on `/tmp/nodeconf.ipc` with the reply shape `ControllerEngine.nodelist_modify` expects is enough.
3. Say if the real nodeconf's `<ip>` ownership in `network_map.xml` matters on a mock box (single-box controller note in the engine's CLAUDE.md).

For information: with nodeconf **absent** the engine answers a UI adoption click with an immediate, actionable refusal (the
`os.path.exists(NODECONF_IPC_PATH)` pre-check), not after the 15 s IPC timeout.
