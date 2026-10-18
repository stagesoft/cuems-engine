<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contract C4: wire contracts that the merge adds, as consumed by siblings

**Implements** FR-023 and FR-038. This feature does not create these contracts; they shipped in
rc6-3…rc6-5. It **records** them, so that each sibling's reconciliation can confirm its half at its
re-cut tag. Every outgoing id leaves through `id_str` (FR-017).

| # | Contract | Producer | Shape | Consumers | Compatibility |
|---|---|---|---|---|---|
| W1 | GO value with `run_seq`; `follow` status ops (item 7, `FollowRelay`) | controller and node engines | GO value is a **dict** carrying `run_seq`. `follow` ops carry `source`/`target` cue ids as `id_str` text | every engine in the cluster | **Not** compatible with pre-rc6-3 engines. Every host upgrades together (FR-038) |
| W2 | `project_status` (item 11) | controller | `{"status": "running"\|"loaded"\|"none", "project_uuid": id_str, "project_unix_name": str}`. A failed load clears `load` | cuems-power-bridge (`0.3.1-2`, `main`), cuems-editor | additive |
| W3 | `/engine/status/cue_name/<uuid>` on `:9190` (item 9) | controller | the address segment is `id_str(cue.id)`; the argument is the name, `""` for an empty `<name/>` | cuems-frontend (`dev`) | additive; older UIs ignore it |
| W4 | `stop_project` ActionCue, authored (item 13) | — | `<action_type>stop_project</action_type>`, **no target** | cuems-frontend `dev` (STOP chips, PR #15), cuems-editor save path (through utils' XSD, X-1), cuems-power-bridge `0.3.1-2` | needs cuems-utils 0.1.1 with rc17's value and S-1's target rule |
| W5 | Unrouted-video report (item 12) | node | `{"cue_id": id_str, …}` | journal / controller | internal |
| W6 | `cuems-nodeconf.service.d` drop-in (#24, planned) | `cuems-engine-mock` | overrides a cuems-nodeconf unit on mock boxes | cuems-nodeconf | **shape settled in cuems-nodeconf's consolidation**; #24 lands after it (FR-016a) |

Unchanged and paired before the merge-base: `/engine/status/cluster_warning`, `nodelist_modify`, and
`cuems-common (>= 1.3.1~)`.

**Tests that pin the engine half**: the rc_1 tests that came with items 7, 9, 11, 12 and 13, plus one
`test_identity_sweep.py` case per wire-leaving id site (FR-017).
