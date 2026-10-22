<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# R-3: a targetless stop_project reaches its handler (T045)

`tests/test_controller_stop_project.py::TestStopProjectBuiltInCode` builds the ActionCue from a dict
(`ActionCue({"action_target": "", "action_type": "stop_project"})`, no target object) and runs it through
`ActionHandler.execute_action`: **applied, not rejected**, `target_id` None. `PROJECT_SCOPE_ACTIONS` exempts it from the
"Missing target" guard, and "other project actions still rejected" (`pause_project`, `resume_project`, `load`,
`unload`) holds. The rc_1 test `tests/test_action_cue.py::TestStopProjectAction` stays green.

**Passed first time → characterization, no production change.**
