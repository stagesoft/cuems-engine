<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kill_cuems.sh vs kill_cuems_processes.py (T076, accepted default Q9)

Binary names 869evtdf7 anchors its sweeps on: `cuems-audioplayer`, `cuems-dmxplayer`, `cuems-videocomposer`,
own-user processes only.

| Pattern | `kill_cuems.sh` | `kill_cuems_processes.py` | Current? |
|---|---|---|---|
| `cuems`, `pytest.*cuems`, `python.*cuems` | yes | yes | broad, matches every name below |
| `cuems-audioplayer` | yes | yes | yes |
| `cuems-dmxplayer` | yes | yes | yes |
| `videoplayer-cuems` | **yes** | **yes** | **stale**: the player is `cuems-videocomposer` |
| `ControllerEngine` / `NodeEngine` / `OssiaServer` / `EditorWsServer` | yes | yes | kept |

Both scripts carried the same stale name. `dev/scripts/kill_cuems.sh` now matches `cuems-videocomposer` instead of
`videoplayer-cuems`; `kill_cuems_processes.py` (a Python duplicate of the same list) is deleted. Neither is restricted to
the caller's own processes; both run as the developer, so another user's processes fail with EPERM instead of being killed.
