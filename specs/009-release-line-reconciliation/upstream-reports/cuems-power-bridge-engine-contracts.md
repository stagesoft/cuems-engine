<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# For cuems-power-bridge: engine contracts that the 0.1.1-1 merge adds (C4 rows W2 and W4)

From cuems-engine feature 009, 2026-10-22. No file of cuems-power-bridge was changed. Its `0.3.1-2` half is absorbed in its
own 0.4.0-1 reconciliation.

| Row | Contract | Shape |
|---|---|---|
| W2 | `project_status` with three states | `status` is `running`, `loaded` or `none`; `project_uuid` and `project_unix_name` accompany it. A failed load clears `load`. |
| W4 | authored `stop_project` | After the cue's STOP an operator-style sequence follows: `running no` → `armed no` → `armed yes`. A `/go` during the re-arm window is answered 409 `not_armed`; the bridge's persistent auto-load must not reload on that window. Needs cuems-utils 0.1.1 with rc17's value for a project that holds the cue to load at all (`cuems-utils-x1-x4.md`, X-1). |

Engine tests that pin these: `tests/test_controller_commands.py`, `tests/test_controller_stop_project.py`.
