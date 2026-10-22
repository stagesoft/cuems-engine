<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# For cuems-editor: engine contracts that the 0.1.1-1 merge adds (C4 rows W2 and W4)

From cuems-engine feature 009, 2026-10-22. No file of cuems-editor was changed.

| Row | Contract | Shape |
|---|---|---|
| W2 | `project_status` | `{"status": "running" \| "loaded" \| "none", "project_uuid": <text>, "project_unix_name": <text>}`. `project_uuid` is populated in both `running` and `loaded`; a stopped project is `loaded`, no project is `none` with empty strings. A failed load clears `load`, so the previous project's name no longer stays on the wire. Additive. |
| W4 | authored `stop_project` ActionCue, **save path** | The editor saves scripts through cuems-utils' schema, so a script holding `<action_type>stop_project</action_type>` with an empty `<action_target />` is only saved if the installed cuems-utils carries rc17's value (`cuems-utils-x1-x4.md`, X-1). Without it the save is refused by the library, not by the engine. |

Unchanged and paired before this merge: `nodelist_modify` (the editor → engine → nodeconf chain) and
`/engine/status/cluster_warning`.

Engine tests that pin these: `tests/test_controller_commands.py`, `tests/test_controller_stop_project.py`,
`tests/test_stop_project_xsd.py`.
