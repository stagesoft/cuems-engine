<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UR-5 — `XmlReaderWriter.validate`'s deprecation advice fits only scripts

**From** cuems-engine feature 008, 2026-09-29, cuems-utils @ `2a88a7c`.

**Observed.** Calling `XmlReaderWriter(schema_name=..., xmlfile=...).validate()` warns *"Call to
deprecated method validate. (use cuemsutils.cues.CuemsScript.CuemsScript.validate instead; removed in
v0.1.1)"* — for **every** schema. `CuemsScript.validate()` validates a loaded show script object; it
cannot validate a `settings`, `network_map`, `project_mappings` or `project_settings` document. The
public surface has no stand-alone validator for those; only the `ConfigManager` loaders validate them
(as a side effect of loading).

**Reproduction.** `evidence/baseline-suite-postmerge.txt` (the warning on each of the five
config-schema cases of the old `tests/test_default_mappings_valid.py`), and
`evidence/us2-default-mappings-deprecation.txt` (before/after).

**Expected.** Either per-schema advice in the deprecation message (`ConfigManager.load_*` for config
documents) or a public validator for config documents.

**Impact here.** The engine's fixture-validity test had to be rewritten around the loaders and a
throw-away config directory in the deployed layout.

**Workaround taken.** `tests/test_default_mappings_valid.py` validates each fixture through the
`ConfigManager` loader the engine uses, and scripts through `CuemsScript.load(...).validate()`.
