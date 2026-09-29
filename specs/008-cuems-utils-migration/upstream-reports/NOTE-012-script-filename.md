<!--
SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
SPDX-License-Identifier: GPL-3.0-or-later
-->

# NOTE-012 — the engine reads `script.xml` by a hardcoded name (FR-015)

**For** cuems-utils feature 012 (uuid4 convergence), whose node re-mint must reach every project
script that carries a node uuid in `<output_name>`. **No change in cuems-engine** — recorded only.

**What the engine does.** `BaseEngine.read_script` (`src/cuemsengine/core/BaseEngine.py:491-492`,
rc7) opens `<library_path>/projects/<project>/script.xml` — the file name is a literal. The deploy
manifest ships the same literal (`CuemsDeploy._project_files`: `script.xml`, `mappings.xml`,
`settings.xml`).

**What the editor does.** cuems-editor makes the name configurable: `settings['script_file_name']`
(`CuemsDBProject.py:212`, `repair_durations.py:71`). Its CLI default is `'script.xml'` (`cli.py:41`),
but its own docstring example uses `"cue_script.xml"` (`CuemsProjectManager.py:38`).

**The trap.** A re-mint that discovers scripts through the editor's configured `script_file_name`
and a library whose name is anything but `script.xml` would rewrite a file the engine never loads —
or skip the one it does. Either way stale `<uuid>_<output>` prefixes survive where the engine reads
them, and show up only as "missing" nodes in `cluster_warning` (012 FR-036's detector).

**Suggested handling in 012.** Treat `script.xml` as the engine's contract when deciding the re-mint's
reach (or verify `script_file_name == "script.xml"` on each host before relying on it), and say which
in 012's migration guide.
