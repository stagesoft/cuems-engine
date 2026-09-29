<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UR-6 — No public id-coercion helper

**From** cuems-engine feature 008, 2026-09-29, cuems-utils @ `2a88a7c`.

**Observed.** The rule that turns a raw value into an id — uuid4 → `Uuid`, other non-empty text
unchanged, empty → `None` — is `_UuidAdapter.decode` (`src/cuemsutils/xml/adapters.py:119-142`), in
internal `cuemsutils.xml`. Consumers receive ids from other sources too (settings, NNG payloads,
editor JSON, `output_name` prefixes) and must apply the same rule to compare them with the map's.

**Expected.** The rule published under `cuemsutils.tools` (next to `Uuid`).

**Impact here.** cuems-engine mirrors it in `cuemsengine/tools/ids.py::as_id` (~6 lines) — a copy of
library leniency that can drift.

**Workaround taken.** That mirror, with a docstring pointing here. Delete it for the public helper.

**Status upstream.** 012's draft spec plans to publish the rule (FR-030, assumption 6). Related: the
engine relies on `json_fix` (imported by `cuemsutils.tools.CTimecode`) to serialize `Uuid` in NNG and
editor JSON — a process-wide patch; worth stating as a guarantee if consumers are meant to rely on it
(`evidence/identity-audit.md`).
