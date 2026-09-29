<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# UR-7 — `fade_out` → `stop` is a behaviour change in cuems-engine

**From** cuems-engine feature 008, 2026-09-29, cuems-utils @ `2a88a7c`.

**Observed.** `src/cuemsutils/xml/versioning.py:171-178` rewrites `fade_in` → `play` and `fade_out` →
`stop` on read, justified as *"behaviour-preserving: cuems-engine already dispatches both as
never-implemented stubs treated exactly as play/stop"*. True for `fade_in` (code-identical to `play`).
**Not** for `fade_out`: the engine's old `_handle_fade_out` set the stop flags but never called
`disarm()` and never answered `applied_no_change` — its own TODO named *"the same zombie-process bug
as the old stop handler"*. `_handle_stop` does both.

**Reproduction.** cuems-engine `git show 9f83654^:src/cuemsengine/cues/ActionHandler.py` —
`_handle_fade_out` vs `_handle_stop`; engine test
`tests/test_action_cue.py::TestFadeActionsFromAVersion1Script::test_former_fade_out_is_stop_and_disarms_its_target`
(fixture = cuems-utils' own `tests/data/corpus/pre-008/fade_actions.xml`).

**Expected.** The comment (and any migration text) says the `fade_out` conversion changes behaviour:
a converted `fade_out` disarms its target and a repeat answers `applied_no_change`.

**Impact here.** A welcome change (it fixes leaked player processes), but a change: cuems-engine rc7's
`CHANGELOG.md` states it under `### Changed`.

**Workaround taken.** None needed; the engine deleted its fade handlers (FR-012) and documents the
change.
