<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# dev/

Developer tools. **Nothing under `dev/` is packaged or run by CI.**

| Tool | What it is for |
|---|---|
| `scripts/link-dev.sh` | Replaces the installed `cuemsengine` package under `/usr/lib/cuems` with a symlink (the editable `cuemsengine.pth` overlay) to this source tree, so edits are used by the system services. Needs `sudo`. Restore with a reinstall of the `.deb`. |
| `scripts/kill_cuems.sh` | Kills stubborn CUEMS processes with escalating force (`--list`, `--dry-run`, `--force`). |
| `scripts/osc_send.py` | Sends a single OSC message to a server: `osc_send.py <path> <value> [--ip IP] [--port PORT]`. |

Test fixtures live in `tests/data/`, not here.
