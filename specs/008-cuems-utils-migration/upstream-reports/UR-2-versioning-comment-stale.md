<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UR-2 — `versioning.py` comment says only `script` moves

**From** cuems-engine feature 008, 2026-09-29, cuems-utils @ `2a88a7c`.

**Observed.** `src/cuemsutils/xml/versioning.py:30-32`: *"Only ``script`` moves in this feature — the
other five stay at 1"*. The table right below it has `script` 2, **`settings` 2**,
**`hardware_outputs` 2**; `network_map`, `project_mappings`, `project_settings` 1.

**Reproduction.** `sed -n 25,45p src/cuemsutils/xml/versioning.py`.

**Expected.** The comment states the current table (or points at it instead of restating it).

**Impact here.** Low — a consumer planning an upgrade order from the comment would miss that
`settings.xml` is at version 2 (the engine's own test fixture had to be converted, `evidence/step2-*`).

**Workaround taken.** None needed in code; the engine's hand-off lists the deployed documents'
versions from `CURRENT_VERSION`, not from the comment.
