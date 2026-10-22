<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# For cuems-frontend: engine contracts that the 0.1.1-1 merge adds (C4 rows W3 and W4)

From cuems-engine feature 009, 2026-10-22. The engine ships these in `0.1.0rc6-3 … rc6-6`; 0.1.1-1 contains them. No file of
cuems-frontend was changed. Confirm your half at your re-cut tag.

| Row | Contract | Shape |
|---|---|---|
| W3 | `/engine/status/cue_name/<uuid>` on `:9190` | the controller broadcasts each cue's name once per load, **after** `/engine/status/load <project>` (duplicated projects share cue uuids, so treat a change of `load` as "new table" and refill it from the burst that follows), and replays them to late joiners (after `cue_enabled`, before `mixer`). The address segment is the cue id as text; the argument is the name, `""` for a cue with no name. Additive: older UIs ignore it. |
| W4 | authored `stop_project` ActionCue | `<action_type>stop_project</action_type>` with **no target** (`<action_target />`). The engine reveals it on every node and the controller runs its own STOP: `running no`, every cue reset to 0, nodes re-armed. The cue is a hard chain break; disabled, it is transparent (rehearsal mode). Needs cuems-utils 0.1.1 with rc17's value (see `cuems-utils-x1-x4.md`). |

For awareness (W1): the GO value is a **dict** carrying `run_seq`, and `follow` status ops exist; the engine is not
wire-compatible with engines before 0.1.0rc6-3, so a cluster upgrades every host together.

Engine tests that pin these: `tests/test_controller_cue_names.py`, `tests/test_controller_stop_project.py`,
`tests/test_node_stop_project.py`, `tests/test_identity_sweep.py` (the id leaves as text).
