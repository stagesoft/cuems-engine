<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Re-measurement at implementation start (T003)

Measured 2026-10-22 after `git fetch --all --tags`, on `009-release-line-reconciliation` @ `aa0ffe6`.

| Measure | Spec (M1/M7, 2026-10-17) | Now | Moved? |
|---|---|---|---|
| `HEAD..origin/debian/bookworm` | 119 (`b8431a3`) | **128** (`3108b4f`) | **yes, +9** |
| `HEAD..origin/rc_1` | 84 (`698e777`) | **90** (`06f733a`) | **yes, +6** |
| Newest build on bookworm | `0.1.0rc6-5` | **`0.1.0rc6-6`** (tag `v0.1.0rc6-6` → `098eb25`, 2026-10-19) | **yes** |
| `35cbe78` (#22), `d50ee4b` (#23) ancestors of `origin/rc_1` | no | no | no |
| `5a1811c`, `3c11c60` (#24) ancestors of `origin/rc_1` | no | no | no |
| `xml-refactor-merge-candidate^{commit}` | `e994a5e` | `e994a5e` | no |
| `rc_1`'s own `debian/changelog` | `0.1.0rc2-3` | `0.1.0rc2-3` | no |
| `gh` | absent | absent | PR state: *unchecked: no gh* |

## What moved: one new release, `0.1.0rc6-6`

New commits on bookworm past `b8431a3` (9) and on rc_1 past `698e777` (6):

| sha | what |
|---|---|
| `7bc5d3d` | fix(unload): nodes unload the project instead of re-arming it (869fh8kef, #41) |
| `af27553` | test(follow): unload forwards `/engine/command/unload`, `run_seq` still bumped first |
| `89f2a29`, `d10d66d`, `06f733a` | docs: the A/V loop sync guarantee (README, CLAUDE.md) |
| `93b9bba` | rc_1: merge of #41 |
| `d586b0a`, `62e788e`, `855d3fc`, `3108b4f` | bookworm: merges of rc_1 and #41, `release: cuems-engine 0.1.0rc6-6`, PR #42 |

Files touched in the release delta (`b8431a3..3108b4f`): `CLAUDE.md`, `README.md`, `debian/changelog`,
`src/cuemsengine/ControllerEngine.py`, `src/cuemsengine/NodeEngine.py`, `tests/test_controller_commands.py`,
`tests/test_cross_node_follow_controller.py`, `tests/test_node_unload_project.py` (new),
`tests/test_project_load.py`. No dependency change (`cuems-utils >= 0.1.0rc17`).

**Decision (per T003's own rule).** The inventory gains **#25** (869fh8kef, #41, released in rc6-6),
method M. Everything else in the tasks reads as written, with the bookworm sources being
`origin/debian/bookworm` @ `3108b4f` and the newest build `0.1.0rc6-6`. Where a task or message says
`0.1.0rc6-5`, this run writes `0.1.0rc6-6`. The merge is likely to conflict in two more places
(`ControllerEngine.py`, `NodeEngine.py`, `tests/test_controller_commands.py`): T008 records the real list, and
T008 stops on a list that differs from M4.

## The two branches T003 must settle

- **#24 on `rc_1`**: `5a1811c` and `3c11c60` are **not** ancestors of `origin/rc_1`. FR-007's safety net does
  **not** fire. #24 stays out; T027 asserts they are not ancestors; no FR-016 / A-8 tasks are added.
- **#22/#23 on `rc_1`**: `35cbe78` and `d50ee4b` are **not** ancestors of `origin/rc_1`. T018 absorbs nothing
  of them; T019/T021 show their red on HEAD; T020/T022 merge them by SHA.
- Changelog headers newer than `0.1.0rc6-5`: only bookworm's `0.1.0rc6-6` (above). No `v0.1.0*` tag past it.
